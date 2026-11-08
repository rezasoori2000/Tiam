"""Car prowling detector on synthetic scenes. Calibration 0.02 m/px: 1.2 m visit radius = 60 px,
2 m 'same car' = 100 px, 1 m park drift = 50 px."""
import numpy as np

from app.analytics import FrameContext, TrackView
from app.analytics.car_prowling import CarProwlingDetector
from app.config import CalibrationConfig, Zone, ZoneRules

CAL = CalibrationConfig(meters_per_pixel=0.02)
FRAME = np.zeros((540, 960, 3), np.uint8)
CARS = {101: (100, 300), 102: (300, 300), 103: (500, 300), 104: (700, 300)}  # id -> (left x, bottom y)


def zone(min_vehicles=3.0, **kw):
    return Zone(id="1", name="Bays", polygon=[[0, 0], [960, 0], [960, 540], [0, 540]],
                rules=ZoneRules(prowling=True, prowling_min_vehicles=min_vehicles, applies_to=["person"], **kw))


def car(tid, moving_offset=0.0):
    x, y = CARS[tid]
    x += moving_offset
    return TrackView(track_id=tid, class_name="car", kind="vehicle", xyxy=np.array([x, y - 80, x + 160, y], float),
                     point=(x + 80, y), speed_kmh=None, zone_hits=["1"])


def person(x, y=320, height=110, tid=7, in_zone=True):
    return TrackView(track_id=tid, class_name="person", kind="person", xyxy=np.array([x - 15, y - height, x + 15, y], float),
                     point=(x, y), speed_kmh=None, zone_hits=["1"] if in_zone else [])


def run(det, frames, zones):
    """frames: list of (ts, tracks). Returns all events."""
    out = []
    for ts, tracks in frames:
        out += det.update(FrameContext(camera_id=1, ts=ts, frame=FRAME, tracks=tracks, calibration=CAL, zones=zones))
    return out


def parked_cars(t0=0.0, seconds=35, step=1.0, cars=(101, 102, 103, 104)):
    """Cars sitting still long enough to count as parked."""
    return [(t0 + i * step, [car(c) for c in cars]) for i in range(int(seconds / step))]


def walk_past(cars_to_visit, start, dwell=4.0, height=110, step=0.5, cars=(101, 102, 103, 104)):
    """Person stops beside each car in turn for `dwell` seconds (feet just below the car's box)."""
    frames, ts = [], start
    for c in cars_to_visit:
        x = CARS[c][0] + 80
        for _ in range(int(dwell / step)):
            frames.append((ts, [car(k) for k in cars] + [person(x, height=height)]))
            ts += step
    return frames, ts


def test_going_car_to_car_fires():
    det, z = CarProwlingDetector(), [zone()]
    frames = parked_cars()
    visits, _ = walk_past([101, 102, 103], start=40)
    events = run(det, frames + visits, z)
    assert events and events[-1]["type"] == "car_prowling"
    ev = events[-1]
    assert ev["vehicles_visited"] == 3 and ev["track_id"] == 7 and ev["key_track_ids"] == [7]
    assert ev["zone_id"] == "1" and ev["threshold"] == 3.0


def test_own_car_with_long_loading_does_not_fire():
    det, z = CarProwlingDetector(), [zone()]
    visits, _ = walk_past([101], start=40, dwell=60)  # one car, 60 s: 1 + 0.5 = 1.5
    assert run(det, parked_cars() + visits, z) == []


def test_crouching_beside_cars_adds_up():
    det, z = CarProwlingDetector(), [zone()]
    # standing first (sets the person's normal height), then crouched at two cars: 2 cars + 2 crouches = 4
    standing = [(40 + i * 0.5, [car(k) for k in CARS] + [person(900, height=110)]) for i in range(6)]
    visits, _ = walk_past([101, 102], start=43, dwell=5, height=50)
    events = run(det, parked_cars() + standing + visits, z)
    assert events and events[-1]["crouch_visits"] == 2


def test_moving_cars_are_not_parked():
    det, z = CarProwlingDetector(), [zone()]
    frames = [(i * 1.0, [car(c, moving_offset=i * 30.0) for c in (101,)]) for i in range(40)]
    assert run(det, frames, z) == []
    assert det._update_vehicles(FrameContext(1, 41.0, FRAME, [car(101, 1230.0)], CAL, z)) == []


