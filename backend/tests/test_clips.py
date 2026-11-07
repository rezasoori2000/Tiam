import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from app import clips


def frame(v):
    return np.full((540, 960, 3), v % 256, np.uint8)


def test_ring_samples_at_fps_and_trims():
    ring = clips.FrameRing(pre_s=2.0, fps=5.0)
    for i in range(100):  # 10 s at 10 fps
        ring.add(i * 0.1, frame(i), [])
    items = ring.items()
    assert len(items) <= 11  # ~2 s at 5 fps
    assert items[-1][0] - items[0][0] <= 2.0
    assert all(b[0] - a[0] >= 0.199 for a, b in zip(items, items[1:]))


def test_irregular_capture_times_write_fine(tmp_path, monkeypatch):
    """Real cameras deliver frames at uneven intervals; B-frames used to break the MP4 mux (error 22)."""
    import cv2

    monkeypatch.setattr(clips, "CLIPS_DIR", tmp_path)
    rng = np.random.default_rng(1)
    t, frames = 1_762_590_000.0, []
    for _ in range(40):
        t += float(rng.uniform(0.2, 0.45))
        ok, jpeg = cv2.imencode(".jpg", rng.integers(0, 255, (540, 960, 3), dtype=np.uint8))
        frames.append((t, jpeg.tobytes(), []))
    assert clips.write_clip(7, frames)
    assert (tmp_path / "7.mp4").stat().st_size > 0


def test_recorder_writes_mp4_and_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(clips, "CLIPS_DIR", tmp_path)
    monkeypatch.setattr(clips, "_writer", ThreadPoolExecutor(max_workers=1))
    written = []
    ring = clips.FrameRing(pre_s=1.0, fps=5.0)
    rec = clips.ClipRecorder(on_written=written.append, post_s=1.0)
    for i in range(10):
        rec.on_frame(ring.add(i * 0.2, frame(i * 10), [{"id": 1, "cls": "person", "xyxy": [1, 2, 3, 4]}]))
    rec.start(42, ring, now_ts=1.8)
    for i in range(10, 20):
        rec.on_frame(ring.add(i * 0.2, frame(i * 10), []))
    clips._writer.shutdown(wait=True)

    assert written == [42]
    assert (tmp_path / "42.mp4").stat().st_size > 0
    overlay = json.loads((tmp_path / "42.json").read_text())
    assert overlay["frames"][0]["t"] == 0 and overlay["frames"][0]["boxes"][0]["cls"] == "person"
    assert overlay["frames"][-1]["t"] >= 1.0  # post-incident frames included

    import av
    with av.open(str(tmp_path / "42.mp4")) as c:
        assert c.streams.video[0].codec_context.name == "h264"
        assert sum(1 for _ in c.decode(video=0)) == len(overlay["frames"])
