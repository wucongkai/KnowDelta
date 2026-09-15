import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from knowdelta.storage import PipelineError, asset_file, read_json

from .config import get_settings
from .db import get_db
from .schemas import Capabilities, Health, JobCreate, JobList, JobView, NoteView
from .services import artifact, capabilities, create_job, get_job, require_mode, retry_job
from .tables import Dispatch, Job, now

DB = Annotated[Session, Depends(get_db)]
IDKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)]


def make_app(*, dispatch: bool = True) -> FastAPI:
    load_dotenv(Path.cwd() / ".env", override=False)
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()
        thread = None
        if dispatch:
            from .worker import dispatch_loop

            thread = threading.Thread(target=dispatch_loop, args=(stop,), daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=5)

    app = FastAPI(title="KnowDelta API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "localhost",
            "127.0.0.1",
            "[::1]",
            "testserver",
            "api",
        ],
    )

    @app.middleware("http")
    async def local_request_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = set(settings.cors_origins) | {
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:4173",
            "http://localhost:4173",
        }
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in allowed:
            return JSONResponse({"detail": "不接受来自该网页的请求"}, status_code=403)
        if request.method == "POST":
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "无效的请求长度"}, status_code=400)
            if length > (settings.max_upload_mb + 10) * 1024 * 1024:
                return JSONResponse({"detail": "文件超过上传限制"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse({"detail": "任务数据库暂不可用，请检查服务后重试。"}, status_code=503)

    @app.get("/api/v1/health", response_model=Health, operation_id="health")
    def health(db: DB):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/api/v1/capabilities", response_model=Capabilities, operation_id="capabilities")
    def get_capabilities():
        return capabilities()

    @app.get("/api/v1/jobs", response_model=JobList, operation_id="list_jobs")
    def list_jobs(db: DB, limit: int = 100):
        rows = db.scalars(
            select(Job).order_by(Job.created_at.desc()).limit(max(1, min(limit, 200)))
        )
        return {"items": list(rows)}

    @app.post("/api/v1/jobs", response_model=JobView, status_code=202, operation_id="create_job")
    def submit(payload: JobCreate, db: DB, idempotency_key: IDKey = None):
        key = idempotency_key or str(uuid.uuid4())
        try:
            return create_job(db, payload, key)
        except IntegrityError:
            db.rollback()
            job = db.scalar(select(Job).where(Job.request_key == key))
            if job:
                return job
            raise

    @app.post(
        "/api/v1/uploads", response_model=JobView, status_code=202, operation_id="upload_video"
    )
    def upload(
        db: DB,
        video: Annotated[UploadFile, File()],
        subtitles: Annotated[UploadFile | None, File()] = None,
        mode: Annotated[Literal["extractive", "llm", "vision"], Form()] = "extractive",
        asr_prompt: Annotated[str, Form(max_length=500)] = "",
        idempotency_key: IDKey = None,
    ):
        key = idempotency_key or str(uuid.uuid4())
        existing = db.scalar(select(Job).where(Job.request_key == key))
        if existing:
            return existing
        require_mode(mode)
        suffix = Path(video.filename or "").suffix.lower()
        if suffix not in {".mp4", ".mkv", ".mov", ".webm", ".flv", ".avi"}:
            raise HTTPException(422, "请上传 MP4、MKV、MOV、WebM、FLV 或 AVI 视频")
        subtitle_suffix = Path(subtitles.filename or "").suffix.lower() if subtitles else ""
        if subtitles and subtitle_suffix not in {".srt", ".vtt", ".json"}:
            raise HTTPException(422, "字幕支持 SRT、VTT 和 B站 JSON")
        directory = settings.data_root.resolve() / "uploads" / str(uuid.uuid4())
        directory.mkdir(parents=True)

        def save(file: UploadFile, name: str, maximum: int) -> Path:
            destination = directory / name
            size = 0
            with destination.open("wb") as stream:
                while block := file.file.read(1024 * 1024):
                    size += len(block)
                    if size > maximum:
                        raise HTTPException(413, "文件超过上传限制")
                    stream.write(block)
            if not size:
                raise HTTPException(422, "上传文件为空")
            return destination

        try:
            # Preserve a useful local-video title without trusting client path components.
            stem = re.sub(r"[^\w .-]", "_", Path(video.filename or "video").stem)
            safe_name = (stem[:100].strip(" .") or "video") + suffix
            video_path = save(video, safe_name, settings.max_upload_mb * 1024 * 1024)
            options = {"video": str(video_path), "asr_prompt": asr_prompt}
            if subtitles:
                options["subtitles"] = str(
                    save(subtitles, f"captions{subtitle_suffix}", 10 * 1024 * 1024)
                )
            job = Job(
                request_key=key,
                source_url=None,
                source_name=safe_name,
                mode=mode,
                options=options,
            )
            db.add(job)
            db.flush()
            db.add(Dispatch(job_id=job.id, attempt=job.attempt))
            db.commit()
            return job
        except BaseException:
            db.rollback()
            shutil.rmtree(directory)
            raise
        finally:
            video.file.close()
            if subtitles:
                subtitles.file.close()

    @app.get("/api/v1/jobs/{job_id}", response_model=JobView, operation_id="get_job")
    def detail(job_id: str, db: DB):
        return get_job(db, job_id)

    @app.post(
        "/api/v1/jobs/{job_id}/retry",
        response_model=JobView,
        status_code=202,
        operation_id="retry_job",
    )
    def retry(job_id: str, db: DB):
        return retry_job(db, job_id)

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobView, operation_id="cancel_job")
    def cancel(job_id: str, db: DB):
        get_job(db, job_id)
        result = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.in_(["queued", "running"]),
            )
            .values(status="cancelled", error=None, updated_at=now())
        )
        if not result.rowcount:
            raise HTTPException(409, "任务已结束，无需取消")
        db.commit()
        db.expire_all()
        return get_job(db, job_id)

    @app.get("/api/v1/jobs/{job_id}/note", response_model=NoteView, operation_id="get_note")
    def note(job_id: str, db: DB):
        job = get_job(db, job_id)
        source = read_json(artifact(job, "sources.json"))
        available = False
        if job.pipeline_root:
            try:
                root = Path(job.pipeline_root)
                available = bool(asset_file(root, read_json(root / "source.json")["video_path"]))
            except (PipelineError, OSError, ValueError, KeyError):
                pass
        return {
            "job": job,
            "note": read_json(artifact(job, "note.json")),
            "transcript": read_json(artifact(job, "transcript.json")),
            "frames": [
                {"frame_id": f["frame_id"], "timestamp_ms": f["timestamp_ms"]}
                for f in source.get("frames", [])
            ],
            "video_available": available,
        }

    @app.get("/api/v1/jobs/{job_id}/frames/{frame_id}", operation_id="get_frame")
    def frame(job_id: str, frame_id: str, db: DB):
        if not re.fullmatch(r"frame_[0-9]{9,}", frame_id):
            raise HTTPException(404, "截图不存在")
        job = get_job(db, job_id)
        source = read_json(artifact(job, "sources.json"))
        if frame_id not in {f["frame_id"] for f in source.get("frames", [])}:
            raise HTTPException(404, "截图不属于这份笔记")
        return FileResponse(artifact(job, f"assets/{frame_id}.jpg"), media_type="image/jpeg")

    @app.get("/api/v1/jobs/{job_id}/video", operation_id="get_video")
    def video(job_id: str, db: DB):
        job = get_job(db, job_id)
        if job.status != "completed" or not job.pipeline_root:
            raise HTTPException(404, "本地视频不可用")
        root = Path(job.pipeline_root).resolve()
        if not root.is_relative_to(settings.jobs_root):
            raise HTTPException(404, "视频资源不可用")
        try:
            path = asset_file(root, read_json(root / "source.json")["video_path"])
        except (PipelineError, ValueError, OSError, KeyError) as exc:
            raise HTTPException(404, "本地视频不可用") from exc
        return FileResponse(path, media_type="video/mp4" if path.suffix == ".mp4" else None)

    @app.get("/api/v1/jobs/{job_id}/download/{kind}", operation_id="download_note")
    def download(job_id: str, kind: Literal["zip", "md", "html"], db: DB):
        job = get_job(db, job_id)
        return FileResponse(artifact(job, f"note.{kind}"), filename=f"KnowDelta-note.{kind}")

    return app


app = make_app()


def main():
    import uvicorn

    settings = get_settings()
    uvicorn.run("knowdelta.web.app:app", host=settings.api_host, port=settings.api_port)
