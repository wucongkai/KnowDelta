"""One isolated pipeline invocation. No model secrets are written into job requests."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from knowdelta.pipeline import Options, run
from knowdelta.storage import PipelineError, read_json, write_json


def main():
    request_path, progress_path, result_path = map(Path, sys.argv[1:])
    load_dotenv(Path.cwd() / ".env", override=False)
    os.environ["KNOWDELTA_PROGRESS_FILE"] = str(progress_path)
    payload = read_json(request_path)
    for field in ("output", "video", "subtitles"):
        if payload.get(field):
            payload[field] = Path(payload[field])
    os.environ.setdefault("HF_HOME", str(payload["output"] / "models"))
    try:
        directory = run(Options(**payload))
        write_json(result_path, {"output": str(directory)})
    except Exception as exc:
        message = str(exc) if isinstance(exc, PipelineError) else "视频处理失败，请检查素材后重试。"
        write_json(result_path, {"error": message})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
