import json
import re
import shutil
import zipfile
from dataclasses import replace

import pytest

from knowdelta.pipeline import Options, run
from knowdelta.storage import PipelineError, read_json


def test_local_full_pipeline_portable_export_and_resume(local_input, tmp_path, monkeypatch):
    video, subtitles = local_input
    options = Options(video=video, subtitles=subtitles, output=tmp_path / "jobs", extractive=True)
    output = run(options)
    md = (output / "note.md").read_text()
    assert "客户端连接到数据库服务器" in md
    assert "未进行模型提炼" in md
    assert len(list((output / "assets").glob("*.jpg"))) == 2
    with zipfile.ZipFile(output / "note.zip") as archive:
        archive.extractall(tmp_path / "moved")
        assert not any("media/" in name or "cache/" in name for name in archive.namelist())
    for relative in re.findall(r"!\[.*?\]\((.*?)\)", md):
        assert (tmp_path / "moved" / relative).is_file()
    assert "src='assets/" in (tmp_path / "moved" / "note.html").read_text()

    import knowdelta.pipeline as pipeline

    def unexpected(*args, **kwargs):
        raise AssertionError("completed media stages should be cached")

    monkeypatch.setattr(pipeline, "acquire_local", unexpected)
    monkeypatch.setattr(pipeline, "select_frames", unexpected)
    monkeypatch.setattr(pipeline, "normalize_transcript", unexpected)
    assert run(options) == output
    assert run(replace(options, chapter_seconds=5)).is_dir()


def test_renamed_upload_keeps_title_when_media_cache_is_reused(local_input, tmp_path, monkeypatch):
    from knowdelta import pipeline

    video, subtitles = local_input
    options = Options(video=video, subtitles=subtitles, output=tmp_path / "jobs", extractive=True)
    run(options)
    renamed = tmp_path / "另一个标题.mp4"
    shutil.copy2(video, renamed)

    def unexpected(*args, **kwargs):
        raise AssertionError("renaming should not reacquire the same media bytes")

    monkeypatch.setattr(pipeline, "acquire_local", unexpected)
    options.video = renamed
    directory = run(options)
    assert read_json(directory / "note.json")["title"] == "另一个标题"


def test_model_and_vision_modes_use_grounded_ids_and_cache(local_input, tmp_path, fake_model):
    video, subtitles = local_input
    options = Options(video=video, subtitles=subtitles, output=tmp_path / "jobs")
    output = run(options)
    assert len(fake_model) == 2
    assert "test-secret" not in (output / "note.json").read_text()
    assert json.loads((output / "note.json").read_text())["mode"] == "llm"
    run(options)
    assert len(fake_model) == 2
    output = run(replace(options, vision=True))
    assert len(fake_model) == 3  # outline remains reusable
    request = fake_model[-1]
    assert request["model"] == "test-vision"
    content = request["messages"][1]["content"]
    assert any(row["type"] == "image_url" for row in content)
    note = json.loads((output / "note.json").read_text())
    assert note["mode"] == "vision"
    assert note["sections"][0]["images"][0]["caption"] == "查询执行步骤"


def test_invalid_image_cache_regenerates_frames(local_input, tmp_path):
    video, subtitles = local_input
    options = Options(video=video, subtitles=subtitles, output=tmp_path / "jobs", extractive=True)
    output = run(options)
    root = output.parent.parent
    shutil.rmtree(root / "assets")
    assert run(options).is_dir()
    assert list((root / "assets").glob("*.jpg"))


def test_size_and_duration_limits(local_input, tmp_path):
    video, subtitles = local_input
    with pytest.raises(PipelineError, match="max-duration"):
        run(
            Options(
                video=video,
                subtitles=subtitles,
                output=tmp_path / "jobs",
                extractive=True,
                max_duration=1,
            )
        )


def test_generation_failure_resumes_without_media_work(
    local_input, tmp_path, monkeypatch, fake_model
):
    import knowdelta.pipeline as pipeline

    video, subtitles = local_input
    options = Options(video=video, subtitles=subtitles, output=tmp_path / "jobs")
    original = pipeline.generate_note

    def fail(*args, **kwargs):
        raise PipelineError("simulated model outage")

    monkeypatch.setattr(pipeline, "generate_note", fail)
    with pytest.raises(PipelineError):
        run(options)
    monkeypatch.setattr(pipeline, "generate_note", original)

    def unexpected(*args, **kwargs):
        raise AssertionError("media must not run again")

    monkeypatch.setattr(pipeline, "acquire_local", unexpected)
    monkeypatch.setattr(pipeline, "normalize_transcript", unexpected)
    assert run(options).is_dir()
