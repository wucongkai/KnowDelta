import os
import shutil
import subprocess
from pathlib import Path

import cv2

from .storage import PipelineError


def ffmpeg_binary() -> str:
    binary = os.getenv("KNOWDELTA_FFMPEG") or shutil.which("ffmpeg")
    if not binary:
        import imageio_ffmpeg

        binary = imageio_ffmpeg.get_ffmpeg_exe()
    if not Path(binary).is_file():
        raise PipelineError("找不到 FFmpeg，请安装或设置 KNOWDELTA_FFMPEG")
    return str(Path(binary).resolve())


def run_command(args: list[str], *, timeout: int = 1800) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise PipelineError("媒体处理超时；中间结果已保留，可以重试") from exc
    except OSError as exc:
        raise PipelineError("无法启动媒体工具，请检查安装与执行权限") from exc
    if result.returncode:
        # FFmpeg/yt-dlp errors may contain signed URLs or cookie paths.
        raise PipelineError("媒体工具执行失败，请检查文件格式、网络或工具安装")
    return result.stdout


def duration_ms(path: Path) -> int:
    capture = cv2.VideoCapture(str(path))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not capture.isOpened() or fps <= 0 or frames <= 0:
            raise PipelineError("无法读取视频时长，请使用可解码的视频文件")
        return max(1, round(frames / fps * 1000))
    finally:
        capture.release()


def extract_audio(video: Path, destination: Path):
    temporary = destination.with_suffix(".partial.wav")
    run_command(
        [
            ffmpeg_binary(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(temporary),
        ]
    )
    os.replace(temporary, destination)
