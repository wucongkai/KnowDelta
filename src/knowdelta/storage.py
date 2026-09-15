import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import PIPELINE_VERSION


class PipelineError(Exception):
    """A user-facing error without credential-bearing provider output."""


def atomic_write(path: Path, data: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: Any):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()[:20]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or Path(relative).is_absolute():
        raise PipelineError("资源路径超出任务目录")
    if not path.is_file():
        raise PipelineError("引用的资源文件不存在")
    return path


class Cache:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def run(self, stage: str, inputs: Any, compute, valid=None):
        report_progress(stage)
        key = fingerprint({"version": PIPELINE_VERSION, "inputs": inputs})
        path = self.root / "cache" / stage / f"{key}.json"
        if path.exists():
            try:
                value = read_json(path)
                if valid is None or valid(value):
                    print(f"[缓存] {stage}", flush=True)
                    return value
            except (ValueError, OSError, PipelineError, KeyError, TypeError):
                pass
        print(f"[处理] {stage}", flush=True)
        write_json(self.root / "status.json", {"stage": stage, "status": "running"})
        try:
            value = compute()
            write_json(path, value)
            return value
        except Exception:
            write_json(self.root / "status.json", {"stage": stage, "status": "failed"})
            raise


def report_progress(stage: str):
    path = os.getenv("KNOWDELTA_PROGRESS_FILE")
    if path:
        progress = {
            "acquire": 10,
            "transcript": 30,
            "frames": 55,
            "outline": 72,
            "section": 85,
            "export": 95,
        }.get(stage, 5)
        write_json(Path(path), {"stage": stage, "progress": progress})
