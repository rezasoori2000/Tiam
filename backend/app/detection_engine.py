"""Object-detection engine behind one small interface (ADR 0007).

Today the only engine is Ultralytics YOLO (AGPL-3.0). Everything else in the pipeline only talks to
`DetectionEngine`, so a non-AGPL engine (RT-DETR, D-FINE, YOLOX...) can be added later by
implementing `predict` + `class_names` and registering it in `load_engine`.
"""
import threading
from pathlib import Path
from typing import Dict, Protocol, Tuple

import numpy as np
import supervision as sv

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
DEFAULT_MODEL = "yolov8s.pt"


class DetectionEngine(Protocol):
    class_names: Dict[int, str]

    def predict(self, frame: np.ndarray, conf: float, imgsz: int, device: str) -> sv.Detections: ...


class UltralyticsEngine:
    """One loaded YOLO model. Shared by every camera using the same weights (see load_engine);
    YOLO.predict() isn't safe to call concurrently on one instance, hence the lock."""

    def __init__(self, path: str):
        from ultralytics import YOLO  # imported lazily: only this engine needs it

        self._model = YOLO(path)
        self._lock = threading.Lock()
        self.class_names: Dict[int, str] = dict(self._model.model.names)

    def predict(self, frame: np.ndarray, conf: float, imgsz: int, device: str) -> sv.Detections:
        with self._lock:
            result = self._model.predict(frame, verbose=False, device=device, conf=conf, imgsz=imgsz)[0]
        return sv.Detections.from_ultralytics(result)


_engines: Dict[str, DetectionEngine] = {}
_engines_lock = threading.Lock()


def resolve_model_path(name: str) -> str:
    """A bare file name in backend/models wins; otherwise the name is passed through (Ultralytics
    downloads/finds stock weights such as yolov8s.pt itself)."""
    local = MODELS_DIR / name
    return str(local) if local.exists() else name


def load_engine(model: str) -> DetectionEngine:
    """Shared engine per model, so N cameras don't load N copies of the weights onto the GPU."""
    path = resolve_model_path(model)
    with _engines_lock:
        engine = _engines.get(path)
        if engine is None:
            engine = UltralyticsEngine(path)
            _engines[path] = engine
        return engine


def available_models() -> list[str]:
    """Choices for the Detection Settings dropdown: the default plus any .pt in backend/models."""
    names = {DEFAULT_MODEL}
    if MODELS_DIR.exists():
        names.update(p.name for p in MODELS_DIR.glob("*.pt") if not p.stem.endswith("-pose"))  # pose = analytics model
    return sorted(names)


def engine_info() -> Tuple[int, list[str]]:
    with _engines_lock:
        return len(_engines), list(_engines)
