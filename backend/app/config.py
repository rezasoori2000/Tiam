"""Configuration models for the vision engine: zones, rules, and calibration."""
import datetime
from dataclasses import dataclass, field
from math import hypot
from typing import List, Optional, Tuple

Point = Tuple[float, float]


@dataclass
class ZoneRules:
    exclusion: bool = False
    speed_limit_kmh: Optional[float] = None
    # stop-sign-style compliance: a track must stay put (within
    # STOP_MAX_DRIFT_M of one spot) for at least stop_min_seconds at some point
    # while inside the zone, or a "failed_to_stop" incident fires when it
    # leaves (see vision_engine's _apply_rules; the drift is a measurement
    # tolerance for box jitter, not a policy choice, so not per zone).
    stop_required: bool = False
    stop_min_seconds: float = 1.0
    # car prowling (analytics/car_prowling.py): people in this zone going car to car / lingering /
    # crouching beside parked vehicles; alert once the score reaches prowling_min_vehicles.
    prowling: bool = False
    prowling_min_vehicles: float = 3.0
    # fight / assault (analytics/fight.py): two people close together with fast limb movement
    # for fight_min_seconds (or a charge / a fall between them).
    fight: bool = False
    fight_min_seconds: float = 2.0
    # object classes this zone's rules apply to, matched against detector class names
    applies_to: List[str] = field(default_factory=lambda: ["person"])
    # optional time-of-day window ("HH:MM") these rules are enforced in; a
    # violation detected outside this window is ignored. Supports overnight
    # windows (e.g. 22:00 -> 06:00) by wrapping past midnight.
    time_restriction_enabled: bool = False
    from_time: Optional[str] = None
    to_time: Optional[str] = None

    def is_active_at(self, ts: float) -> bool:
        """Whether this zone's rules should be enforced at epoch time `ts`."""
        if not self.time_restriction_enabled or not self.from_time or not self.to_time:
            return True
        now = datetime.datetime.fromtimestamp(ts).time()
        start = datetime.time.fromisoformat(self.from_time)
        end = datetime.time.fromisoformat(self.to_time)
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end  # window wraps past midnight


@dataclass
class Zone:
    id: str
    name: str
    polygon: List[Point]
    rules: ZoneRules
    color_bgr: Tuple[int, int, int] = (0, 200, 255)


@dataclass
class CalibrationConfig:
    # meters represented by one pixel at the calibrated reference plane.
    # Derived in a later stage from a known real-world reference distance;
    # 0.02 is a placeholder (~5cm/px) until per-camera calibration is run.
    meters_per_pixel: float = 0.02
    # 4-point calibration: 3x3 image -> ground-plane metres mapping (row-major,
    # scaled so w > 0 on the ground). Handles perspective, so a far-away metre
    # counts the same as a near one. None = meters_per_pixel everywhere.
    homography: Optional[Tuple[Tuple[float, float, float], ...]] = None

    def _to_ground(self, p: Point) -> Optional[Point]:
        (a, b, c), (d, e, f), (g, h, i) = self.homography
        w = g * p[0] + h * p[1] + i
        if w <= 1e-9:  # at/above the horizon: not on the ground plane
            return None
        return (a * p[0] + b * p[1] + c) / w, (d * p[0] + e * p[1] + f) / w

    def ground_points(self, points: List[Point]) -> List[Point]:
        """Image points -> ground-plane positions in metres. All points use
        the same mapping: if any can't be mapped (above the horizon), all
        fall back to the flat meters_per_pixel scale."""
        if self.homography is not None:
            ground = [self._to_ground(p) for p in points]
            if all(g is not None for g in ground):
                return ground
        m = self.meters_per_pixel
        return [(x * m, y * m) for x, y in points]

    def distance_m(self, p: Point, q: Point) -> float:
        """Real-world distance between two ground points (image pixels)."""
        (ax, ay), (bx, by) = self.ground_points([p, q])
        return hypot(ax - bx, ay - by)


