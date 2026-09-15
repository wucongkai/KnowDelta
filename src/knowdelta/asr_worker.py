"""Standalone speech worker; deliberately does not import OpenCV or pipeline modules."""

import sys
from pathlib import Path

from .models import Segment, Transcript
from .storage import write_json


def main():
    from faster_whisper import WhisperModel

    audio, destination, language, model, prompt = sys.argv[1:]
    engine = WhisperModel(model, device="cpu", compute_type="int8")
    iterator, info = engine.transcribe(
        audio,
        language=language,
        vad_filter=True,
        initial_prompt=prompt or None,
    )
    segments = []
    for item in iterator:
        if not item.text.strip() or item.end <= item.start:
            continue
        segments.append(
            Segment(
                segment_id=f"seg_{len(segments) + 1:05d}",
                start_ms=round(item.start * 1000),
                end_ms=max(round(item.start * 1000) + 1, round(item.end * 1000)),
                text=item.text.strip(),
                source="asr",
            )
        )
    result = Transcript(segments=segments, language=info.language, origin=f"faster-whisper:{model}")
    write_json(Path(destination), result.model_dump())


if __name__ == "__main__":
    main()
