from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from filelock import FileLock, Timeout

from .alignment import make_chapters
from .bilibili_source import acquire_bilibili, acquire_local, normalize_url
from .frames import select_frames
from .llm import ModelClient
from .models import Frame, Media, Transcript
from .note_generator import generate_note
from .renderer import export_note
from .storage import (
    Cache,
    PipelineError,
    asset_file,
    file_hash,
    fingerprint,
    read_json,
    report_progress,
    write_json,
)
from .transcript import normalize_transcript


@dataclass
class Options:
    url: str | None = None
    video: Path | None = None
    subtitles: Path | None = None
    output: Path = Path("data/jobs")
    cookies: Path | None = None
    language: str = "zh"
    extractive: bool = False
    vision: bool = False
    force_asr: bool = False
    asr_model: str = "small"
    asr_prompt: str = ""
    chapter_seconds: int = 180
    frame_interval: float = 5
    max_frames: int = 180
    max_duration: int = 7200
    max_size_mb: int = 2048


def media_cache_valid(value: dict, root: Path) -> bool:
    media = Media.model_validate(value["media"])
    video = asset_file(root, media.video_path)
    return file_hash(video) == value["video_hash"] and all(
        asset_file(root, name) for name in media.subtitle_paths
    )


def frames_cache_valid(value: list, root: Path) -> bool:
    return all(asset_file(root, Frame.model_validate(row).asset_path) for row in value)


def run(options: Options) -> Path:
    if bool(options.url) == bool(options.video):
        raise PipelineError("必须指定一个 B 站链接或 --video 本地文件")
    for path in (options.video, options.subtitles, options.cookies):
        if path and not path.is_file():
            raise PipelineError("输入视频、字幕或 Cookie 文件不存在")
    if options.extractive and options.vision:
        raise PipelineError("--extractive 和 --vision 不能同时使用")
    client = None if options.extractive else ModelClient.from_env()
    url, part = normalize_url(options.url) if options.url else (None, 1)
    identity = {"url": url} if url else {"video_hash": file_hash(options.video)}
    root = options.output.resolve() / fingerprint(identity)
    cache = Cache(root)
    try:
        with FileLock(root / ".lock", timeout=0):
            try:
                result = run_locked(options, root, cache, client, identity, url, part)
            except BaseException:
                status = read_json(root / "status.json") if (root / "status.json").exists() else {}
                write_json(root / "status.json", {**status, "status": "failed"})
                raise
            write_json(
                root / "status.json",
                {
                    "status": "complete",
                    "stage": "export",
                    "export_path": str(result),
                },
            )
            return result
    except Timeout as exc:
        raise PipelineError("同一视频已有任务正在运行，请等待完成后再试") from exc


def run_locked(
    options: Options,
    root: Path,
    cache: Cache,
    client: ModelClient | None,
    identity: dict,
    url: str | None,
    part: int,
) -> Path:
    subtitle_hash = file_hash(options.subtitles) if options.subtitles else None
    acquire_config = {
        **identity,
        "subtitle_hash": subtitle_hash if not url else None,
        "language": options.language,
        "max_duration": options.max_duration,
        "max_size_mb": options.max_size_mb,
        "yt_dlp": version("yt-dlp"),
    }

    def acquire():
        if url:
            media = acquire_bilibili(
                url,
                part,
                root,
                options.cookies,
                options.language,
                options.max_duration,
                options.max_size_mb * 1024 * 1024,
            )
        else:
            media = acquire_local(
                options.video,
                options.subtitles,
                root,
                options.max_duration,
                options.max_size_mb * 1024 * 1024,
            )
        return {
            "media": media.model_dump(),
            "video_hash": file_hash(asset_file(root, media.video_path)),
        }

    acquired = cache.run("acquire", acquire_config, acquire, lambda v: media_cache_valid(v, root))
    media = Media.model_validate(acquired["media"])
    if options.video:
        # The bytes can share a media cache while the current upload has a new title.
        media.title = options.video.stem
    write_json(root / "source.json", media.model_dump())
    transcript_config = {
        "media_hash": acquired["video_hash"],
        "subtitle_hash": subtitle_hash,
        "captions": [file_hash(asset_file(root, name)) for name in media.subtitle_paths],
        "language": options.language,
        "asr_model": options.asr_model,
        "asr_prompt": options.asr_prompt,
        "title": media.title,
        "transcript_version": "2",
        "force_asr": options.force_asr,
    }
    transcript = Transcript.model_validate(
        cache.run(
            "transcript",
            transcript_config,
            lambda: normalize_transcript(
                media,
                root,
                options.language,
                options.asr_model,
                options.subtitles,
                options.force_asr,
                options.asr_prompt,
            ).model_dump(),
        )
    )
    write_json(root / "transcript.json", transcript.model_dump())
    frames = [
        Frame.model_validate(value)
        for value in cache.run(
            "frames",
            {
                "media_hash": acquired["video_hash"],
                "interval": options.frame_interval,
                "max_frames": options.max_frames,
                "opencv": version("opencv-python-headless"),
                "selector_version": "2",
            },
            lambda: [
                f.model_dump()
                for f in select_frames(media, root, options.frame_interval, options.max_frames)
            ],
            lambda value: frames_cache_valid(value, root),
        )
    ]
    write_json(root / "frames.json", [f.model_dump() for f in frames])
    chapters = make_chapters(transcript, client, cache, options.chapter_seconds)
    write_json(root / "chapters.json", [c.model_dump() for c in chapters])
    report_progress("section")
    note = generate_note(media, transcript, frames, chapters, client, cache, root, options.vision)
    if client:
        write_json(
            root / "last_run_usage.json",
            {
                "note": "仅包含本次进程实际调用模型的用量；命中缓存的调用不计入。",
                "calls": client.usage,
            },
        )
    write_json(root / "status.json", {"status": "running", "stage": "export"})
    report_progress("export")
    try:
        return export_note(note, media, transcript, frames, root)
    except Exception:
        write_json(root / "status.json", {"status": "failed", "stage": "export"})
        raise
