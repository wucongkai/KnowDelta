FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.10.9
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY backend ./backend
RUN --mount=type=cache,id=knowdelta-uv,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra web --extra asr \
    && .venv/bin/python -c "import cv2, faster_whisper; from knowdelta.media import ffmpeg_binary; print(ffmpeg_binary())" \
    && .venv/bin/python -c "import weasyprint; from knowdelta.pdf_exporter import FONT_PATH; assert FONT_PATH.is_file()" \
    && useradd --create-home --uid 10001 knowdelta \
    && mkdir /app/data && chown knowdelta:knowdelta /app/data
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 KNOWDELTA_DATA_ROOT=/app/data
USER knowdelta
EXPOSE 8000
CMD ["knowdelta-api"]
