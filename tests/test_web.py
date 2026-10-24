from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from knowdelta.pipeline import Options, run
from knowdelta.web.app import make_app
from knowdelta.web.config import get_settings
from knowdelta.web.db import Base, get_db
from knowdelta.web.services import complete_values
from knowdelta.web.tables import Dispatch, Job


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWDELTA_DATA_ROOT", str(tmp_path))
    for key in ["KNOWDELTA_LLM_BASE_URL", "KNOWDELTA_LLM_MODEL", "KNOWDELTA_VISION_MODEL"]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = make_app(dispatch=False)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, factory, tmp_path
    engine.dispose()
    get_settings.cache_clear()


def test_job_creation_idempotency_and_state_transitions(api):
    client, factory, _ = api
    payload = {"url": "https://www.bilibili.com/video/BV1p5qhYsE4f/?p=2&tracking=foo"}
    first = client.post("/api/v1/jobs", json=payload, headers={"Idempotency-Key": "same"})
    assert first.status_code == 202
    job = first.json()
    assert job["status"] == "queued"
    assert job["source_url"].endswith("?p=2")
    assert "options" not in job and "artifact_path" not in job
    second = client.post("/api/v1/jobs", json=payload, headers={"Idempotency-Key": "same"})
    assert second.json()["id"] == job["id"]
    with factory() as db:
        assert len(list(db.scalars(select(Dispatch)))) == 1
    assert client.post(f"/api/v1/jobs/{job['id']}/retry").status_code == 409
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/v1/jobs/{job['id']}/retry").json()["attempt"] == 2
    assert client.get("/api/v1/jobs/no-such-job").status_code == 404


