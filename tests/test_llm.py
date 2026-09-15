import json

import httpx
import pytest

from knowdelta.llm import ModelClient
from knowdelta.storage import PipelineError

HTTP_CLIENT = httpx.Client


def mocked_transport(monkeypatch, responses):
    original = HTTP_CLIENT
    calls = []

    def respond(request):
        calls.append(request)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond))
    )
    monkeypatch.setattr("knowdelta.llm.time.sleep", lambda seconds: None)
    return calls


def completion(content="{}", finish="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
        },
    )


def test_rate_limit_retries_but_auth_failure_does_not(monkeypatch):
    calls = mocked_transport(monkeypatch, [httpx.Response(429), completion('{"ok":true}')])
    model = ModelClient("https://example.com/v1", "model", "secret")
    assert model.complete("JSON", {}) == {"ok": True}
    assert len(calls) == 2
    calls = mocked_transport(monkeypatch, [httpx.Response(401, text="secret response")])
    with pytest.raises(PipelineError) as error:
        model.complete("JSON", {})
    assert "secret" not in str(error.value)
    assert len(calls) == 1


def test_truncated_response_is_rejected(monkeypatch):
    calls = mocked_transport(monkeypatch, [completion('{"ok":', "length")])
    with pytest.raises(PipelineError, match="截断"):
        ModelClient("https://example.com/v1", "model", "secret").complete("JSON", {})
    assert len(calls) == 1


def test_invalid_json_is_retried_with_limit(monkeypatch):
    calls = mocked_transport(monkeypatch, [completion("not json")])
    with pytest.raises(PipelineError, match="JSON"):
        ModelClient("https://example.com/v1", "model", "secret").complete("JSON", {})
    assert len(calls) == 3


def test_model_change_only_regenerates_model_stages(local_input, tmp_path, monkeypatch, fake_model):
    from knowdelta.pipeline import Options, run

    video, subtitles = local_input
    options = Options(video=video, subtitles=subtitles, output=tmp_path / "jobs")
    output = run(options)
    transcript = output.parent.parent / "transcript.json"
    old_text = json.loads(transcript.read_text())
    monkeypatch.setenv("KNOWDELTA_LLM_MODEL", "another-model")
    run(options)
    assert len(fake_model) == 4
    assert fake_model[-1]["model"] == "another-model"
    assert json.loads(transcript.read_text()) == old_text
