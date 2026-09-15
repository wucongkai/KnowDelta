from .llm import ModelClient
from .models import Chapter, Frame, Segment, Transcript
from .storage import Cache, PipelineError


def group_segments(segments: list[Segment], seconds: int = 180) -> list[list[Segment]]:
    groups, current, chars = [], [], 0
    for segment in segments:
        if len(segment.text) > 8000:
            raise PipelineError("单条字幕过长，请先按句子拆分字幕")
        if current and (
            segment.end_ms - current[0].start_ms > seconds * 1000
            or chars + len(segment.text) > 8000
            or len(current) >= 150
        ):
            groups.append(current)
            current, chars = [], 0
        current.append(segment)
        chars += len(segment.text)
    if current:
        groups.append(current)
    return groups


def parse_outline(value: dict, group: list[Segment]) -> list[dict]:
    """Require an ordered partition: no dropped, duplicated, or invented evidence."""
    try:
        rows = value["chapters"]
        if not isinstance(rows, list) or not rows or len(rows) > 12:
            raise ValueError
        ids = [segment.segment_id for segment in group]
        result, start = [], 0
        for row in rows:
            title = row["title"]
            end = ids.index(row["end_segment_id"])
            if not isinstance(title, str) or not title.strip() or len(title) > 200 or end < start:
                raise ValueError
            result.append({"title": title.strip(), "segment_ids": ids[start : end + 1]})
            start = end + 1
        if start != len(ids):
            raise ValueError
        return result
    except (KeyError, ValueError, TypeError) as exc:
        raise PipelineError("模型章节划分遗漏、重复或引用了不存在的字幕，请重试") from exc


def make_chapters(
    transcript: Transcript,
    client: ModelClient | None,
    cache: Cache,
    seconds: int,
) -> list[Chapter]:
    chapters = []
    for group in group_segments(transcript.segments, seconds):
        if client is None:
            rows = [
                {
                    "title": f"原文片段 {len(chapters) + 1}",
                    "segment_ids": [s.segment_id for s in group],
                }
            ]
        else:
            evidence = {"segments": [s.model_dump() for s in group]}

            def compute(evidence=evidence, group=group):
                value = client.complete(
                    '将连续字幕按主题划分为 1～12 节。返回 {"chapters": '
                    '[{"title":"主题标题","end_segment_id":"该节最后一句字幕ID"}]}。'
                    "各节按原顺序连续覆盖全部输入，最后一节必须以最后一句字幕结束。",
                    evidence,
                )
                return parse_outline(value, group)

            rows = cache.run("outline", [client.signature(), evidence], compute)
        for row in rows:
            chapters.append(Chapter(chapter_id=f"chapter_{len(chapters) + 1:04d}", **row))
    return chapters


def frames_for_chapter(
    chapter: Chapter,
    segments: dict[str, Segment],
    frames: list[Frame],
    limit: int = 6,
) -> list[Frame]:
    start = min(segments[sid].start_ms for sid in chapter.segment_ids)
    end = max(segments[sid].end_ms for sid in chapter.segment_ids)
    candidates = [frame for frame in frames if start - 4000 <= frame.timestamp_ms <= end + 4000]
    if len(candidates) <= limit:
        return candidates
    # Uniform temporal buckets prevent choosing six almost-identical opening shots.
    selected = []
    for index in range(limit):
        group = candidates[
            index * len(candidates) // limit : (index + 1) * len(candidates) // limit
        ]
        selected.append(max(group, key=lambda frame: frame.sharpness))
    return sorted(selected, key=lambda frame: frame.timestamp_ms)
