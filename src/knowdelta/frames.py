from pathlib import Path

import cv2
import numpy as np

from .models import Frame, Media
from .storage import PipelineError, asset_file, atomic_write


def image_hash(gray: np.ndarray) -> np.ndarray:
    small = cv2.resize(gray, (9, 8))
    return small[:, 1:] > small[:, :-1]


def select_frames(
    media: Media,
    root: Path,
    interval: float = 5,
    max_frames: int = 180,
) -> list[Frame]:
    """Sample scene changes + periodic frames, then quality-filter and deduplicate.

    Scene analysis is sampled (not frame-exhaustive); short-lived content can be missed.
    Store only timestamps during discovery, so long videos don't retain decoded images.
    """
    capture = cv2.VideoCapture(str(asset_file(root, media.video_path)))
    if not capture.isOpened():
        raise PipelineError("视频无法解码，不能提取截图")
    duration = media.duration_ms / 1000
    step = max(1.0, duration / 3600)
    candidates = []
    previous = None
    last_periodic = -interval
    recent = []
    try:
        for seconds in np.arange(0, duration, step):
            capture.set(cv2.CAP_PROP_POS_MSEC, float(seconds * 1000))
            ok, picture = capture.read()
            if not ok:
                continue
            thumb = cv2.resize(picture, (320, 180))
            gray = cv2.cvtColor(thumb, cv2.COLOR_BGR2GRAY)
            delta = 0 if previous is None else float(cv2.absdiff(gray, previous).mean())
            previous = gray
            periodic = seconds - last_periodic >= interval
            if not periodic and delta < 18:
                continue
            if periodic:
                last_periodic = seconds
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if gray.mean() < 8 or gray.std() < 4 or sharpness < 12:
                continue
            signature = image_hash(gray)
            recent = [
                (time, hashed, image) for time, hashed, image in recent if seconds - time < 60
            ]
            # A coarse hash alone collapses different PPT/code pages with the same layout.
            if any(
                np.count_nonzero(signature != hashed) <= 3
                and np.mean(cv2.absdiff(gray, image) > 20) < 0.001
                for _, hashed, image in recent
            ):
                continue
            recent.append((seconds, signature, gray))
            candidates.append((float(seconds), sharpness))

        # Keep the clearest candidate in each temporal bucket to preserve late chapters.
        if len(candidates) > max_frames:
            buckets = {}
            for item in candidates:
                bucket = min(max_frames - 1, int(item[0] / duration * max_frames))
                if bucket not in buckets or item[1] > buckets[bucket][1]:
                    buckets[bucket] = item
            candidates = sorted(buckets.values())
        assets = root / "assets"
        assets.mkdir(exist_ok=True)
        result = []
        for seconds, sharpness in candidates:
            timestamp = min(media.duration_ms - 1, round(seconds * 1000))
            capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp))
            ok, picture = capture.read()
            if not ok:
                continue
            height, width = picture.shape[:2]
            if width > 1280:
                picture = cv2.resize(picture, (1280, round(height * 1280 / width)))
            frame_id = f"frame_{timestamp:09d}"
            path = assets / f"{frame_id}.jpg"
            ok, encoded = cv2.imencode(".jpg", picture, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if ok:
                atomic_write(path, encoded.tobytes())
                result.append(
                    Frame(
                        frame_id=frame_id,
                        timestamp_ms=timestamp,
                        asset_path=str(path.relative_to(root)),
                        sharpness=sharpness,
                    )
                )
        return result
    finally:
        capture.release()
