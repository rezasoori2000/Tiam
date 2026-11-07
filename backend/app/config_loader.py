"""Converts DB rows (Zone, Calibration) into the dataclasses vision_engine
expects, without touching detector/device/frame_size settings."""
from typing import List

import cv2
import numpy as np
from sqlalchemy.orm import Session

from . import crud
from .config import CalibrationConfig, Zone, ZoneRules

ZONE_COLORS = [
    (0, 0, 255), (0, 200, 255), (255, 0, 200), (0, 255, 150), (255, 150, 0),
]


_APPLIES_TO_MAP = {
    "person": ["person"],
    "vehicle": ["vehicle"],
    "both": ["person", "vehicle"],
}


def load_zones_from_db(db: Session, camera_id: int) -> List[Zone]:
    zones = []
    for i, row in enumerate(crud.get_zones(db, camera_id=camera_id)):
        applies_to = _APPLIES_TO_MAP.get(row.applies_to, ["person"])
        zones.append(
            Zone(
                id=str(row.id),
                name=row.name,
                polygon=row.polygon_points,
                rules=ZoneRules(
                    exclusion=row.rule_exclusion,
                    speed_limit_kmh=row.max_speed_kmh,
                    stop_required=row.rule_stop_required,
                    stop_min_seconds=row.stop_min_seconds,
                    applies_to=applies_to,
                    time_restriction_enabled=row.time_restriction_enabled,
                    from_time=row.from_time,
                    to_time=row.to_time,
                ),
                color_bgr=ZONE_COLORS[i % len(ZONE_COLORS)],
            )
        )
    return zones


def load_calibration_from_db(
    db: Session, camera_id: int, default: CalibrationConfig
) -> CalibrationConfig:
    active = crud.get_active_calibration(db, camera_id=camera_id)
    if active is None or active.pixels_per_meter <= 0:
        return default
    homography = None
    if len(active.line_points) == 4 and active.real_world_width_m:
        homography = ground_homography(
            active.line_points, active.real_world_meters, active.real_world_width_m
        )
    return CalibrationConfig(meters_per_pixel=1.0 / active.pixels_per_meter, homography=homography)


def ground_homography(corners, side_12_m: float, side_23_m: float):
    """Image -> ground-metres mapping from the 4 corners of a real rectangle
    (clicked in order). None if the corners are degenerate."""
    src = np.float32(corners)
    dst = np.float32([[0, 0], [side_12_m, 0], [side_12_m, side_23_m], [0, side_23_m]])
    try:
        h = cv2.getPerspectiveTransform(src, dst)
    except cv2.error:
        return None
    # collinear/degenerate corners give a (near-)singular matrix, not an error
    if not np.all(np.isfinite(h)) or abs(np.linalg.det(h)) < 1e-12:
        return None
    # projective scale is arbitrary; fix its sign so w > 0 on the rectangle
    # (CalibrationConfig._to_ground treats w <= 0 as above the horizon)
    if h[2] @ np.array([*src[0], 1.0]) < 0:
        h = -h
    return tuple(tuple(float(v) for v in row) for row in h)
