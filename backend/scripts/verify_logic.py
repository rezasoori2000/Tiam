"""Direct unit-style checks for the core algorithms in VisionEngine, since the
synthetic smoke-test clip has no real people/vehicles for YOLO to detect.
Validates: speed formula, zone point-in-polygon, exclusion rule, shadow
filter, time windows, vehicle dedup.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from collections import deque as _deque

from app.config import CalibrationConfig, EngineConfig, Zone, ZoneRules
from app.vision_engine import VisionEngine, _TrackInfo

failures = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        failures.append(name)


config = EngineConfig(
    zones=[
        Zone(
            id="z1", name="test-zone",
            polygon=[[100, 100], [300, 100], [300, 300], [100, 300]],
            rules=ZoneRules(exclusion=True),
        ),
    ],
    calibration=CalibrationConfig(meters_per_pixel=0.02),
    device="cuda",
)
engine = VisionEngine(config)

# 1. Speed formula: 150px over 1.5s at 0.02 m/px = 2m/s = 7.2 km/h
# (_speed_kmh needs >= 3 samples spanning 70% of speed_window_s)
history = [(0.0, 0.0, 0.0), (75.0, 0.0, 0.75), (150.0, 0.0, 1.5)]
from collections import deque
speed = engine._speed_kmh(deque(history))
check(f"speed calc: 150px/1.5s @0.02m/px -> 7.2km/h (got {speed})", speed is not None and abs(speed - 7.2) < 0.01)

# 2. Zone point-in-polygon
poly = engine.zone_polygons["z1"]
inside = cv2.pointPolygonTest(poly, (200.0, 200.0), False) >= 0
outside = cv2.pointPolygonTest(poly, (500.0, 500.0), False) >= 0
check("point (200,200) is inside test-zone polygon", inside)
check("point (500,500) is outside test-zone polygon", not outside)

# 3c. Shadow filter: a "person" box that's only darkened floor, touching a
# real person, is dropped; real people (lone, side by side, bright clothing) are kept.
import supervision as sv


def hsv_px(h, s, v):
    return cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]


FLOOR, SHADOW = hsv_px(17, 104, 208), hsv_px(17, 104, 115)  # site floor + its shadow


def draw_person(img, x, top=(255, 255, 255)):
    img[100:115, x + 8:x + 22] = hsv_px(10, 90, 170)  # head (skin)
    img[115:150, x + 4:x + 26] = top  # shirt / vest
    img[150:190, x + 6:x + 24] = (40, 40, 40)  # dark trousers


def draw_shadow(img, x):
    img[105:190, x + 6:x + 24] = SHADOW


def person_dets(*xs):
    person_id = next(cid for cid, name in engine.class_names.items() if name == "person")
    return sv.Detections(
        xyxy=np.array([[x, 98, x + 30, 192] for x in xs], dtype=np.float32),
        class_id=np.full(len(xs), person_id), confidence=np.full(len(xs), 0.5, dtype=np.float32),
    )


def kept_xs(img, *xs):
    return sorted(int(b[0]) for b in engine._filter_person_shadows(person_dets(*xs), img).xyxy)


scene = np.full((300, 600, 3), FLOOR, dtype=np.uint8)
draw_person(scene, 100)
draw_shadow(scene, 130)
check("shadow next to a person is dropped, person kept", kept_xs(scene, 100, 130) == [100])
scene = np.full((300, 600, 3), FLOOR, dtype=np.uint8)
draw_person(scene, 100, top=hsv_px(40, 120, 200))  # hi-vis vest
draw_shadow(scene, 130)
check("hi-vis worker kept, their shadow dropped", kept_xs(scene, 100, 130) == [100])
scene = np.full((300, 600, 3), FLOOR, dtype=np.uint8)
draw_person(scene, 100)
draw_person(scene, 130, top=(60, 60, 60))
check("two people side by side are both kept", kept_xs(scene, 100, 130) == [100, 130])
scene = np.full((300, 600, 3), FLOOR, dtype=np.uint8)
draw_person(scene, 100)
draw_shadow(scene, 400)  # shadow-like figure with no person touching it
check("shadow-like box not touching a person is kept", kept_xs(scene, 100, 400) == [100, 400])
engine.config.ignore_person_shadows = False
scene = np.full((300, 600, 3), FLOOR, dtype=np.uint8)
draw_person(scene, 100)
draw_shadow(scene, 130)
check("shadow filter off keeps everything", kept_xs(scene, 100, 130) == [100, 130])
engine.config.ignore_person_shadows = True

# 4. Exclusion rule via _apply_rules with a synthetic track (no detector).
def make_track(track_id, x, y, zone_hits):
    return _TrackInfo(
        track_id=track_id, xyxy=np.array([x - 5, y - 5, x + 5, y + 5], dtype=np.float32),
        class_name="person", kind="person", point=(float(x), float(y)), speed_kmh=None,
        history=_deque(maxlen=1), zone_hits=zone_hits,
    )


inside_events = engine._apply_rules([make_track(201, 200, 200, ["z1"])], 0.0)
check("person inside exclusion zone fires one exclusion event",
      [e["type"] for e in inside_events] == ["exclusion"])
check("person outside every zone fires nothing", engine._apply_rules([make_track(202, 500, 500, [])], 0.0) == [])

# 6. Time-restricted zone: violation only fires inside the from/to window.
import datetime

restricted_zone_rules = ZoneRules(
    exclusion=True, time_restriction_enabled=True, from_time="09:00", to_time="17:00",
)
in_window_ts = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
out_of_window_ts = datetime.datetime.now().replace(hour=20, minute=0, second=0, microsecond=0).timestamp()
check("time-restricted rule active at 12:00 within 09:00-17:00", restricted_zone_rules.is_active_at(in_window_ts))
check("time-restricted rule inactive at 20:00 outside 09:00-17:00", not restricted_zone_rules.is_active_at(out_of_window_ts))

overnight_zone_rules = ZoneRules(
    exclusion=True, time_restriction_enabled=True, from_time="22:00", to_time="06:00",
)
late_ts = datetime.datetime.now().replace(hour=23, minute=0, second=0, microsecond=0).timestamp()
midday_ts = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
check("overnight window (22:00-06:00) active at 23:00", overnight_zone_rules.is_active_at(late_ts))
check("overnight window (22:00-06:00) inactive at 12:00", not overnight_zone_rules.is_active_at(midday_ts))

# 7. Vehicle dedup: one vehicle boxed as both "car" and "truck" -> one box;
# two separate vehicles both stay.
import supervision as sv

coco_car = next(cid for cid, name in engine.class_names.items() if name == "car")
coco_truck = next(cid for cid, name in engine.class_names.items() if name == "truck")


def dedup_names(boxes, class_ids, confs):
    kept = engine._dedup_vehicle_detections(sv.Detections(
        xyxy=np.array(boxes, dtype=float), class_id=np.array(class_ids),
        confidence=np.array(confs, dtype=float),
    ))
    return sorted(engine._class_name(int(c)) for c in kept.class_id)


check(
    "same vehicle as car + truck: lower-confidence box dropped",
    dedup_names([[100, 100, 200, 300], [105, 110, 200, 290]],
                [coco_truck, coco_car], [0.83, 0.5]) == ["truck"],
)
check(
    "separate car and truck: both kept",
    dedup_names([[0, 0, 300, 200], [350, 100, 450, 250]],
                [coco_truck, coco_car], [0.9, 0.6]) == ["car", "truck"],
)

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("All checks passed.")
