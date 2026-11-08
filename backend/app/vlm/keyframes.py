"""Key frames for AI verification (spec 6.3): up to MAX_CROPS frames from [t - PRE_S, t + POST_S] of the
camera's FrameRing, each cropped around the incident's tracks, plus one full-frame thumbnail. Boxes are
drawn with track ids (incident tracks red, others amber) so the prompt can refer to "#id"."""
from typing import Iterable, List

import cv2
import numpy as np

PRE_S = 6.0
POST_S = 2.0
MAX_CROPS = 6
CROP_EXPAND = 2.5
CROP_MIN, CROP_MAX = 384, 1024
THUMB_W = 768
RED, AMBER = (61, 77, 255), (11, 158, 245)  # BGR, same as the live boxes


def _draw(img: np.ndarray, boxes: list, key_ids: set) -> None:
    for b in boxes:
        x1, y1, x2, y2 = (int(v) for v in b["xyxy"])
        color = RED if b["id"] in key_ids else AMBER
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, f"#{b['id']}", (x1 + 2, max(y1 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def _crop(img: np.ndarray, boxes: list, key_ids: set) -> np.ndarray:
    keys = [b["xyxy"] for b in boxes if b["id"] in key_ids] or [b["xyxy"] for b in boxes]
    h, w = img.shape[:2]
    if not keys:
        return img
    x1 = min(k[0] for k in keys); y1 = min(k[1] for k in keys)
    x2 = max(k[2] for k in keys); y2 = max(k[3] for k in keys)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    half = max(x2 - x1, y2 - y1) * CROP_EXPAND / 2
    half = max(half, 60)
    a, b = int(max(0, cx - half)), int(max(0, cy - half))
    c, d = int(min(w, cx + half)), int(min(h, cy + half))
    crop = img[b:d, a:c]
    long_side = max(crop.shape[:2])
    target = min(max(long_side, CROP_MIN), CROP_MAX)
    if long_side and target != long_side:
        s = target / long_side
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * s)), max(1, int(crop.shape[0] * s))))
    return crop


def build(ring_items: Iterable, incident_ts: float, key_track_ids: Iterable[int]) -> List[bytes]:
    """ring_items: (ts, jpeg, boxes) tuples (clips.FrameRing / ClipRecorder frames)."""
    key_ids = set(int(k) for k in key_track_ids if k is not None)
    window = [it for it in ring_items if incident_ts - PRE_S <= it[0] <= incident_ts + POST_S]
    if not window:
        return []
    step = max(1, len(window) // MAX_CROPS)
    chosen = window[::step][-MAX_CROPS:]
    out: List[bytes] = []
    for ts, jpeg, boxes in chosen:
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        _draw(img, boxes, key_ids)
        ok, enc = cv2.imencode(".jpg", _crop(img, boxes, key_ids), [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            out.append(enc.tobytes())
    # full-frame context: the frame closest to the incident time
    ts, jpeg, boxes = min(window, key=lambda it: abs(it[0] - incident_ts))
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        _draw(img, boxes, key_ids)
        s = THUMB_W / img.shape[1]
        ok, enc = cv2.imencode(".jpg", cv2.resize(img, (THUMB_W, int(img.shape[0] * s))), [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            out.append(enc.tobytes())
    return out
