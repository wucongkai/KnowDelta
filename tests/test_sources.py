import json

import httpx
import pytest

from knowdelta.bilibili_source import acquire_bilibili, normalize_url
from knowdelta.storage import PipelineError


def test_bilibili_url_preserves_part_and_removes_tracking():
    url, part = normalize_url(
        "https://www.bilibili.com/video/BV1p5qhYsE4f/?p=2&vd_source=private&spm_id_from=x"
    )
    assert url == "https://www.bilibili.com/video/BV1p5qhYsE4f/?p=2"
    assert part == 2


@pytest.mark.parametrize(
    "url",
    [
        "https://bilibili.com.evil.example/video/BV1p5qhYsE4f/",
        "file:///etc/passwd",
        "http://127.0.0.1/video/BV1p5qhYsE4f/",
        "https://www.bilibili.com/video/BV1p5qhYsE4f/?p=0",
        "https://user:password@www.bilibili.com/video/BV1p5qhYsE4f/",
    ],
)
def test_reject_unsupported_urls(url):
    with pytest.raises(PipelineError):
        normalize_url(url)


def test_short_link_redirect_to_private_host_is_not_followed(monkeypatch):
    original = httpx.Client
    calls = []

    def response(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal"})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(response)),
    )
    with pytest.raises(PipelineError):
        normalize_url("https://b23.tv/example")
    assert len(calls) == 1


def test_bilibili_download_survives_subtitle_failure(local_input, tmp_path, monkeypatch):
    import shutil

    import knowdelta.bilibili_source as module

    video, _ = local_input
    root = tmp_path / "job"
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if "--dump-single-json" in args:
            return json.dumps({"id": "BV1p5qhYsE4f_p2", "title": "示例", "duration": 12})
        if "--write-subs" in args:
            raise PipelineError("字幕需要登录")
        shutil.copy2(video, root / "media" / "video.mp4")
        return ""

    monkeypatch.setattr(module, "run_command", command)
    media = acquire_bilibili(
        "https://www.bilibili.com/video/BV1p5qhYsE4f/?p=2", 2, root, None, "zh", 60, 10000000
    )
    assert media.part == 2
    assert media.warnings
    assert len(calls) == 3
    assert all("--no-playlist" in args for args in calls)