def test_model_configuration_and_url_boundary(api):
    client, _, _ = api
    assert (
        client.post(
            "/api/v1/jobs",
            json={
                "url": "https://www.bilibili.com/video/BV1p5qhYsE4f/",
                "mode": "llm",
            },
        ).status_code
        == 409
    )
    assert client.post("/api/v1/jobs", json={"url": "http://127.0.0.1/internal"}).status_code == 422
    assert (
        client.post(
            "/api/v1/jobs",
            json={"url": "https://b23.tv/test"},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/capabilities").json()["text_model_ready"] is False


def test_uploaded_video_only_exposes_job_id(api, local_input):
    client, factory, root = api
    video, subtitles = local_input
    result = client.post(
        "/api/v1/uploads",
        files={
            "video": ("../../outside.mp4", video.read_bytes(), "video/mp4"),
            "subtitles": ("captions.srt", subtitles.read_bytes(), "text/plain"),
        },
        data={"mode": "extractive"},
    )
    assert result.status_code == 202, result.text
    job_id = result.json()["id"]
    assert str(root) not in result.text
    with factory() as db:
        job = db.get(Job, job_id)
        assert Path(job.options["video"]).is_relative_to(root / "uploads")
        assert Path(job.options["subtitles"]).is_file()
    bad = client.post("/api/v1/uploads", files={"video": ("test.exe", b"bad")})
    assert bad.status_code == 422


def test_note_assets_download_and_video_range(api, local_input):
    client, factory, root = api
    video, subtitles = local_input
    directory = run(
        Options(video=video, subtitles=subtitles, output=root / "jobs", extractive=True)
    )
    with factory() as db:
        job = Job(
            request_key="import-test", mode="extractive", options={}, **complete_values(directory)
        )
        db.add(job)
        db.commit()
        job_id = job.id
    prefix = f"/api/v1/jobs/{job_id}"
    note = client.get(prefix + "/note")
    assert note.status_code == 200
    assert "artifact_path" not in note.text
    frame_id = note.json()["frames"][0]["frame_id"]
    assert client.get(prefix + "/frames/" + frame_id).headers["content-type"] == "image/jpeg"
    assert client.get(prefix + "/frames/frame_999999999").status_code == 404
    assert client.get(prefix + "/download/zip").content[:2] == b"PK"
    response = client.get(prefix + "/video", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100
    assert client.post(prefix + "/cancel").status_code == 409


def test_worker_duplicate_delivery_does_not_reprocess(api, monkeypatch):
    from knowdelta.web import worker
    from knowdelta.web.schemas import JobCreate
    from knowdelta.web.services import create_job

    _, factory, _ = api
    monkeypatch.setattr(worker, "get_session_factory", lambda: factory)
    with factory() as db:
        job = create_job(db, JobCreate(url="https://www.bilibili.com/video/BV1p5qhYsE4f/"), "a")
        job.status = "running"
        db.commit()
        job_id = job.id

    def unexpected(*args, **kwargs):
        pytest.fail("duplicate delivery must not start a process")

    monkeypatch.setattr(worker.subprocess, "Popen", unexpected)
    worker.process_job(job_id, 1)


def test_outbox_failure_keeps_dispatch_pending(api, monkeypatch):
    from knowdelta.web import worker
    from knowdelta.web.schemas import JobCreate
    from knowdelta.web.services import create_job

    _, factory, _ = api
    monkeypatch.setattr(worker, "get_session_factory", lambda: factory)
    with factory() as db:
        create_job(db, JobCreate(url="https://www.bilibili.com/video/BV1p5qhYsE4f/"), "b")

    def unavailable(*args, **kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(worker.process_job, "apply_async", unavailable)
    with pytest.raises(ConnectionError):
        worker.dispatch_pending()
    with factory() as db:
        assert db.scalar(select(Dispatch)).sent_at is None


def test_pdf_export_lifecycle_idempotency_retry_and_video_isolation(api, local_input, monkeypatch):
    from knowdelta.web import pdf_jobs
    from knowdelta.web.tables import PdfDispatch, PdfExport

    client, factory, root = api
    monkeypatch.setattr(pdf_jobs, "get_session_factory", lambda: factory)
    video, subtitles = local_input
    directory = run(
        Options(video=video, subtitles=subtitles, output=root / "jobs", extractive=True)
    )
    with factory() as db:
        job = Job(
            request_key="pdf-note", mode="extractive", options={}, **complete_values(directory)
        )
        db.add(job)
        db.commit()
        job_id = job.id
    url = f"/api/v1/jobs/{job_id}/exports/pdf"
    assert client.get(url).json() is None
    first = client.post(url)
    assert first.status_code == 202, first.text
    export_id = first.json()["id"]
    assert "source_path" not in first.text
    assert client.post(url).json()["id"] == export_id
    with factory() as db:
        assert len(list(db.scalars(select(PdfDispatch)))) == 1
    download = f"/api/v1/exports/{export_id}/download"
    assert client.get(download).status_code == 409
    # Real subprocess render, not a fake successful PDF.
    pdf_jobs.execute_export(export_id, 1)
    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "completed"
    response = client.get(download)
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert client.post(url).json()["attempt"] == 1
    with factory() as db:
        export = db.get(PdfExport, export_id)
        pdf_jobs.output_path(export).unlink()
    assert client.get(url).json() is None
    assert client.post(url).json()["attempt"] == 2

    # A rendering failure should affect only the export, never the video job.
    def broken(*args, **kwargs):
        raise OSError("simulated missing renderer")

    monkeypatch.setattr(pdf_jobs.subprocess, "Popen", broken)
    pdf_jobs.execute_export(export_id, 2)
    assert client.get(f"/api/v1/exports/{export_id}").json()["status"] == "failed"
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "completed"
    assert client.post(url).json()["attempt"] == 3
    assert client.get("/api/v1/exports/unknown/download").status_code == 404

    # Updated layouts never offer an older renderer's cached PDF as the current export.
    original_version = pdf_jobs.renderer_version()
    monkeypatch.setattr(pdf_jobs, "renderer_version", lambda: original_version + "-updated")
    assert client.get(url).json() is None
    replacement = client.post(url)
    assert replacement.status_code == 202 and replacement.json()["id"] != export_id


def test_pdf_dispatch_error_does_not_block_video_jobs(monkeypatch):
    import threading

    from knowdelta.web import pdf_jobs, worker

    stop = threading.Event()
    calls = []

    def failed_pdf():
        calls.append("pdf")
        raise ConnectionError("export dispatch unavailable")

    def recover():
        calls.append("recover")
        stop.set()

    monkeypatch.setattr(worker, "dispatch_pending", lambda: calls.append("video"))
    monkeypatch.setattr(pdf_jobs, "dispatch_pdf_pending", failed_pdf)
    monkeypatch.setattr(worker, "recover_stale", recover)
    worker.dispatch_loop(stop)
    assert calls == ["video", "pdf", "recover"]


def test_pdf_dispatch_failure_and_duplicate_delivery(api, local_input, monkeypatch):
    from knowdelta.web import pdf_jobs, worker
    from knowdelta.web.tables import PdfDispatch, PdfExport

    client, factory, root = api
    monkeypatch.setattr(pdf_jobs, "get_session_factory", lambda: factory)
    video, subtitles = local_input
    directory = run(
        Options(video=video, subtitles=subtitles, output=root / "jobs", extractive=True)
    )
    with factory() as db:
        job = Job(
            request_key="pdf-dispatch", mode="extractive", options={}, **complete_values(directory)
        )
        db.add(job)
        db.commit()
        job_id = job.id
    export_id = client.post(f"/api/v1/jobs/{job_id}/exports/pdf").json()["id"]

    def unavailable(*args, **kwargs):
        raise ConnectionError("broker offline")

    monkeypatch.setattr(worker.process_pdf_export, "apply_async", unavailable)
    with pytest.raises(ConnectionError):
        pdf_jobs.dispatch_pdf_pending()
    with factory() as db:
        assert db.scalar(select(PdfDispatch)).sent_at is None
        export = db.get(PdfExport, export_id)
        export.status = "running"
        db.commit()

    def unexpected(*args, **kwargs):
        pytest.fail("duplicate delivery started rendering")

    monkeypatch.setattr(pdf_jobs.subprocess, "Popen", unexpected)
    pdf_jobs.execute_export(export_id, 1)
