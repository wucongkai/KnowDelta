import json

import cv2
import numpy as np
import pytest


@pytest.fixture
def local_input(tmp_path):
    video = tmp_path / "lesson.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 5, (640, 360))
    assert writer.isOpened()
    for number in range(60):
        frame = np.full((360, 640, 3), 245, dtype=np.uint8)
        if number < 30:
            title, labels = "MySQL architecture", ["Client", "SQL server", "Storage engine"]
        else:
            title, labels = "Query execution", ["Parse", "Optimize", "Execute"]
        cv2.putText(frame, title, (25, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (50, 50, 50), 2)
        for i, label in enumerate(labels):
            cv2.rectangle(frame, (50, 80 + i * 85), (580, 140 + i * 85), (120, 85, 25), 2)
            cv2.putText(
                frame, label, (80, 122 + i * 85), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 60, 30), 2
            )
        writer.write(frame)
    writer.release()
    subtitles = tmp_path / "lesson.srt"
    subtitles.write_text(
        "1\n00:00:00,000 --> 00:00:04,000\n客户端连接到数据库服务器。\n\n"
        "2\n00:00:04,000 --> 00:00:08,000\n服务器对查询进行解析和优化。\n\n"
        "3\n00:00:08,000 --> 00:00:12,000\n执行器调用存储引擎读取数据。\n",
        encoding="utf-8",
    )
    return video, subtitles


@pytest.fixture
def fake_model(monkeypatch):
    """Exercise real HTTP request building and JSON parsing without paid model calls."""
    import httpx

    original_client = httpx.Client
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        content = payload["messages"][1]["content"]
        text = content if isinstance(content, str) else content[0]["text"]
        data = json.loads(text.split("输入数据：\n", 1)[1])
        if "end_segment_id" in text.split("输入数据：\n", 1)[0]:
            answer = {
                "chapters": [
                    {"title": "查询如何执行", "end_segment_id": data["segments"][-1]["segment_id"]}
                ]
            }
        else:
            answer = {
                "title": "查询如何执行",
                "paragraphs": [
                    {
                        "text": "服务器先解析和优化查询，再读取数据。",
                        "source_segment_ids": [s["segment_id"] for s in data["segments"]],
                    }
                ],
                "images": (
                    [{"frame_id": data["frames"][0]["frame_id"], "caption": "查询执行步骤"}]
                    if isinstance(content, list) and data["frames"]
                    else []
                ),
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setenv("KNOWDELTA_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("KNOWDELTA_LLM_MODEL", "test-text")
    monkeypatch.setenv("KNOWDELTA_VISION_MODEL", "test-vision")
    monkeypatch.setenv("KNOWDELTA_LLM_API_KEY", "test-secret-do-not-export")
    return requests
