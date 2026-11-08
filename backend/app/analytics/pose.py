"""PoseRunner (spec 5.2): COCO-17 keypoints for the person tracks a detector asks for.

Runs the pose model once on a crop around the requested tracks (more pixels for distant people,
less work than the full frame) and matches each pose to a track by box overlap. Loaded lazily and
shared across cameras, like the detection engine; Ultralytics/AGPL like the main detector (ADR 0007).
"""
import logging
import threading
from typing import Dict, Iterable, Optional

import numpy as np

from ..detection_engine import MODELS_DIR

logger = logging.getLogger(__name__)

POSE_MODEL = "yolov8s-pose.pt"
POSE_IMGSZ = 640
POSE_CONF = 0.25
CROP_MARGIN = 0.25  # of the requested boxes' union, each side
MATCH_IOU = 0.3

# COCO-17 keypoint indices
L_WRIST, R_WRIST, L_ANKLE, R_ANKLE = 9, 10, 15, 16
L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12

_model = None
_model_lock = threading.Lock()
_load_failed = False


def _load():
    global _model, _load_failed
    with _model_lock:
        if _model is None and not _load_failed:
            path = MODELS_DIR / POSE_MODEL
            if not path.exists():
                _load_failed = True
                logger.warning("Pose model %s not found: fight detection is disabled", path)
                return None
            from ultralytics import YOLO
            _model = YOLO(str(path))
        return _model


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class PoseRunner:
    def __init__(self, device: str = "cuda"):
        self.device = device

    def run(self, frame: np.ndarray, tracks: Iterable) -> Dict[int, np.ndarray]:
        """tracks: TrackViews to get keypoints for. Returns track_id -> (17, 3) array of
        (x, y, confidence) in full-frame pixels; tracks without a matching pose are left out."""
        tracks = list(tracks)
        model = _load()
        if model is None or not tracks:
            return {}
        h, w = frame.shape[:2]
        boxes = np.array([t.xyxy for t in tracks], dtype=float)
        x1, y1 = boxes[:, 0].min(), boxes[:, 1].min()
        x2, y2 = boxes[:, 2].max(), boxes[:, 3].max()
        mx, my = (x2 - x1) * CROP_MARGIN, (y2 - y1) * CROP_MARGIN
        cx1, cy1 = int(max(0, x1 - mx)), int(max(0, y1 - my))
        cx2, cy2 = int(min(w, x2 + mx)), int(min(h, y2 + my))
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return {}
        with _model_lock:
            result = model.predict(crop, verbose=False, device=self.device, conf=POSE_CONF, imgsz=POSE_IMGSZ)[0]
        if result.keypoints is None or result.boxes is None or len(result.boxes) == 0:
            return {}
        offset = np.array([cx1, cy1, cx1, cy1], dtype=float)
        pose_boxes = result.boxes.xyxy.cpu().numpy() + offset
        kpts = result.keypoints.data.cpu().numpy().copy()  # (N, 17, 3)
        kpts[:, :, 0] += cx1
        kpts[:, :, 1] += cy1
        out: Dict[int, np.ndarray] = {}
        used = set()
        for t in tracks:  # greedy best-overlap match, one pose per track
            best, best_iou = None, MATCH_IOU
            for i, pb in enumerate(pose_boxes):
                if i in used:
                    continue
                iou = _iou(t.xyxy, pb)
                if iou >= best_iou:
                    best, best_iou = i, iou
            if best is not None:
                used.add(best)
                out[t.track_id] = kpts[best]
        return out


def model_available() -> bool:
    return (MODELS_DIR / POSE_MODEL).exists()


def body_height(kp: np.ndarray, box) -> float:
    """Reference length for normalising speeds: the box height (robust; keypoints may be missing)."""
    return max(1.0, float(box[3] - box[1]))


def point(kp: np.ndarray, idx: int, min_conf: float = 0.3) -> Optional[np.ndarray]:
    return kp[idx, :2] if kp is not None and kp[idx, 2] >= min_conf else None
