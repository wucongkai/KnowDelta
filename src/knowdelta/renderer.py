import html
import re
import zipfile
from pathlib import Path

from .models import Frame, Media, Note, Transcript
from .storage import PipelineError, asset_file, atomic_write, fingerprint, write_json


def timestamp(ms: int) -> str:
    seconds = ms // 1000
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def plain_markdown(text: str) -> str:
    # All source/model text is plain text. Only the renderer may create links/images/HTML.
    text = html.escape(text, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~\-])", r"\\\1", text).replace("\n", "  \n")


def source_link(media: Media, start_ms: int) -> str | None:
    return f"{media.source_url}&t={start_ms // 1000}" if media.source_url else None


def validate_note(
    note: Note, media: Media, transcript: Transcript, frames: list[Frame], root: Path
):
    segments = {s.segment_id: s for s in transcript.segments}
    images = {f.frame_id: f for f in frames}
    if len(segments) != len(transcript.segments) or len(images) != len(frames):
        raise PipelineError("证据 ID 重复")
    for segment in segments.values():
        if not 0 <= segment.start_ms < segment.end_ms <= media.duration_ms:
            raise PipelineError("字幕证据时间范围无效")
    for section in note.sections:
        for paragraph in section.paragraphs:
            if (
                not paragraph.source_segment_ids
                or not set(paragraph.source_segment_ids) <= segments.keys()
            ):
                raise PipelineError("笔记引用了不存在的字幕证据")
        for image in section.images:
            frame = images.get(image.frame_id)
            if frame is None or not 0 <= frame.timestamp_ms < media.duration_ms:
                raise PipelineError("笔记引用了不存在或时间无效的截图")
            asset_file(root, frame.asset_path)


STYLE = """
body{margin:0;background:#f6f7f9;color:#20252c;font:17px/1.85 system-ui,sans-serif}
main{max-width:860px;margin:32px auto;background:white;padding:40px;border-radius:16px}
h1{line-height:1.3}h2{margin-top:44px;border-top:1px solid #e5e7eb;padding-top:24px}
a{color:#2463ad}img{max-width:100%;height:auto;border-radius:8px}figure{margin:24px 0}
figcaption,.source{color:#637082;font-size:14px}.notice{padding:16px;background:#f1f5fb}
p{white-space:pre-wrap}nav ol{padding-left:24px}footer{margin-top:40px;color:#637082}
@media(max-width:600px){main{padding:20px;margin:0;border-radius:0}}
"""


def export_note(
    note: Note,
    media: Media,
    transcript: Transcript,
    frames: list[Frame],
    root: Path,
) -> Path:
    validate_note(note, media, transcript, frames, root)
    directory = root / "exports" / fingerprint(note.model_dump())
    directory.mkdir(parents=True, exist_ok=True)
    segments = {s.segment_id: s for s in transcript.segments}
    images = {f.frame_id: f for f in frames}
    md = [f"# {plain_markdown(note.title)}", ""]
    page = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
        "img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'\">",
        f"<title>{html.escape(note.title)}</title><style>{STYLE}</style></head><body><main>",
        f"<h1>{html.escape(note.title)}</h1>",
    ]
    description = (
        f"作者：{media.author or '未提供'} · P{media.part} · {timestamp(media.duration_ms)}"
    )
    md += [plain_markdown(description), ""]
    page.append(f"<p class='source'>{html.escape(description)}</p>")
    if media.source_url:
        md += [f"[原视频]({media.source_url})", ""]
        page.append(f"<a href='{html.escape(media.source_url, quote=True)}'>原视频</a>")
    else:
        md += ["来源：本地视频。视频未包含在导出包中，时间戳供本地回看定位。", ""]
        page.append(
            "<p class='source'>来源：本地视频。视频未包含在导出包中，时间戳供本地回看定位。</p>"
        )
    if note.warnings:
        md += [f"> {plain_markdown(w)}" for w in note.warnings] + [""]
        page.append(
            "<div class='notice'>" + "<br>".join(html.escape(w) for w in note.warnings) + "</div>"
        )
    page.append(
        "<nav><h2>目录</h2><ol>"
        + "".join(
            f"<li><a href='#section-{i}'>{html.escape(s.title)}</a></li>"
            for i, s in enumerate(note.sections, 1)
        )
        + "</ol></nav>"
    )
    used_frames = {}
    for index, section in enumerate(note.sections, 1):
        md += [f"## {index}. {plain_markdown(section.title)}", ""]
        page.append(f"<section id='section-{index}'><h2>{index}. {html.escape(section.title)}</h2>")
        for paragraph in section.paragraphs:
            evidence = [segments[sid] for sid in paragraph.source_segment_ids]
            start, end = min(s.start_ms for s in evidence), max(s.end_ms for s in evidence)
            label = f"{timestamp(start)}–{timestamp(end)}"
            link = source_link(media, start)
            citation_md = f"[{label}]({link})" if link else label
            citation_html = (
                f"<a href='{html.escape(link, quote=True)}'>{label}</a>" if link else label
            )
            md += [plain_markdown(paragraph.text), "", f"来源：{citation_md}", ""]
            page += [
                f"<p>{html.escape(paragraph.text)}</p>",
                f"<div class='source'>来源：{citation_html}</div>",
            ]
        for illustration in section.images:
            frame = images[illustration.frame_id]
            relative = f"assets/{frame.frame_id}.jpg"
            atomic_write(directory / relative, asset_file(root, frame.asset_path).read_bytes())
            used_frames[frame.frame_id] = {**frame.model_dump(), "asset_path": relative}
            caption = f"{illustration.caption}（{timestamp(frame.timestamp_ms)}）"
            md += [f"![{plain_markdown(caption)}]({relative})", "", plain_markdown(caption), ""]
            page.append(
                f"<figure><img loading='lazy' src='{relative}' "
                f"alt='{html.escape(caption, quote=True)}'>"
                f"<figcaption>{html.escape(caption)}</figcaption></figure>"
            )
        page.append("</section>")
    page.append(
        "<footer>由 KnowDelta 整理 · 字幕与截图来源保存在随附 JSON 文件中。"
        "</footer></main></body></html>"
    )
    atomic_write(directory / "note.md", "\n".join(md))
    atomic_write(directory / "note.html", "\n".join(page))
    write_json(directory / "note.json", note.model_dump())
    write_json(directory / "transcript.json", transcript.model_dump())
    write_json(
        directory / "sources.json",
        {
            "source_id": media.source_id,
            "source_url": media.source_url,
            "title": media.title,
            "author": media.author,
            "part": media.part,
            "duration_ms": media.duration_ms,
            "frames": list(used_frames.values()),
        },
    )
    target = directory / "note.zip"
    temporary = directory / ".note.zip.tmp"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["note.md", "note.html", "note.json", "transcript.json", "sources.json"]:
            archive.write(directory / name, name)
        for frame in used_frames.values():
            archive.write(directory / frame["asset_path"], frame["asset_path"])
    temporary.replace(target)
    return directory
