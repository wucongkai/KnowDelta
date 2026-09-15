import json

import pytest

from knowdelta.alignment import parse_outline
from knowdelta.models import Media, Note, Paragraph, Section, Segment, Transcript
from knowdelta.note_generator import validate_section
from knowdelta.renderer import export_note, validate_note
from knowdelta.storage import PipelineError, asset_file
from knowdelta.transcript import normalize_transcript, quality_issues, read_subtitles


def segment(start=0, end=12000, text="示例内容"):
    return Segment(segment_id="seg_00001", start_ms=start, end_ms=end, text=text, source="subtitle")


@pytest.mark.parametrize(
    "content,suffix",
    [
        ("WEBVTT\n\n00:00:00.000 --> 00:00:12.000\n你好<b>世界</b>\n", ".vtt"),
        (json.dumps({"body": [{"from": 0, "to": 12, "content": "你好世界"}]}), ".json"),
        ("1\n00:00:00,000 --> 00:00:12,000\n你好世界\n", ".srt"),
    ],
)
def test_subtitle_formats_and_timestamps(tmp_path, content, suffix):
    path = tmp_path / f"captions{suffix}"
    path.write_text(content)
    rows = read_subtitles(path)
    assert rows[0].text == "你好世界"
    assert rows[0].end_ms == 12000
    assert not quality_issues(rows, 12000)


@pytest.mark.parametrize(
    "rows,duration",
    [
        ([], 10000),
        ([segment(0, 100)], 600000),
        ([segment(0, 14000)], 12000),
        ([segment(12000, 12500)], 12000),
    ],
)
def test_bad_captions_are_not_accepted(rows, duration):
    assert quality_issues(rows, duration)


@pytest.mark.parametrize("bad_subtitles", [False, True])
def test_missing_or_bad_subtitles_use_asr(local_input, tmp_path, monkeypatch, bad_subtitles):
    import knowdelta.transcript as module

    video, subtitles = local_input
    paths = []
    if bad_subtitles:
        subtitles.write_text("1\n00:00:00,000 --> 00:00:00,100\n缺失的字幕\n")
        paths = [subtitles.name]
    media = Media(
        source_id="test",
        title="test",
        duration_ms=12000,
        video_path=video.name,
        subtitle_paths=paths,
    )
    calls = []

    def asr(*args):
        calls.append(args)
        return Transcript(segments=[segment()], language="zh", origin="test-asr")

    monkeypatch.setattr(module, "transcribe", asr)
    result = normalize_transcript(media, tmp_path, "zh", "base")
    assert len(calls) == 1
    assert result.origin == "test-asr"


@pytest.mark.parametrize("end_ids", [[], ["unknown"], ["seg_00001", "seg_00001"]])
def test_outline_rejects_missing_duplicate_or_unknown_ids(end_ids):
    with pytest.raises(PipelineError):
        parse_outline(
            {"chapters": [{"title": "标题", "end_segment_id": sid} for sid in end_ids]}, [segment()]
        )


def test_reject_fabricated_sources_and_path_traversal(tmp_path):
    section = Section(
        title="标题", paragraphs=[Paragraph(text="结论", source_segment_ids=["fake"])]
    )
    with pytest.raises(PipelineError):
        validate_section(section, {"seg_00001"}, set())
    with pytest.raises(PipelineError):
        asset_file(tmp_path, "../outside.txt")


def test_export_escapes_untrusted_text(tmp_path):
    raw = "<script>alert(1)</script> ![remote](https://evil.example/a.png)"
    transcript = Transcript(segments=[segment(text=raw)], language="zh", origin="subtitle")
    media = Media(source_id="test", title=raw, duration_ms=12000, video_path="unused.mp4")
    note = Note(
        title=raw,
        mode="extractive",
        sections=[
            Section(
                title=raw,
                paragraphs=[Paragraph(text=raw, source_segment_ids=["seg_00001"])],
            )
        ],
    )
    directory = export_note(note, media, transcript, [], tmp_path)
    assert "<script>" not in (directory / "note.html").read_text()
    assert "![remote]" not in (directory / "note.md").read_text()
    note.sections[0].paragraphs[0].source_segment_ids = ["made-up"]
    with pytest.raises(PipelineError):
        validate_note(note, media, transcript, [], tmp_path)
