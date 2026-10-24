"""PDF lifecycle. Video job state is never changed by an export."""

import os
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from knowdelta.pdf_exporter import content_version, renderer_version
from knowdelta.storage import PipelineError, read_json

from .config import get_settings
from .db import get_session_factory
from .services import artifact_root, get_job
from .tables import PdfDispatch, PdfExport, now


def output_path(export: PdfExport) -> Path:
    return get_settings().data_root.resolve() / "pdf" / export.id / str(export.attempt) / "note.pdf"


def get_export(db: Session, export_id: str) -> PdfExport:
    export = db.get(PdfExport, export_id)
    if export is None:
        raise HTTPException(404, "PDF 导出任务不存在")
    # All access follows the source job's existing artifact boundary.
    artifact_root(get_job(db, export.job_id))
    return export


def export_identity(db: Session, job_id: str):
    directory = artifact_root(get_job(db, job_id))
    try:
        content, renderer = content_version(directory), renderer_version()
    except (PipelineError, ValueError, KeyError, OSError) as exc:
        raise HTTPException(409, "笔记资源或 PDF 字体不完整，请检查素材后重试") from exc
    return directory, content, renderer


def current_export(db: Session, job_id: str) -> PdfExport | None:
    _, content, renderer = export_identity(db, job_id)
    export = db.scalar(
        select(PdfExport).where(
            PdfExport.job_id == job_id,
            PdfExport.content_version == content,
            PdfExport.renderer_version == renderer,
        )
    )
    if export and export.status == "completed" and not output_path(export).is_file():
        return None
    return export


def request_export(db: Session, job_id: str) -> PdfExport:
    directory, content, renderer = export_identity(db, job_id)
    query = select(PdfExport).where(
        PdfExport.job_id == job_id,
        PdfExport.content_version == content,
        PdfExport.renderer_version == renderer,
    )
    export = db.scalar(query)
    if not export:
        export = PdfExport(
            job_id=job_id,
            content_version=content,
            renderer_version=renderer,
            source_path=str(directory),
        )
        try:
            db.add(export)
            db.flush()
            db.add(PdfDispatch(export_id=export.id, attempt=export.attempt))
            db.commit()
            return export
        except IntegrityError:
            db.rollback()
            export = db.scalar(query)
            if export is None:
                raise
    if export.status == "failed" or (
        export.status == "completed" and not output_path(export).is_file()
    ):
        changed = db.execute(
            update(PdfExport)
            .where(
                PdfExport.id == export.id,
                PdfExport.attempt == export.attempt,
                PdfExport.status == export.status,
            )
            .values(status="queued", attempt=PdfExport.attempt + 1, error=None, updated_at=now())
        )
        db.refresh(export)
        if changed.rowcount:
            db.add(PdfDispatch(export_id=export.id, attempt=export.attempt))
        db.commit()
    return export


def dispatch_pdf_pending():
    from .worker import process_pdf_export

    with get_session_factory()() as db:
        # Heartbeats are refreshed by the supervisor, including while native rendering blocks.
        db.execute(
            update(PdfExport)
            .where(
                PdfExport.status == "running",
                PdfExport.updated_at < now() - timedelta(minutes=2),
            )
            .values(status="failed", error="PDF 处理进程中断，请重新生成", updated_at=now())
        )
        db.commit()
        rows = db.scalars(select(PdfDispatch).where(PdfDispatch.sent_at.is_(None)).limit(30)).all()
        for row in rows:
            process_pdf_export.apply_async(
                args=[row.export_id, row.attempt], queue="pdf", retry=False
            )
            row.sent_at = now()
            db.commit()


def execute_export(export_id: str, attempt: int):
    from .worker import stop_process

    factory = get_session_factory()
    with factory() as db:
        claimed = db.execute(
            update(PdfExport)
            .where(
                PdfExport.id == export_id,
                PdfExport.attempt == attempt,
                PdfExport.status == "queued",
            )
            .values(status="running", error=None, updated_at=now())
        )
        db.commit()
        if not claimed.rowcount:
            return
        export = db.get(PdfExport, export_id)
        source, target, expected = (
            Path(export.source_path),
            output_path(export),
            export.content_version,
        )
    process = None
    try:
        if export.renderer_version != renderer_version():
            raise PipelineError("PDF 排版版本已更新，请重新发起导出")
        with factory() as db:
            if source.resolve() != artifact_root(get_job(db, export.job_id)):
                raise PipelineError("笔记版本已变化，请重新导出")
        target.parent.mkdir(parents=True, exist_ok=True)
        result_path = target.parent / "result.json"
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "knowdelta.web.pdf_runner",
                    str(source),
                    str(target),
                    expected,
                    str(result_path),
                ],
                stdout=log,
                stderr=log,
                start_new_session=os.name == "posix",
            )
            started = time.monotonic()
            while process.poll() is None:
                if time.monotonic() - started > 180:
                    raise PipelineError("PDF 生成超过 3 分钟，请重试或检查素材大小")
                with factory() as db:
                    alive = db.execute(
                        update(PdfExport)
                        .where(
                            PdfExport.id == export_id,
                            PdfExport.attempt == attempt,
                            PdfExport.status == "running",
                        )
                        .values(updated_at=now())
                    )
                    db.commit()
                    if not alive.rowcount:
                        stop_process(process)
                        return
                time.sleep(1)
        if process.returncode or not target.is_file():
            result = read_json(result_path) if result_path.exists() else {}
            raise PipelineError(result.get("error", "PDF 渲染进程异常退出，请重试"))
        with factory() as db:
            db.execute(
                update(PdfExport)
                .where(
                    PdfExport.id == export_id,
                    PdfExport.attempt == attempt,
                    PdfExport.status == "running",
                )
                .values(status="completed", error=None, updated_at=now())
            )
            db.commit()
    except BaseException as exc:
        if process:
            stop_process(process)
        message = str(exc) if isinstance(exc, PipelineError) else "PDF 导出失败，请稍后重试"
        with factory() as db:
            db.execute(
                update(PdfExport)
                .where(
                    PdfExport.id == export_id,
                    PdfExport.attempt == attempt,
                    PdfExport.status == "running",
                )
                .values(status="failed", error=message[:500], updated_at=now())
            )
            db.commit()
        if not isinstance(exc, Exception):
            raise
    finally:
        target.with_suffix(".partial.pdf").unlink(missing_ok=True)
