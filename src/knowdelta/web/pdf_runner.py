"""PDF renderer subprocess: bounded by the supervising Celery task."""

import sys
from pathlib import Path

from knowdelta.pdf_exporter import render_pdf
from knowdelta.storage import PipelineError, write_json


def main():
    source, target, content_version, result = sys.argv[1:]
    try:
        render_pdf(Path(source), Path(target), content_version)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, PipelineError)
            else "PDF 排版失败，请检查字体和渲染依赖后重试"
        )
        write_json(Path(result), {"error": message})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
