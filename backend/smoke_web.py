"""Optional live smoke test. Creates two labelled test tasks in the chosen local workspace."""

import argparse
import io
import tempfile
import time
import zipfile
from pathlib import Path

import cv2
import httpx
import numpy as np


def wait_for_job(client: httpx.Client, job_id: str) -> dict:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(1)
    raise TimeoutError(f"Task {job_id} did not finish in 90 seconds; check the worker.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with (
        tempfile.TemporaryDirectory() as temporary,
        httpx.Client(base_url=args.base_url, timeout=20) as client,
    ):
        video = Path(temporary) / "fixture.mp4"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 5, (640, 360))
        assert writer.isOpened()
        for number in range(60):
            frame = np.full((360, 640, 3), 245, dtype=np.uint8)
            title = "MySQL architecture" if number < 30 else "Query execution"
            cv2.putText(frame, title, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (30, 60, 45), 2)
            for index, label in enumerate(["Client", "SQL server", "Storage engine"]):
                cv2.rectangle(
                    frame, (40, 90 + index * 80), (600, 145 + index * 80), (50, 90, 70), 2
                )
                cv2.putText(
                    frame,
                    label,
                    (60, 128 + index * 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (30, 40, 30),
                    2,
                )
            writer.write(frame)
        writer.release()
        captions = (
            "1\n00:00:00,000 --> 00:00:04,000\n客户端连接到数据库服务器。\n\n"
            "2\n00:00:04,000 --> 00:00:08,000\n服务器对查询进行解析和优化。\n\n"
            "3\n00:00:08,000 --> 00:00:12,000\n执行器调用存储引擎读取数据。\n"
        )
        response = client.post(
            "/api/v1/uploads",
            files={
                "video": ("验收示例-查询执行.mp4", video.read_bytes(), "video/mp4"),
                "subtitles": ("lesson.srt", captions.encode(), "text/plain"),
            },
            data={"mode": "extractive"},
        )
        assert response.status_code == 202, response.text
        job = wait_for_job(client, response.json()["id"])
        assert job["status"] == "completed", job
        assert job["source_name"] == "验收示例-查询执行", job
        prefix = f"/api/v1/jobs/{job['id']}"
        note = client.get(prefix + "/note").json()
        assert len(note["transcript"]["segments"]) == 3
        assert note["note"]["sections"] and note["frames"]
        frame_id = note["frames"][0]["frame_id"]
        assert client.get(prefix + "/frames/" + frame_id).headers["content-type"] == "image/jpeg"
        ranged = client.get(prefix + "/video", headers={"Range": "bytes=0-99"})
        assert ranged.status_code == 206 and len(ranged.content) == 100
        archive = client.get(prefix + "/download/zip")
        archive.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            assert bundle.testzip() is None
            assert any(name.endswith("note.md") for name in bundle.namelist())
        failed = client.post(
            "/api/v1/uploads", files={"video": ("验收示例-损坏素材.mp4", b"invalid media")}
        )
        assert failed.status_code == 202, failed.text
        failure = wait_for_job(client, failed.json()["id"])
        assert failure["status"] == "failed", failure
        retry_path = f"/api/v1/jobs/{failure['id']}"
        retried = client.post(retry_path + "/retry")
        assert retried.status_code == 202 and retried.json()["attempt"] == 2
        cancelled = client.post(retry_path + "/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        print(f"PASS upload → queue → worker → note → frame/video/ZIP: {job['id']}")
        print(f"PASS malformed media → failed → retry → cancel: {failure['id']}")


if __name__ == "__main__":
    main()
