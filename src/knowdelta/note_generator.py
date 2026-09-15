from pathlib import Path

from pydantic import ValidationError

from .alignment import frames_for_chapter
from .llm import ModelClient
from .models import Chapter, Frame, Illustration, Media, Note, Paragraph, Section, Transcript
from .storage import Cache, PipelineError, asset_file, file_hash


def extractive_paragraphs(chapter: Chapter, segments: dict) -> list[Paragraph]:
    result, ids, texts, start = [], [], [], 0
    for sid in chapter.segment_ids:
        segment = segments[sid]
        if ids and (
            sum(len(text) for text in texts) + len(segment.text) > 220
            or segment.end_ms - start > 30000
        ):
            result.append(Paragraph(text=" ".join(texts), source_segment_ids=ids))
            ids, texts = [], []
        if not ids:
            start = segment.start_ms
        ids.append(sid)
        texts.append(segment.text)
    if ids:
        result.append(Paragraph(text=" ".join(texts), source_segment_ids=ids))
    return result


def validate_section(section: Section, segment_ids: set[str], frame_ids: set[str]):
    for paragraph in section.paragraphs:
        if not set(paragraph.source_segment_ids) <= segment_ids:
            raise PipelineError("正文引用了当前章节以外或不存在的字幕")
    chosen = [image.frame_id for image in section.images]
    if not set(chosen) <= frame_ids or len(chosen) != len(set(chosen)):
        raise PipelineError("配图包含不存在、不属于当前章节或重复的截图")


def generate_note(
    media: Media,
    transcript: Transcript,
    frames: list[Frame],
    chapters: list[Chapter],
    client: ModelClient | None,
    cache: Cache,
    root: Path,
    vision: bool = False,
) -> Note:
    segments = {s.segment_id: s for s in transcript.segments}
    sections = []
    for index, chapter in enumerate(chapters):
        print(f"[章节] {index + 1}/{len(chapters)}", flush=True)
        candidates = frames_for_chapter(chapter, segments, frames)
        evidence = {
            "title": chapter.title,
            "segments": [segments[sid].model_dump() for sid in chapter.segment_ids],
            "frames": [
                {"frame_id": f.frame_id, "timestamp_ms": f.timestamp_ms} for f in candidates
            ],
        }
        if client is None:
            section = Section(
                title=chapter.title,
                paragraphs=extractive_paragraphs(chapter, segments),
            )
        else:

            def compute(evidence=evidence, chapter=chapter, candidates=candidates):
                instruction = (
                    '将本节整理成中文图文笔记，返回 {"title":"标题",'
                    '"paragraphs":[{"text":"一段讲解的纯文本",'
                    '"source_segment_ids":["seg_…"]}],'
                    '"images":[{"frame_id":"frame_…","caption":"图注"}]}。'
                    "每段必须引用确实支持它的字幕 ID，保留适用条件、例子和操作步骤。"
                    "不输出 HTML、Markdown 图片、外部链接或自行构造的时间戳。"
                )
                instruction += (
                    "结合提供的真实截图选择最多 3 张与讲解相关的清晰图片；"
                    "图注仅描述能看清的内容，正文论断仍以字幕为依据，无合适图片时 images=[]。"
                    if vision
                    else "你未收到实际图片，因此 images 必须为 []，不要猜测画面内容。"
                )
                try:
                    section = Section.model_validate(
                        client.complete(
                            instruction,
                            evidence,
                            root=root,
                            frames=candidates if vision else None,
                            vision=vision,
                        )
                    )
                except ValidationError as exc:
                    raise PipelineError("模型返回的笔记结构无效，请重试当前生成阶段") from exc
                validate_section(
                    section, set(chapter.segment_ids), {f.frame_id for f in candidates}
                )
                return section.model_dump()

            signature = [client.signature(vision), evidence]
            if vision:
                signature.append([file_hash(asset_file(root, f.asset_path)) for f in candidates])
            section = Section.model_validate(cache.run("section", signature, compute))
        if not vision:
            # These are explicitly temporal candidate illustrations, not visually verified.
            chosen = candidates if len(candidates) <= 2 else [candidates[0], candidates[-1]]
            section.images = [
                Illustration(frame_id=f.frame_id, caption="按时间匹配的候选配图，未做视觉核验")
                for f in chosen
            ]
        validate_section(section, set(chapter.segment_ids), {f.frame_id for f in candidates})
        sections.append(section)
    warnings = media.warnings + transcript.warnings
    if not frames:
        warnings.append("未找到通过清晰度筛选的截图，本次输出为文字笔记。")
    if client is None:
        warnings.append("本次为原文整理：保留字幕原句，按时间分段，未进行模型提炼。")
    elif not vision:
        warnings.append("正文经过模型整理；配图按时间匹配，未做视觉语义核验。")
    else:
        warnings.append("正文与图注经过模型整理，请结合原视频核对专业名词及结论。")
    return Note(
        title=media.title,
        mode="extractive" if client is None else "vision" if vision else "llm",
        sections=sections,
        warnings=list(dict.fromkeys(warnings)),
    )
