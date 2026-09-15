import html
import importlib.util
import json
import re
import sys
from pathlib import Path

import pysubs2

from .media import extract_audio, run_command
from .models import Media, Segment, Transcript
from .storage import PipelineError, asset_file, read_json


def read_subtitles(path: Path) -> list[Segment]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = data["body"]
        items = [
            (round(float(r["from"]) * 1000), round(float(r["to"]) * 1000), str(r["content"]))
            for r in rows
        ]
    else:
        subs = pysubs2.load(str(path), encoding="utf-8-sig")
        items = [(r.start, r.end, r.plaintext) for r in subs if not r.is_comment]
    segments = []
    for start, end, text in sorted(items):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", text))).strip()
        if not text:
            continue
        if start < 0 or end <= start:
            raise ValueError("字幕时间范围无效")
        if segments and (start, end, text) == (
            segments[-1].start_ms,
            segments[-1].end_ms,
            segments[-1].text,
        ):
            continue
        segments.append(
            Segment(
                segment_id=f"seg_{len(segments) + 1:05d}",
                start_ms=start,
                end_ms=end,
                text=text,
                source="subtitle",
            )
        )
    return segments


def quality_issues(segments: list[Segment], duration: int) -> list[str]:
    if not segments:
        return ["字幕内容为空"]
    if any(s.end_ms > duration + 1000 or s.start_ms >= duration for s in segments):
        return ["字幕时间超出视频范围"]
    covered, cursor, largest_gap = 0, 0, 0
    for segment in segments:
        largest_gap = max(largest_gap, segment.start_ms - cursor)
        covered += max(0, min(duration, segment.end_ms) - max(cursor, segment.start_ms))
        cursor = max(cursor, segment.end_ms)
    largest_gap = max(largest_gap, duration - cursor)
    problems = []
    if covered / duration < 0.2:
        problems.append("字幕时间覆盖不足 20%")
    if largest_gap > max(90000, duration * 0.25):
        problems.append("字幕存在较长空缺")
    text = "".join(s.text for s in segments)
    if text.count("\ufffd") / max(1, len(text)) > 0.01:
        problems.append("字幕存在乱码")
    if len(segments) >= 10 and len({s.text for s in segments}) / len(segments) < 0.2:
        problems.append("字幕异常重复")
    return problems


def transcribe(video: Path, root: Path, language: str, model: str, prompt: str = "") -> Transcript:
    if importlib.util.find_spec("faster_whisper") is None:
        raise PipelineError(
            "没有可用字幕，且未安装转写依赖。运行 uv sync --extra asr，"
            "或通过 --subtitles 提供 SRT/VTT/B站 JSON 字幕。"
        )
    audio = root / "media" / "audio.wav"
    extract_audio(video, audio)
    print(f"[转写] CPU / {model}；首次使用需下载模型", flush=True)
    result = root / "media" / "asr_result.json"
    result.unlink(missing_ok=True)
    try:
        # Isolate PyAV from OpenCV's FFmpeg dylibs on macOS, and release model memory on exit.
        run_command(
            [
                sys.executable,
                "-m",
                "knowdelta.asr_worker",
                str(audio),
                str(result),
                language,
                model,
                prompt,
            ],
            timeout=10800,
        )
        return Transcript.model_validate(read_json(result))
    except (PipelineError, ValueError, OSError) as exc:
        raise PipelineError("语音识别失败，请检查模型下载网络、内存或音轨是否有效") from exc


def normalize_transcript(
    media: Media,
    root: Path,
    language: str,
    asr_model: str,
    subtitle_override: Path | None = None,
    force_asr: bool = False,
    asr_prompt: str = "",
) -> Transcript:
    paths = (
        [subtitle_override]
        if subtitle_override
        else [asset_file(root, path) for path in media.subtitle_paths]
    )
    paths.sort(key=lambda path: ("ai-" in path.name, path.name))
    warnings = []
    if not force_asr:
        for path in paths:
            try:
                segments = read_subtitles(path)
                issues = quality_issues(segments, media.duration_ms)
            except (ValueError, KeyError, TypeError, OSError, pysubs2.exceptions.Pysubs2Error):
                issues = ["字幕格式无法解析"]
            if issues:
                warnings.extend(issues)
                continue
            for segment in segments:
                segment.end_ms = min(segment.end_ms, media.duration_ms)
            return Transcript(
                segments=segments, language=language, origin="subtitle", warnings=warnings
            )
    prompt = f"{media.title}。{asr_prompt}"[:1000]
    if language == "zh":
        prompt = "以下是简体中文的视频转写。" + prompt
    result = transcribe(asset_file(root, media.video_path), root, language, asr_model, prompt)
    result.warnings = warnings + ["文字来自自动语音识别，专业名词需结合原视频核对。"]
    # ASR may slightly overshoot the media endpoint; discard invalid tail segments.
    result.segments = [s for s in result.segments if s.start_ms < media.duration_ms]
    for segment in result.segments:
        segment.end_ms = min(segment.end_ms, media.duration_ms)
    if not result.segments:
        raise PipelineError("语音识别没有返回有效时间范围的文字")
    return result
