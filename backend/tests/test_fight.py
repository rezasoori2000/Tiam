"""Fight detector on synthetic keypoints. Calibration 0.02 m/px: 1.5 m close = 75 px. Person boxes
are 110 px tall, so the 1.8 body-heights/s limb threshold is ~200 px/s."""
from pathlib import Path

import numpy as np
import pytest

from app.analytics import FrameContext, TrackView
from app.analytics import pose as pose_mod
from app.analytics.fight import FightDetector
from app.config import CalibrationConfig, EngineConfig, Zone, ZoneRules
from app.vision_engine import VisionEngine

CAL = CalibrationConfig(meters_per_pixel=0.02)
FRAME = np.zeros((540, 960, 3), np.uint8)
STEP = 0.1  # 10 fps


def zone(fight=True, min_s=2.0):
    return Zone(id="1", name="Entrance", polygon=[[0, 0], [960, 0], [960, 540], [0, 540]],
                rules=ZoneRules(fight=fight, fight_min_seconds=min_s, applies_to=["person"]))


def keypoints(x, y, wrist_dx=0.0):
    """Standing person with feet at (x, y), 110 px tall; wrists pushed sideways by wrist_dx."""
    kp = np.zeros((17, 3))
    kp[:, 2] = 0.9
    kp[:, 0], kp[:, 1] = x, y - 55
    kp[9, :2] = (x - 15 + wrist_dx, y - 60)
    kp[10, :2] = (x + 15 + wrist_dx, y - 60)
    kp[15, :2] = (x - 8, y)
    kp[16, :2] = (x + 8, y)
    return kp


def person(tid, x, y=400, wrist_dx=0.0, lying=False):
    box = np.array([x - 55, y - 30, x + 55, y], float) if lying else np.array([x - 20, y - 110, x + 20, y], float)
    return TrackView(track_id=tid, class_name="person", kind="person", xyxy=box, point=(x, y),
                     speed_kmh=None, zone_hits=["1"], keypoints=keypoints(x, y, wrist_dx))


def run(det, frames, zones):
    out = []
    for ts, tracks in frames:
        out += det.update(FrameContext(camera_id=1, ts=ts, frame=FRAME, tracks=tracks, calibration=CAL, zones=zones))
    return out


def scuffle(seconds, gap_px=50, t0=0.0, walk_px_per_frame=0.0):
    """Two people gap_px apart, A's wrists swinging +-25 px a frame (~500 px/s)."""
    frames = []
    for i in range(int(seconds / STEP)):
        dx = 25.0 if i % 2 else -25.0
        shift = i * walk_px_per_frame
        frames.append((t0 + i * STEP, [person(1, 400 + shift, wrist_dx=dx), person(2, 400 + gap_px + shift)]))
    return frames


def test_sustained_strikes_fire_after_min_seconds():
    events = run(FightDetector(), scuffle(3.0), [zone(min_s=2.0)])
    assert events, "no fight detected"
    first = events[0]
    assert first["type"] == "fight" and first["subtype"] == "strikes"
    assert first["key_track_ids"] == [1, 2] and first["track_id"] == 1
    assert first["timestamp"] >= 2.0


def test_short_burst_does_not_fire():
    assert run(FightDetector(), scuffle(1.0), [zone(min_s=2.0)]) == []


def test_people_far_apart_do_not_fire():
    assert run(FightDetector(), scuffle(3.0, gap_px=150), [zone()]) == []  # 3 m apart


def test_walking_together_is_not_agitation():
    """Whole body (box + keypoints) moving fast: limb speed relative to the body is ~0."""
    frames = []
    for i in range(40):
        x = 200 + i * 30  # 300 px/s
        frames.append((i * STEP, [person(1, x), person(2, x + 50)]))
    assert run(FightDetector(), frames, [zone()]) == []


def test_zone_without_rule_is_ignored_and_asks_no_pose():
    det = FightDetector()
    ts, tracks = scuffle(0.1)[0]
    ctx = FrameContext(camera_id=1, ts=ts, frame=FRAME, tracks=tracks, calibration=CAL, zones=[zone(fight=False)])
    assert det.pose_requests(ctx) == set()
    assert run(det, scuffle(3.0), [zone(fight=False)]) == []


def test_pose_requested_only_for_close_people_in_zone():
    tracks = [person(1, 100), person(2, 140), person(3, 800)]
    ctx = FrameContext(camera_id=1, ts=0.0, frame=FRAME, tracks=tracks, calibration=CAL, zones=[zone()])
    assert FightDetector().pose_requests(ctx) == {1, 2}


def test_fall_during_scuffle_fires_before_min_seconds():
    frames = scuffle(0.8)
    t = frames[-1][0] + STEP
    frames.append((t, [person(1, 400, wrist_dx=25), person(2, 450, lying=True)]))
    events = run(FightDetector(), frames, [zone(min_s=5.0)])
    assert events and events[-1]["subtype"] == "fall" and events[-1]["fallen_track_id"] == 2


def test_vision_engine_runs_pose_only_when_asked(fake_engine, monkeypatch):
    calls = []

    class FakePose:
        def __init__(self, device):
            pass

        def run(self, frame, tracks):
            calls.append(sorted(t.track_id for t in tracks))
            return {t.track_id: keypoints(*t.point, wrist_dx=25.0 if len(calls) % 2 else -25.0) for t in tracks}

    monkeypatch.setattr(pose_mod, "PoseRunner", FakePose)
    config = EngineConfig(zones=[zone(min_s=1.0)], calibration=CAL, frame_size=(960, 540), ignore_person_shadows=False)
    engine = VisionEngine(config, detectors=[FightDetector()])
    fake_engine.next = [([380, 290, 420, 400], 0, 0.9), ([430, 290, 470, 400], 0, 0.9)]
    events = []
    for i in range(25):
        events += engine.process_frame(FRAME, ts=i * STEP)[1]
    assert calls and len(calls[-1]) == 2
    assert any(e["type"] == "fight" for e in events)
    assert all("fight" in t.alerts for t in engine.last_tracks)


@pytest.mark.skipif(not pose_mod.model_available(), reason="pose model not downloaded")
def test_pose_runner_on_real_image():
    import cv2
    import ultralytics

    img = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "zidane.jpg"))
    img = cv2.resize(img, (960, 540))
    # rough person boxes on the resized zidane.jpg (two men standing)
    tracks = [TrackView(track_id=1, class_name="person", kind="person", xyxy=np.array([80, 80, 860, 540], float),
                        point=(470, 540), speed_kmh=None, zone_hits=[])]
    out = pose_mod.PoseRunner(device="cpu").run(img, tracks)
    assert 1 in out and out[1].shape == (17, 3)
    assert (out[1][:, 0] >= 0).all() and (out[1][:, 0] <= 960).all()
