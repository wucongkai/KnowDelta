"""Offline, versioned PDF rendering from an existing immutable note export."""

import hashlib
import html
import logging
import os
import re
import sys
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

from .models import Note, Transcript
from .renderer import timestamp
from .storage import PipelineError, asset_file, file_hash, read_json

RENDERER_VERSION = "pdf-v1"
FONT_PATH = Path(__file__).parent / "fonts" / "NotoSansCJKsc-Regular.otf"
BASE_URL = "https://pdf.knowdelta.invalid/"
CSS = """
@font-face { font-family: NoteSans; src: url('font.otf'); }
@page {
  size: A4; margin: 18mm 17mm 20mm;
  @bottom-left { content: 'KnowDelta · 知微'; color: #7b817b; font: 8pt NoteSans; }
  @bottom-right { content: counter(page) ' / ' counter(pages); color: #7b817b; font: 8pt NoteSans; }
}
body { font-family: NoteSans; font-size: 10.5pt; line-height: 1.8; color: #29352e; }
h1 { font-size: 23pt; line-height: 1.45; color: #234d3c; margin: 6mm 0; }
h2 { font-size: 15pt; line-height: 1.5; color: #234d3c; margin: 9mm 0 4mm;
     border-bottom: 1px solid #dce4db; padding-bottom: 3mm; break-after: avoid; }
p { white-space: pre-wrap; overflow-wrap: anywhere; orphans: 3; widows: 3; margin: 3mm 0; }
a { color: #356e55; text-decoration: none; overflow-wrap: anywhere; }
.meta, .source, figcaption { font-size: 8.5pt; color: #66786a; }
.source { margin-top: 1mm; break-before: avoid; }
.notice { background: #f0f4ec; padding: 4mm; margin: 6mm 0; font-size: 9pt; }
.notice p { margin: 1mm 0; }
nav { font-size: 9.5pt; margin: 6mm 0; }
nav ol { padding-left: 6mm; }
nav li { margin: 1mm 0; }
figure { margin: 6mm 0; break-inside: avoid; }
img { display: block; margin: 0 auto; max-width: 176mm; }
figcaption { margin-top: 2mm; line-height: 1.6; overflow-wrap: anywhere; }
.kicker { font-size: 9pt; letter-spacing: 1pt; color: #6e856e; }
"""


def load_inputs(directory: Path):
    note = Note.model_validate(read_json(asset_file(directory, "note.json")))
    transcript = Transcript.model_validate(read_json(asset_file(directory, "transcript.json")))
    sources = read_json(asset_file(directory, "sources.json"))
    segments = {segment.segment_id: segment for segment in transcript.segments}
    frames = {frame["frame_id"]: frame for frame in sources.get("frames", [])}
    resources = {}
    for section in note.sections:
        for paragraph in section.paragraphs:
            if not set(paragraph.source_segment_ids) <= segments.keys():
                raise PipelineError("笔记缺少来源字幕，无法导出 PDF")
        for image in section.images:
            if image.frame_id not in frames or not re.fullmatch(r"frame_[0-9]{9,}", image.frame_id):
                raise PipelineError("笔记缺少截图索引，无法导出 PDF")
            name = f"assets/{image.frame_id}.jpg"
            resources[name] = asset_file(directory, name)
    return note, transcript, sources, resources


def content_version(directory: Path) -> str:
    _, _, _, resources = load_inputs(directory)
    digest = hashlib.sha256()
    for name in ["note.json", "transcript.json", "sources.json", *sorted(resources)]:
        digest.update(name.encode())
        digest.update(file_hash(asset_file(directory, name)).encode())
    return digest.hexdigest()


def renderer_version() -> str:
    style = hashlib.sha256(CSS.encode()).hexdigest()[:12]
    return f"{RENDERER_VERSION}-weasy{version('weasyprint')}-{style}-{file_hash(FONT_PATH)[:12]}"


def configure_native_libraries():
    """Help macOS locate Homebrew libraries without changing the system configuration."""
    if sys.platform == "darwin" and "DYLD_FALLBACK_LIBRARY_PATH" not in os.environ:
        directories = [
            directory
            for directory in ("/opt/homebrew/lib", "/usr/local/lib")
            if (Path(directory) / "libpango-1.0.dylib").is_file()
        ]
        if directories:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(directories)


