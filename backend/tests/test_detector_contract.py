import numpy as np

from app.analytics import FrameContext
from app.config import CalibrationConfig, EngineConfig, Zone, ZoneRules
from app.vision_engine import VisionEngine

FRAME = np.zeros((540, 960, 3), np.uint8)
PERSON = ([100, 100, 140, 220], 0, 0.9)


class CountingDetector:
    name = "counting"
    event_types = ["test_event"]

    def __init__(self):
        self.seen, self.pruned_with = [], None

    def update(self, ctx: FrameContext):
        self.seen.append([t.track_id for t in ctx.tracks])
        if not ctx.tracks:
            return []
        t = ctx.tracks[0]
        return [{"type": "test_event", "zone_name": "", "track_id": t.track_id, "timestamp": ctx.ts,
                 "point": t.point, "key_track_ids": [t.track_id]}]

    def prune(self, live_track_ids):
        self.pruned_with = set(live_track_ids)


def make_engine(detectors=(), zones=()):
    config = EngineConfig(zones=list(zones), calibration=CalibrationConfig(), frame_size=(960, 540),
                          ignore_person_shadows=False)
    return VisionEngine(config, detectors=list(detectors))


def test_detector_receives_tracks_and_its_events_come_out(fake_engine):
    det = CountingDetector()
    engine = make_engine([det])
    fake_engine.next = [PERSON]
    events = []
    for i in range(3):
        _, ev = engine.process_frame(FRAME, ts=100.0 + i)
        events += ev
    assert det.seen[-1], "detector saw no tracks"
    assert any(e["type"] == "test_event" for e in events)
    assert engine.last_tracks[0].alerts == ["test_event"]  # key_track_ids -> drawn as a threat


def test_no_detectors_still_runs_zone_rules(fake_engine):
    zone = Zone(id="1", name="all", polygon=[[0, 0], [960, 0], [960, 540], [0, 540]],
                rules=ZoneRules(exclusion=True, applies_to=["person"]))
    engine = make_engine(zones=[zone])
    fake_engine.next = [PERSON]
    engine.process_frame(FRAME, ts=1.0)
    _, events = engine.process_frame(FRAME, ts=1.1)
    assert [e["type"] for e in events] == ["exclusion"]


def test_detectors_are_pruned_with_live_tracks(fake_engine):
    det = CountingDetector()
    engine = make_engine([det])
    fake_engine.next = [PERSON]
    engine.process_frame(FRAME, ts=0.0)
    engine.process_frame(FRAME, ts=0.1)
    fake_engine.next = []
    for i in range(100):  # long enough for the track to go stale and a prune pass to run
        engine.process_frame(FRAME, ts=60.0 + i)
    assert det.pruned_with == set()
