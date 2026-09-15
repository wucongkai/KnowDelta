import wave

import cv2
import numpy as np

from knowdelta.frames import select_frames
from knowdelta.media import extract_audio, ffmpeg_binary, run_command
from knowdelta.models import Media


def test_real_ffmpeg_audio_extraction(tmp_path):
    video = tmp_path / "tone.mp4"
    run_command(
        [
            ffmpeg_binary(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ]
    )
    destination = tmp_path / "audio.wav"
    extract_audio(video, destination)
    with wave.open(str(destination)) as audio:
        assert audio.getframerate() == 16000
        assert audio.getnchannels() == 1
        assert audio.getnframes() >= 16000


def test_blank_video_can_degrade_to_no_frames(tmp_path):
    path = tmp_path / "blank.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5, (320, 180))
    for _ in range(10):
        writer.write(np.zeros((180, 320, 3), dtype=np.uint8))
    writer.release()
    media = Media(source_id="blank", title="blank", duration_ms=2000, video_path=path.name)
    assert select_frames(media, tmp_path) == []
