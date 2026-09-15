import importlib.util
import os
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from knowdelta.bilibili_source import normalize_url
from knowdelta.models import Note
from knowdelta.storage import PipelineError, asset_file, read_json

from .config import get_settings
from .schemas import Capabilities, JobCreate
from .tables import Dispatch, Job, now


def capabilities() -> Capabilities:
    ready = bool(os.getenv("KNOWDELTA_LLM_BASE_URL") and os.getenv("KNOWDELTA_LLM_MODEL"))
    return Capabilities(
        text_model_ready=ready,
        vision_model_ready=ready and bool(os.getenv("KNOWDELTA_VISION_MODEL")),
        text_model=os.getenv("KNOWDELTA_LLM_MODEL") or None,
        vision_model=os.getenv("KNOWDELTA_VISION_MODEL") or None,
        asr_available=importlib.util.find_spec("faster_whisper") is not None,
        max_upload_mb=get_settings().max_upload_mb,
    )


def require_mode(mode: str):
    config = capabilities()
    if mode == "llm" and not config.text_model_ready:
        raise HTTPException(409, "尚未配置文字模型，请先使用原文整理或配置后端模型服务。")
    if mode == "vision" and not config.vision_model_ready:
        raise HTTPException(409, "尚未配置视觉模型，请设置后端 KNOWDELTA_VISION_MODEL。")


def get_job(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job


def create_job(db: Session, payload: JobCreate, key: str) -> Job:
    existing = db.scalar(select(Job).where(Job.request_key == key))
    if existing:
        return existing
    require_mode(payload.mode)
    try:
        url, _ = normalize_url(payload.url)
    except PipelineError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = Job(
        request_key=key,
        source_url=url,
        mode=payload.mode,
        source_name="正在整理视频…",
        options=payload.model_dump(exclude={"url", "mode"}),
    )
    db.add(job)
    db.flush()
    db.add(Dispatch(job_id=job.id, attempt=job.attempt))
    db.commit()
    return job


def retry_job(db: Session, job_id: str) -> Job:
    job = get_job(db, job_id)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "只有失败或已取消的任务可以重试")
    require_mode(job.mode)
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status.in_(["failed", "cancelled"]),
            Job.attempt == job.attempt,
        )
        .values(
            status="queued",
            stage="queued",
            progress=0,
            error=None,
            attempt=Job.attempt + 1,
            updated_at=now(),
        )
    )
    if not result.rowcount:
        raise HTTPException(409, "任务状态已变化，请刷新")
    db.refresh(job)
    db.add(Dispatch(job_id=job.id, attempt=job.attempt))
    db.commit()
    return job


def artifact_root(job: Job) -> Path:
    if job.status != "completed" or not job.artifact_path:
        raise HTTPException(409, "笔记还未完成")
    path = Path(job.artifact_path).resolve()
    if not path.is_relative_to(get_settings().jobs_root):
        raise HTTPException(404, "笔记资源不可用")
    if not path.is_dir():
        raise HTTPException(404, "笔记文件不存在")
    return path


def artifact(job: Job, name: str) -> Path:
    try:
        return asset_file(artifact_root(job), name)
    except PipelineError as exc:
        raise HTTPException(404, "笔记资源不存在") from exc


def complete_values(directory: Path) -> dict:
    note = Note.model_validate(read_json(directory / "note.json"))
    source = read_json(directory / "sources.json")
    frames = source.get("frames", [])
    return {
        "status": "completed",
        "stage": "export",
        "progress": 100,
        "artifact_path": str(directory.resolve()),
        "pipeline_root": str(directory.parent.parent.resolve()),
        "source_name": note.title[:500],
        "source_url": source.get("source_url"),
        "author": source.get("author", "")[:500],
        "duration_ms": source["duration_ms"],
        "section_count": len(note.sections),
        "image_count": len(frames),
        "cover_frame_id": frames[0]["frame_id"] if frames else None,
        "updated_at": now(),
        "error": None,
    }