@dataclass
class EngineConfig:
    # DB camera this engine instance is bound to; used by refresh_from_db to
    # scope which zones/calibration rows to load. None outside multi-camera use.
    camera_id: Optional[int] = None
    zones: List[Zone] = field(default_factory=list)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    detector_model_path: str = "yolov8s.pt"
    # Floor passed to the main detector's own predict() call (and used to
    # derive the ByteTrack activation threshold below) -- normally set by
    # whoever builds this config to min(person_confidence, car_confidence,
    # truck_confidence) so nothing any per-class threshold might still want
    # is prematurely dropped by the model call itself.
    detection_conf: float = 0.2
    # Per-class confidence floors applied *after* the main detector runs
    # (post-filter on detections.confidence), independent of detection_conf
    # above -- lets e.g. "truck" be tightened to cut down on static box/
    # container false positives without also raising the floor for "person".
    # bus/motorcycle share car_confidence (not separately exposed/tuned).
    person_confidence: float = 0.2
    car_confidence: float = 0.2
    truck_confidence: float = 0.2
    # IoU threshold for suppressing duplicate boxes on the same vehicle --
    # e.g. the detector calling one vehicle both "car" and "truck", or
    # emitting two overlapping boxes for it at a low detection_conf. Applied
    # class-agnostic-ly, but only within the "vehicle" kind (never
    # against/between person boxes).
    vehicle_nms_iou_threshold: float = 0.5
    # Second suppression pass alongside the IoU-based NMS above: catches
    # duplicate boxes on the *same* vehicle that have low IoU because the
    # boxes are very different sizes (e.g. one box hugging just a truck's
    # cab, another around the whole truck). Measured as
    # intersection_area / smaller_box_area rather than IoU, so it fires
    # on that big/small overlap pattern that IoU alone misses.
    vehicle_containment_threshold: float = 0.7
    device: str = "cuda"
    frame_size: Tuple[int, int] = (640, 640)
    # YOLO inference size (long side, px). Ultralytics defaults to 640, which
    # shrinks our 960x540 frame by a third before detection and loses small /
    # distant people. 960 runs at the frame's native resolution.
    detector_imgsz: int = 960
    # speed is fitted over this many seconds of a track's ground points
    # (whatever the frame rate) -- see VisionEngine._speed_kmh
    # (1.5 s: on live data 1.0 s still let box jumps through as spikes; the
    # cost is speeding alerts ~0.5 s later)
    speed_window_s: float = 1.5
    # A vehicle must be seen inside a stop-required zone on at least this many
    # frames before leaving without stopping counts as "failed_to_stop", so a
    # tracker glitch or clipping a zone corner doesn't. Set from Detection
    # Settings' "Minimum confirmations".
    stop_min_frames_in_zone: int = 1
    # object classes treated as "vehicle" for speed/stop rules
    vehicle_class_names: List[str] = field(
        default_factory=lambda: ["car", "truck", "bus", "motorcycle"]
    )
    # Minimum height/width ratio a "person" detection must have to be kept;
    # boxes below this are dropped as implausible clutter. From an elevated
    # camera angle, a pair of wheelie bins side by side forms a roughly
    # square silhouette that the generic COCO detector sometimes calls
    # "person" at low confidence -- a standing or crouching person's box is
    # reliably taller than it is wide, so this catches that case without
    # needing a retrained model. Set to 0 to disable.
    person_min_aspect_ratio: float = 1.2
    # Drop a "person" box touching another person when it holds nothing but
    # floor and darkened floor -- that person's shadow (see
    # VisionEngine._filter_person_shadows).
    ignore_person_shadows: bool = True
    # When set to one of this camera's zone ids, the live frame is masked to
    # that zone's polygon and cropped to its bounding box *before* the
    # detector ever runs -- nothing outside it is detected, and the stream
    # only shows that area, rather than detecting over the full frame and
    # filtering alerts by zone membership afterwards like every other zone
    # rule. Falls back to normal full-frame behaviour if the id doesn't
    # match any currently-loaded zone (e.g. the zone was deleted). None
    # (default) = normal full-frame behaviour.
    restrict_to_zone_id: Optional[str] = None
