import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from .media import duration_ms, ffmpeg_binary, run_command
from .models import Media
from .storage import PipelineError, file_hash

ALLOWED_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}
VIDEO_PATH = re.compile(r"^/video/(BV[A-Za-z0-9]{10}|av[0-9]+)/?$")


def validate_host(url: str):
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"https", "http"}
            and parsed.hostname in ALLOWED_HOSTS
            and parsed.port in {None, 80, 443}
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        valid = False
    if not valid:
        raise PipelineError("仅支持 bilibili.com 视频地址和 b23.tv 短链接")
    return parsed


def normalize_url(url: str) -> tuple[str, int]:
    url = url.strip()
    for _ in range(6):
        parsed = validate_host(url)
        if parsed.hostname != "b23.tv":
            match = VIDEO_PATH.fullmatch(parsed.path)
            if not match:
                raise PipelineError("请提供 /video/BV… 或 /video/av… 格式的视频链接")
            try:
                parts = parse_qs(parsed.query).get("p", ["1"])
                part = int(parts[0])
                if len(parts) != 1 or not 1 <= part <= 10000:
                    raise ValueError
            except ValueError as exc:
                raise PipelineError("分 P 参数 p 必须是正整数") from exc
            return f"https://www.bilibili.com/video/{match[1]}/?p={part}", part
        # Inspect every redirect before following it; never follow to arbitrary hosts.
        try:
            with httpx.Client(follow_redirects=False, timeout=20) as client:
                response = client.get(url.replace("http://", "https://", 1))
            if response.status_code not in {301, 302, 303, 307, 308}:
                raise PipelineError("B 站短链接未返回可用的视频跳转地址")
            url = urljoin(url, response.headers["location"])
        except (httpx.HTTPError, KeyError) as exc:
            raise PipelineError("无法解析 B 站短链接，请检查网络或粘贴完整视频地址") from exc
    raise PipelineError("短链接跳转次数过多，请粘贴完整视频地址")


def check_limits(path: Path, duration: int, max_duration: int, max_bytes: int):
    if duration > max_duration * 1000:
        raise PipelineError("视频超过 --max-duration 限制（单位：秒）")
    if path.stat().st_size > max_bytes:
        raise PipelineError("视频超过 --max-size-mb 限制")


def acquire_local(
    video: Path, subtitles: Path | None, root: Path, max_duration: int, max_bytes: int
) -> Media:
    length = duration_ms(video)
    check_limits(video, length, max_duration, max_bytes)
    target = root / "media" / f"video{video.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video, target)
    subtitle_paths = []
    if subtitles:
        subtitle = target.parent / f"captions{subtitles.suffix.lower()}"
        shutil.copy2(subtitles, subtitle)
        subtitle_paths.append(str(subtitle.relative_to(root)))
    return Media(
        source_id=file_hash(video),
        title=video.stem,
        duration_ms=length,
        video_path=str(target.relative_to(root)),
        subtitle_paths=subtitle_paths,
    )


def acquire_bilibili(
    url: str,
    part: int,
    root: Path,
    cookies: Path | None,
    language: str,
    max_duration: int,
    max_bytes: int,
) -> Media:
    directory = root / "media"
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "--socket-timeout",
        "20",
        "--retries",
        "2",
        "--extractor-retries",
        "2",
        "--fragment-retries",
        "2",
        "--no-cache-dir",
    ]
    if cookies:
        command += ["--cookies", str(cookies)]
    try:
        raw = run_command(command + ["--dump-single-json", "--skip-download", url], timeout=180)
        info = json.loads(raw)
    except (PipelineError, ValueError) as exc:
        raise PipelineError(
            "B 站视频信息获取失败。请确认视频可访问；如需登录，使用 --cookies 提供"
            " Netscape 格式 Cookie 文件；网络或平台限制可稍后重试，或改用 --video。"
        ) from exc
    if info.get("_type") in {"playlist", "multi_video"} or not info.get("id"):
        raise PipelineError("平台返回了多个视频，请用明确的分 P 地址；本版一次处理一 P")
    if float(info.get("duration") or 0) > max_duration:
        raise PipelineError("视频超过 --max-duration 限制（单位：秒）")
    print(f"[来源] B 站 P{part}，时长约 {float(info.get('duration') or 0):.0f} 秒", flush=True)

    warnings = []
    # Subtitle download is independent: unavailable captions must not block ASR fallback.
    subtitle_pattern = rf"(?:ai-)?{re.escape(language)}(?:[-_].*)?"
    try:
        run_command(
            command
            + [
                "--skip-download",
                "--write-subs",
                "--sub-langs",
                subtitle_pattern,
                "--sub-format",
                "srt/vtt/best",
                "-o",
                str(directory / "captions.%(ext)s"),
                url,
            ],
            timeout=180,
        )
    except PipelineError:
        warnings.append("平台字幕获取失败，将检查现有字幕或尝试语音识别。")

    # yt-dlp expects conventional executable names, including when using bundled FFmpeg.
    binary_dir = root / "tools"
    binary_dir.mkdir(exist_ok=True)
    binary_link = binary_dir / "ffmpeg"
    if not binary_link.exists():
        binary_link.symlink_to(ffmpeg_binary())
    try:
        run_command(
            command
            + [
                "--ffmpeg-location",
                str(binary_dir),
                "--max-filesize",
                str(max_bytes),
                "-f",
                "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                str(directory / "video.%(ext)s"),
                url,
            ]
        )
    except PipelineError as exc:
        raise PipelineError(
            "B 站媒体下载失败或超时。请检查网络、访问权限与大小限制；"
            "需要登录时配置 --cookies，或改用本地视频。"
        ) from exc
    videos = [
        path
        for path in directory.glob("video.*")
        if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".flv", ".mov"}
    ]
    if len(videos) != 1:
        raise PipelineError("未获得单个完整视频，可能超过下载大小限制或合并失败")
    video = videos[0]
    length = duration_ms(video)
    check_limits(video, length, max_duration, max_bytes)
    declared = float(info.get("duration") or 0) * 1000
    if declared and length < declared * 0.9:
        raise PipelineError("下载内容明显短于视频声明时长，可能只获得试看片段")
    subtitle_paths = sorted(
        str(path.relative_to(root))
        for path in directory.glob("captions.*")
        if path.suffix.lower() in {".srt", ".vtt", ".json"}
    )
    return Media(
        source_id=str(info["id"]),
        source_url=url,
        part=part,
        title=str(info.get("title") or info["id"]),
        author=str(info.get("uploader") or ""),
        duration_ms=length,
        video_path=str(video.relative_to(root)),
        subtitle_paths=subtitle_paths,
        warnings=warnings,
    )
