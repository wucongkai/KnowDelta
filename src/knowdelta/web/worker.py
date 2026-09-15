import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv
from sqlalchemy import select, update

from knowdelta.storage import PipelineError, read_json, write_json

from .config import get_settings
from .db import get_session_factory
from .services import complete_values
from .tables import Dispatch, Job, now

load_dotenv(Path.cwd() / ".env", override=False)
celery_app = Celery("knowdelta", broker=get_settings().redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 14400},
    task_soft_time_limit=14000,
    task_time_limit=14100,
)


def dispatch_pending():
    """Safe to run repeatedly: duplicate broker deliveries cannot claim a running job."""
    factory = get_session_factory()
    with factory() as db:
        rows = db.scalars(select(Dispatch).where(Dispatch.sent_at.is_(None)).limit(30)).all()
        for row in rows:
            process_job.apply_async(args=[row.job_id, row.attempt], retry=False)
            row.sent_at = now()
            db.commit()


def dispatch_loop(stop: threading.Event):
    while not stop.is_set():
        try:
            dispatch_pending()
            recover_stale()
        except Exception:
            # Unsent outbox records remain in the database for a later attempt.
            pass
        stop.wait(3)


def recover_stale():
    from datetime import timedelta

    with get_session_factory()() as db:
        db.execute(
            update(Job)
            .where(
                Job.status == "running",
                Job.updated_at < now() - timedelta(minutes=2),
            )
            .values(
                status="failed",
                error="处理进程中断，已保存的阶段可在重试时复用。",
                updated_at=now(),
            )
        )
        db.commit()


def stop_process(process: subprocess.Popen):
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)


@celery_app.task(name="knowdelta.process_job")
def process_job(job_id: str, attempt: int):
    factory = get_session_factory()
    with factory() as db:
        claimed = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "queued",
                Job.attempt == attempt,
            )
            .values(status="running", stage="acquire", progress=5, updated_at=now())
        )
        db.commit()
        if not claimed.rowcount:
            return
        job = db.get(Job, job_id)
        payload = {
            **job.options,
            "url": job.source_url,
            "extractive": job.mode == "extractive",
            "vision": job.mode == "vision",
            "output": str(get_settings().jobs_root),
        }
    run_dir = get_settings().data_root.resolve() / "runs" / job_id / str(attempt)
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "request.json"
    progress_path = run_dir / "progress.json"
    result_path = run_dir / "result.json"
    write_json(request_path, payload)
    process = None
    try:
        # A session isolates the entire subprocess tree for cancellation.
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "knowdelta.web.runner",
                    str(request_path),
                    str(progress_path),
                    str(result_path),
                ],
                stdout=log,
                stderr=log,
                start_new_session=os.name == "posix",
            )
            started = time.monotonic()
            while process.poll() is None:
                if time.monotonic() - started > 13900:
                    raise PipelineError("任务超过最长处理时间，请缩短视频后重试")
                with factory() as db:
                    job = db.get(Job, job_id)
                    if job.status != "running" or job.attempt != attempt:
                        stop_process(process)
                        return
                    progress = read_json(progress_path) if progress_path.exists() else {}
                    job.stage = progress.get("stage", job.stage)
                    job.progress = min(95, int(progress.get("progress", job.progress)))
                    job.updated_at = now()
                    db.commit()
                time.sleep(1)
            result = read_json(result_path) if result_path.exists() else {}
            if process.returncode or "output" not in result:
                raise PipelineError(result.get("error", "处理进程异常退出，请重试。"))
            values = complete_values(Path(result["output"]))
            with factory() as db:
                db.execute(
                    update(Job)
                    .where(
                        Job.id == job_id,
                        Job.status == "running",
                        Job.attempt == attempt,
                    )
                    .values(**values)
                )
                db.commit()
    except BaseException as exc:
        if process:
            stop_process(process)
        message = (
            str(exc) if isinstance(exc, PipelineError) else "处理失败，已完成的阶段保留，请重试。"
        )
        with factory() as db:
            db.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.status == "running",
                    Job.attempt == attempt,
                )
                .values(status="failed", error=message[:1000], updated_at=now())
            )
            db.commit()
        if not isinstance(exc, Exception):
            raise
