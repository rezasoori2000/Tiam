"""Tests run without GPU or database: the detection engine is a fake (see fake_engine)."""
import sys
from pathlib import Path

import numpy as np
import pytest
import supervision as sv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeEngine:
    """DetectionEngine double: returns whatever boxes the test queued for the next frame."""
    class_names = {0: "person", 2: "car", 7: "truck"}

    def __init__(self):
        self.next = []  # list of (xyxy, class_id, confidence)

    def predict(self, frame, conf, imgsz, device):
        if not self.next:
            return sv.Detections.empty()
        xyxy, cls, confs = zip(*self.next)
        return sv.Detections(xyxy=np.array(xyxy, float), class_id=np.array(cls), confidence=np.array(confs, float))


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine()
    import app.vision_engine as ve
    monkeypatch.setattr(ve, "load_engine", lambda model: engine)
    return engine