def safe_source(url: str | None, start_ms: int | None = None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.bilibili.com" or parsed.username:
        raise PipelineError("笔记中的视频来源地址无效")
    if start_ms is not None:
        url += ("&" if parsed.query else "?") + f"t={start_ms // 1000}"
    return html.escape(url, quote=True)


def build_document(directory: Path) -> tuple[str, dict[str, dict]]:
    note, transcript, sources, files = load_inputs(directory)
    segments = {segment.segment_id: segment for segment in transcript.segments}
    frames = {frame["frame_id"]: frame for frame in sources.get("frames", [])}
    resources = {BASE_URL + "font.otf": {"string": FONT_PATH.read_bytes(), "mime_type": "font/otf"}}
    sizes = {}
    for name, path in files.items():
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                sizes[name] = image.size
        except (OSError, ValueError) as exc:
            raise PipelineError("截图损坏，无法完整导出 PDF") from exc
        resources[BASE_URL + name] = {"string": path.read_bytes(), "mime_type": "image/jpeg"}
    esc = html.escape
    page = [
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
        f"<title>{esc(note.title)}</title><style>{CSS}</style><body>",
        '<div class="kicker">KNOWDELTA / 视频学习笔记</div>',
        f"<h1>{esc(note.title)}</h1>",
        f'<p class="meta">{esc(str(sources.get("author") or "本地视频"))} · '
        f"{timestamp(sources['duration_ms'])}</p>",
    ]
    source = safe_source(sources.get("source_url"))
    page.append(f'<a href="{source}">查看原视频</a>' if source else "<p>来源：本地视频</p>")
    if note.warnings:
        page.append(
            '<div class="notice">' + "".join(f"<p>{esc(w)}</p>" for w in note.warnings) + "</div>"
        )
    page.append('<nav aria-label="目录"><strong>内容目录</strong><ol>')
    page.extend(
        f'<li><a href="#chapter-{i}">{esc(section.title)}</a></li>'
        for i, section in enumerate(note.sections, 1)
    )
    page.append("</ol></nav>")
    for index, section in enumerate(note.sections, 1):
        page.append(f'<section><h2 id="chapter-{index}">{index}. {esc(section.title)}</h2>')
        for paragraph in section.paragraphs:
            evidence = [segments[sid] for sid in paragraph.source_segment_ids]
            start, end = min(s.start_ms for s in evidence), max(s.end_ms for s in evidence)
            label = f"{timestamp(start)} - {timestamp(end)}"
            link = safe_source(sources.get("source_url"), start)
            citation = f'<a href="{link}">{label}</a>' if link else label
            page.extend(
                [f"<p>{esc(paragraph.text)}</p>", f'<p class="source">来源：{citation}</p>']
            )
        for image in section.images:
            name = f"assets/{image.frame_id}.jpg"
            width, height = sizes[name]
            # Reserve caption space even for maximum-length captions and very tall images.
            caption = image.caption + f"（{timestamp(frames[image.frame_id]['timestamp_ms'])}）"
            caption_lines = (len(caption) + 48) // 49
            max_height = max(70, 220 - caption_lines * 5)
            scale = min(176 / width, max_height / height)
            page.append(
                f'<figure><img src="{name}" alt="{esc(caption, quote=True)}" '
                f'style="width:{width * scale:.2f}mm;height:{height * scale:.2f}mm">'
                f"<figcaption>{esc(caption)}</figcaption></figure>"
            )
        page.append("</section>")
    page.append("</body></html>")
    return "\n".join(page), resources


def render_pdf(directory: Path, destination: Path, expected_version: str):
    # Loaded only in the isolated renderer, so API/video jobs don't load native Pango.
    configure_native_libraries()
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    if content_version(directory) != expected_version:
        raise PipelineError("笔记内容已变化，请重新发起 PDF 导出")
    document, resources = build_document(directory)
    failures = []

    class NoteResources(URLFetcher):
        def fetch(self, url, http_headers=None):
            if url not in resources:
                failures.append(url)
                raise ValueError("Resource is not part of this note")
            resource = resources[url]
            return URLFetcherResponse(
                url, resource["string"], {"Content-Type": resource["mime_type"]}
            )

    class Errors(logging.Handler):
        def emit(self, record):
            failures.append(record.getMessage())

    handler = Errors(level=logging.WARNING)
    logger = logging.getLogger("weasyprint")
    logger.addHandler(handler)
    temporary = destination.with_suffix(".partial.pdf")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        HTML(
            string=document, base_url=BASE_URL, url_fetcher=NoteResources(allowed_protocols=[])
        ).write_pdf(temporary, font_config=FontConfiguration(), pdf_tags=True)
        if failures:
            raise PipelineError("PDF 的图片或字体加载失败，请检查笔记资源后重试")
        if content_version(directory) != expected_version:
            raise PipelineError("导出期间笔记内容变化，请重试")
        os.replace(temporary, destination)
    finally:
        logger.removeHandler(handler)
        temporary.unlink(missing_ok=True)