def test_person_outside_zone_and_time_window_ignored():
    frames = parked_cars()
    visits, _ = walk_past([101, 102, 103], start=40)
    det = CarProwlingDetector()
    assert run(det, frames + [(ts, [t if t.kind == "vehicle" else person(t.point[0], in_zone=False) for t in tr])
                              for ts, tr in visits], [zone()]) == []
    closed = zone(time_restriction_enabled=True, from_time="00:00", to_time="00:01")
    det = CarProwlingDetector()
    assert run(det, frames + visits, [closed]) == []


def test_no_prowling_zone_is_a_noop():
    det = CarProwlingDetector()
    plain = Zone(id="1", name="x", polygon=[[0, 0], [9, 0], [9, 9]], rules=ZoneRules(exclusion=True))
    frames = parked_cars()
    visits, _ = walk_past([101, 102, 103], start=40)
    assert run(det, frames + visits, [plain]) == [] and det._vehicles == {}


def test_through_vision_engine(fake_engine):
    """Fake detector boxes -> ByteTrack -> zone membership -> CarProwlingDetector -> event."""
    from app.analytics import default_detectors
    from app.config import EngineConfig
    from app.vision_engine import VisionEngine

    engine = VisionEngine(EngineConfig(zones=[zone()], calibration=CAL, frame_size=(960, 540),
                                       ignore_person_shadows=False), detectors=default_detectors())
    car_boxes = [([x, y - 80, x + 160, y], 2, 0.9) for x, y in CARS.values()]
    ts, events = 0.0, []
    for _ in range(70):  # 35 s: cars become parked
        fake_engine.next = car_boxes
        engine.process_frame(FRAME, ts)
        ts += 0.5
    x = CARS[101][0] + 80
    for cid in (101, 102, 103):  # person walks (1 m/s) to each car and stops beside it for 4 s
        target = CARS[cid][0] + 80
        while abs(x - target) > 1:
            x += max(-25, min(25, target - x))
            fake_engine.next = car_boxes + [([x - 15, 210, x + 15, 320], 0, 0.9)]
            events += engine.process_frame(FRAME, ts)[1]
            ts += 0.5
        for _ in range(8):
            fake_engine.next = car_boxes + [([x - 15, 210, x + 15, 320], 0, 0.9)]
            events += engine.process_frame(FRAME, ts)[1]
            ts += 0.5
    prowl = [e for e in events if e["type"] == "car_prowling"]
    assert prowl and prowl[-1]["vehicles_visited"] == 3
    person = next(t for t in engine.last_tracks if t.kind == "person")
    assert "car_prowling" in person.alerts  # drawn red on the stream


def test_reacquired_car_counts_once_and_prune():
    det, z = CarProwlingDetector(), [zone(min_vehicles=2)]
    frames = parked_cars()
    visits, ts = walk_past([101], start=40)
    # car 101 re-acquired as id 201 at the same spot, parked long enough again, visited again
    CARS[201] = CARS[101]
    try:
        again = [(ts + 1 + i, [car(201), car(102)]) for i in range(32)]
        visits2, _ = walk_past([201], start=ts + 34, cars=(201, 102))
        events = run(det, frames + visits + again + visits2, z)
    finally:
        del CARS[201]
    assert events == []  # 2 visits but the same car -> 1 vehicle (+0) < 2
    det.prune({7})
    assert set(det._people) == {7} and det._vehicles == {}


def test_person_hidden_then_new_track_id_keeps_visits():
    """Crouching behind a car loses the track; a new id nearby inherits the visits."""
    det, z = CarProwlingDetector(), [zone()]
    frames = parked_cars()
    v1, ts = walk_past([101, 102], start=40)            # track 7 visits two cars
    gap = [(ts + i * 0.5, [car(k) for k in CARS]) for i in range(6)]  # hidden for 3 s
    ts += 3.0
    x = CARS[103][0] + 80                                # reappears 4 m away at the third car, new id 8
    v3 = [(ts + i * 0.5, [car(k) for k in CARS] + [person(x, tid=8)]) for i in range(8)]
    events = run(det, frames + v1 + gap + v3, z)
    assert events and events[-1]["track_id"] == 8 and events[-1]["vehicles_visited"] == 3


def test_far_away_new_person_is_not_merged():
    det, z = CarProwlingDetector(), [zone()]
    frames = parked_cars()
    v1, ts = walk_past([101, 102], start=40)
    x = CARS[104][0] + 80  # 8 m away, only 0.5 s later: a different person
    v2 = [(ts + i * 0.5, [car(k) for k in CARS] + [person(x, tid=9)]) for i in range(8)]
    assert run(det, frames + v1 + v2, z) == []
