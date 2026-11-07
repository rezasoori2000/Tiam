"""Event clips (spec 5.3, ADR 0008).

Each camera worker keeps a FrameRing: the last CLIP_PRE_S seconds of clean frames at CLIP_FPS as
JPEG bytes, each with the track boxes seen on it. When an incident is saved, a ClipRecorder keeps
collecting for CLIP_POST_S more seconds, then a background thread writes
  data/retail_event_clips/{event_id}.mp4   raw H.264 (no boxes drawn: evidence stays untouched)
  data/retail_event_clips/{event_id}.json  per-frame boxes, drawn by the UI on playback
and sets Event.has_clip. Nothing here blocks the camera thread except a JPEG encode at 5 fps.
"""
import json
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# shortcut: fixed defaults (spec 5.3); move to Detection Settings if sites need to tune them.
CLIP_PRE_S = 10.0
CLIP_POST_S = 10.0
CLIP_FPS = 5.0
CLIP_JPEG_QUALITY = 80

CLIPS_DIR = Path(__file__).resolve().parent.parent / "data" / "retail_event_clips"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

# (capture ts, jpeg bytes, boxes on that frame)
RingItem = Tuple[float, bytes, list]

_writer = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clip-writer")
MS = Fraction(1, 1000)  # frame timestamps are milliseconds since the clip's first frame


def clip_path(event_id: int) -> Path:
    return CLIPS_DIR / f"{event_id}.mp4"


def overlay_path(event_id: int) -> Path:
    return CLIPS_DIR / f"{event_id}.json"


def delete_clip(event_id: int) -> None:
    clip_path(event_id).unlink(missing_ok=True)
    overlay_path(event_id).unlink(missing_ok=True)


def boxes_from_tracks(tracks) -> list:
    """Overlay boxes for one frame, from VisionEngine.last_tracks."""
    return [
        {
            "id": t.track_id, "cls": t.class_name, "xyxy": [round(float(v), 1) for v in t.xyxy],
            "conf": None if t.confidence is None else round(t.confidence, 2), "threat": bool(t.alerts),
        }
        for t in tracks
    ]


class FrameRing:
    def __init__(self, pre_s: float = CLIP_PRE_S, fps: float = CLIP_FPS):
        self.pre_s = pre_s
        self.interval = 1.0 / fps
        self._items: Deque[RingItem] = deque()
        self._last_ts = float("-inf")

    def add(self, ts: float, frame: np.ndarray, boxes: list) -> Optional[RingItem]:
        """Keeps every 1/fps-th frame; returns the stored item (or None if this frame was skipped)."""
        if ts - self._last_ts < self.interval:
            return None
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, CLIP_JPEG_QUALITY])
        if not ok:
            return None
        self._last_ts = ts
        item = (ts, jpeg.tobytes(), boxes)
        self._items.append(item)
        while self._items and ts - self._items[0][0] > self.pre_s:
            self._items.popleft()
        return item

    def items(self) -> List[RingItem]:
        return list(self._items)


class ClipRecorder:
    """Per camera worker: collects post-incident frames, then hands each clip to the writer."""

    def __init__(self, on_written, post_s: float = CLIP_POST_S):
        self._pending: List[dict] = []
        self._post_s = post_s
        self._on_written = on_written  # callback(event_id) -> marks the Event row, from the writer thread

    def start(self, event_id: int, ring: FrameRing, now_ts: float) -> None:
        self._pending.append({"event_id": event_id, "frames": ring.items(), "until": now_ts + self._post_s})

    def on_frame(self, item: Optional[RingItem]) -> None:
        if not self._pending:
            return
        if item is not None:
            for p in self._pending:
                if not p["frames"] or item[0] > p["frames"][-1][0]:
                    p["frames"].append(item)
        ts = item[0] if item is not None else None
        done = [p for p in self._pending if ts is not None and ts >= p["until"]]
        for p in done:
            self._submit(p)
        self._pending = [p for p in self._pending if p not in done]

    def flush(self) -> None:
        """Worker stopping: write whatever was collected."""
        for p in self._pending:
            self._submit(p)
        self._pending = []

    def _submit(self, p: dict) -> None:
        _writer.submit(_write_clip_safe, p["event_id"], p["frames"], self._on_written)


def _write_clip_safe(event_id: int, frames: List[RingItem], on_written) -> None:
    try:
        if write_clip(event_id, frames):
            on_written(event_id)
    except Exception:  # pragma: no cover - a failed clip must never affect detection/alerts
        logger.exception("Writing clip for event %s failed", event_id)


def write_clip(event_id: int, frames: List[RingItem]) -> bool:
    """Writes the MP4 (variable frame rate, real capture timing) + JSON overlay. False if no frames."""
    if not frames:
        return False
    import av  # PyAV ships FFmpeg with libx264 (browser-playable H.264)

    t0 = frames[0][0]
    first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
    h, w = first.shape[:2]
    tmp = clip_path(event_id).with_suffix(".tmp.mp4")
    # faststart: moov atom up front so the browser can start playing before the whole file loads
    with av.open(str(tmp), "w", format="mp4", options={"movflags": "+faststart"}) as container:
        stream = container.add_stream("libx264")
        stream.width, stream.height, stream.pix_fmt = w - w % 2, h - h % 2, "yuv420p"
        # Millisecond time base for the ENCODER too: with rate=5 its time base was 1/5 s, so real
        # (uneven) capture times collided on that grid and the muxer rejected them (FFmpeg error 22).
        stream.codec_context.time_base = MS
        stream.codec_context.framerate = Fraction(int(CLIP_FPS))
        stream.time_base = MS
        stream.options = {"preset": "veryfast", "crf": "23"}
        last_pts = -1
        for ts, jpeg, _ in frames:
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            vf = av.VideoFrame.from_ndarray(img[: stream.height, : stream.width], format="bgr24")
            vf.pts = max(int(round((ts - t0) * 1000)), last_pts + 1)
            vf.time_base = MS  # not stream.time_base: the mp4 muxer changes that (to 1/16000) once writing starts
            last_pts = vf.pts
            for packet in stream.encode(vf):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    tmp.replace(clip_path(event_id))
    overlay = {
        "width": w, "height": h, "start_ts": t0,
        "frames": [{"t": round(ts - t0, 3), "boxes": boxes} for ts, _, boxes in frames],
    }
    overlay_path(event_id).write_text(json.dumps(overlay), encoding="utf-8")
    return True
