FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.10.9
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY backend ./backend
RUN --mount=type=cache,id=knowdelta-uv,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra web --extra asr \
    && .venv/bin/python -c "import cv2, faster_whisper; from knowdelta.media import ffmpeg_binary; print(ffmpeg_binary())" \
    && useradd --create-home --uid 10001 knowdelta \
    && mkdir /app/data && chown knowdelta:knowdelta /app/data
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 KNOWDELTA_DATA_ROOT=/app/data
USER knowdelta
EXPOSE 8000
CMD ["knowdelta-api"]
