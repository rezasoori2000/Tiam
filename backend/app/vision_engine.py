"""Per-camera detection pipeline.

Per frame: detection engine -> filters -> ByteTrack -> zone rules (exclusion/speed/stop) +
analytics detectors -> annotated frame + list of candidate events.
"""
from __future__ import annotations

import logging
import time
import warnings
from collections import defaultdict, deque
from dataclasses import dataclass, field
from math import hypot
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np
import supervision as sv
from sqlalchemy.orm import Session
from . import config_loader
from .analytics import CandidateEvent, Detector, FrameContext, TrackView
from .detection_engine import load_engine
from .config import EngineConfig, Zone

logger = logging.getLogger(__name__)

TrackHistory = Deque[Tuple[float, float, float]]  # (x, y, timestamp)

# A track not seen for this long is considered gone; its history is evicted
# on the next prune pass rather than kept forever (ByteTrack ids only ever
# increase, so an unbounded dict would otherwise leak for the life of the
# worker thread).
STALE_TRACK_TIMEOUT_S = 30.0
PRUNE_INTERVAL_FRAMES = 100

# Detection boxes (BGR) -- the frontend's --accent #f59e0b and --critical #ff4d3d.
BOX_NORMAL = (11, 158, 245)
BOX_THREAT = (61, 77, 255)

# Stop-required zones: a vehicle counts as stopped once its ground point stays
# within this distance of one spot for the zone's stop_min_seconds. Position-
# based rather than "speed under 2 km/h on every frame", where one
# jittery box reset the timer and parked cars got "failed_to_stop".
STOP_MAX_DRIFT_M = 0.5
# Speed is only reported once a track's samples span this fraction of
# speed_window_s (and there are at least SPEED_MIN_SAMPLES of them) -- a
# brand-new track's first frames are mostly box jitter.
SPEED_MIN_SPAN_FRACTION = 0.7
SPEED_MIN_SAMPLES = 3
# Upper bound on samples kept per track (old ones are trimmed by time anyway).
TRACK_HISTORY_MAXLEN = 64

# Shadow filter (`_filter_person_shadows`): a "person" box touching another
# person is that person's shadow if almost nothing in it differs from the
# floor around it, or a darkened copy of that floor. Measured on site: shadow
# box 2% "other" pixels, real person 22% (skin, hair, clothes, vest).
SHADOW_RING_FRACTION = 0.25  # floor sample ring, as a fraction of the box's width/height
SHADOW_HUE_TOLERANCE = 12  # OpenCV hue units (0-180)
SHADOW_GREY_MAX_SATURATION = 40  # below this a floor's hue is just noise
SHADOW_DARKEN_RANGE = (0.3, 0.85)  # shadow brightness / floor; darker is hair or black clothing
SHADOW_FLOOR_RANGE = (0.85, 1.15)
SHADOW_MAX_OTHER_FRACTION = 0.08
SHADOW_MIN_SHADOW_FRACTION = 0.15
SHADOW_TOUCH_MARGIN = 0.1  # boxes this fraction of their height apart still "touch"



def _compare_to_floor(hsv: np.ndarray, floor: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """(mask of pixels the floor's colour, brightness / floor brightness) for
    int16 HSV pixels against a floor's median HSV. On a grey floor
    (saturation below SHADOW_GREY_MAX_SATURATION) hue is noise, so "same
    colour" just means grey too."""
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    floor_h, floor_s, floor_v = (float(c) for c in floor)
    if floor_s < SHADOW_GREY_MAX_SATURATION:
        same_colour = s < SHADOW_GREY_MAX_SATURATION
    else:
        dh = np.abs(h - floor_h)
        same_colour = np.minimum(dh, 180 - dh) <= SHADOW_HUE_TOLERANCE
    return same_colour, v / max(floor_v, 1.0)


@dataclass
class _TrackInfo:
    track_id: int
    xyxy: np.ndarray
    class_name: str
    kind: str
    point: Tuple[float, float]
    speed_kmh: Optional[float]
    history: TrackHistory
    zone_hits: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    confidence: Optional[float] = None


# Pose (~45 ms on the laptop RTX 3050) runs only while a detector asks (fight: two people close in a
# fight zone). Every frame: at a live ~6 fps, every 2nd frame missed the punches in a real fight clip.
POSE_EVERY_N_FRAMES = 1


class VisionEngine:
    def __init__(self, config: EngineConfig, detectors: Optional[List[Detector]] = None):
        self.config = config

        # Shared per model across cameras (detection_engine.load_engine); swappable engine, ADR 0007.
        self.engine = load_engine(config.detector_model_path)
        self.class_names: Dict[int, str] = dict(self.engine.class_names)
        # Analytics detectors (app/analytics), run after the built-in zone rules.
        self.detectors: List[Detector] = list(detectors or [])
        self._pose = None  # PoseRunner, created the first time a detector asks for keypoints
        self._pose_tick = 0

        with warnings.catch_warnings():
            # supervision 0.30 flags ByteTrack as deprecated (removal in 0.31)
            # with no replacement class shipped yet; revisit when it lands.
            warnings.simplefilter("ignore", FutureWarning)
            # ByteTrack only spawns a *new* track for a detection scoring at
            # least `det_thresh`, which it sets to
            # track_activation_threshold + 0.1 (0.35 with the sv default of
            # 0.25) -- regardless of the confidence floor already applied by
            # the detector's own `conf=` filter. With detection_conf=0.2,
            # any person detected at 0.2-0.35 confidence (common for
            # distant/partially-occluded people) passed the detector but was
            # then silently dropped every frame since it could never become
            # a track, and `process_frame` skips untracked detections
            # entirely. Lowering track_activation_threshold so det_thresh
            # lands at the detector's own conf floor means anything the
            # detector reports is actually eligible to be tracked.
            self.tracker = sv.ByteTrack(
                track_activation_threshold=max(0.05, config.detection_conf - 0.1),
                # Default is 30 frames -- only ~1.7s at our ~18fps -- after
                # which a briefly-occluded person (behind a car, in
                # shadow) comes back under a new id and gets a duplicate
                # event. Hold lost tracks ~5s instead.
                lost_track_buffer=90,
            )

        self.zone_polygons: Dict[str, np.ndarray] = {
            zone.id: np.array(zone.polygon, dtype=np.int32) for zone in config.zones
        }
        # Populated by _recompute_restriction() below whenever
        # config.restrict_to_zone_id names a currently-loaded zone: the crop
        # offset/size (in full-frame coordinates) used to mask+crop just the
        # detector's input -- detections are shifted back to full-frame
        # coordinates immediately after, so zone polygons/drawing/output
        # never need a separate crop-space version (see process_frame).
        self._restrict_offset: Optional[Tuple[int, int]] = None
        self._restricted_frame_size: Optional[Tuple[int, int]] = None
        self._recompute_restriction()

        self.track_history: Dict[int, TrackHistory] = defaultdict(
            lambda: deque(maxlen=TRACK_HISTORY_MAXLEN)
        )
        self._track_last_seen: Dict[int, float] = {}
        self._frames_since_prune = 0
        # Snapshot of the current frame's tracks (kind/class_name/point),
        # for camera_manager to read after process_frame() returns -- used
        # to accumulate the Usage Heatmap's position counts without vision_engine
        # itself needing any DB access.
        self.last_tracks: List[_TrackInfo] = []

        # track_id -> zone_id -> {"anchor": (x, y)|None, "anchor_since": ts,
        # "satisfied": bool, "frames": int} for stop-required zones (see
        # _apply_rules) -- whether this track ever stayed within
        # STOP_MAX_DRIFT_M of one spot for `stop_min_seconds` while inside
        # that zone, checked at the moment it leaves.
        self._stop_progress: Dict[int, Dict[str, dict]] = {}
        # track_id -> zone ids it was inside as of the previous frame, so a
        # zone-exit (present last frame, absent this frame) can be detected --
        # zone_hits itself is a fully memoryless per-frame recomputation.
        self._track_last_zone_hits: Dict[int, List[str]] = {}

    # ------------------------------------------------------------------ utils

    def _class_name(self, class_id: int) -> str:
        return self.class_names.get(class_id, str(class_id))

    def _object_kind(self, class_name: str) -> str:
        if class_name == "person":
            return "person"
        if class_name in self.config.vehicle_class_names:
            return "vehicle"
        return "other"

    @staticmethod
    def _ground_point(xyxy: np.ndarray) -> Tuple[float, float]:
        x1, y1, x2, y2 = xyxy
        return float((x1 + x2) / 2), float(y2)

    def _speed_kmh(self, history: TrackHistory) -> Optional[float]:
        """Theil-Sen velocity (median of the velocities between every pair of
        samples) over the last speed_window_s of ground points, in metres via
        the calibration. A median, not a least-squares fit: when the box jumps
        (a differently-sized box, or catching up after a repeated frame) only
        a few pairs are off, so the jump doesn't drag the speed up. Live data:
        a vehicle reading ~4 km/h peaked at 6.9 with the old fit, 4.4 with
        this + 1.5 s window."""
        if len(history) < SPEED_MIN_SAMPLES:
            return None
        if history[-1][2] - history[0][2] < SPEED_MIN_SPAN_FRACTION * self.config.speed_window_s:
            return None
        t = np.array([h[2] for h in history])
        g = np.array(self.config.calibration.ground_points([(h[0], h[1]) for h in history]))
        i, j = np.triu_indices(len(t), k=1)
        dt = t[j] - t[i]
        ok = dt > 1e-6
        v = (g[j][ok] - g[i][ok]) / dt[ok][:, None]  # metres per second, per pair
        if not len(v):
            return None
        vx, vy = np.median(v, axis=0)
        return float(hypot(vx, vy)) * 3.6


    def _prune_stale_tracks(self, now: float) -> None:
        """Evicts history for tracks not seen in a while. ByteTrack ids only
        ever increase for the life of a worker, so without this,
        track_history/_track_last_seen would grow forever."""
        stale_ids = [
            track_id for track_id, last_seen in self._track_last_seen.items()
            if now - last_seen > STALE_TRACK_TIMEOUT_S
        ]
        for track_id in stale_ids:
            self.track_history.pop(track_id, None)
            self._track_last_seen.pop(track_id, None)
            self._stop_progress.pop(track_id, None)
            self._track_last_zone_hits.pop(track_id, None)
        if stale_ids:
            live = set(self._track_last_seen)
            for detector in self.detectors:
                detector.prune(live)








    # -------------------------------------------------------------- DB config

    def refresh_from_db(self, db: Session) -> None:
        """Reloads zones + active calibration from the DB without reloading
        the (expensive) detector model or resetting active tracks."""
        if self.config.camera_id is None:
            raise ValueError("refresh_from_db requires EngineConfig.camera_id to be set")
        self.config.zones = config_loader.load_zones_from_db(db, camera_id=self.config.camera_id)
        self.config.calibration = config_loader.load_calibration_from_db(
            db, camera_id=self.config.camera_id, default=self.config.calibration
        )
        self.zone_polygons = {
            zone.id: np.array(zone.polygon, dtype=np.int32) for zone in self.config.zones
        }
        self._recompute_restriction()

    def _recompute_restriction(self) -> None:
        """(Re)derives the zone-only-view crop from config.restrict_to_zone_id
        + the current zone_polygons. Called on load and whenever zones are
        reloaded, since either the target zone's shape or its very existence
        (deleted -> falls back to full-frame) can change."""
        zone_id = self.config.restrict_to_zone_id
        poly = self.zone_polygons.get(zone_id) if zone_id is not None else None
        if poly is None:
            self._restrict_offset = None
            self._restricted_frame_size = None
            return
        frame_w, frame_h = self.config.frame_size
        x, y, w, h = cv2.boundingRect(poly)
        x, y = max(x, 0), max(y, 0)
        w, h = min(w, frame_w - x), min(h, frame_h - y)
        self._restrict_offset = (x, y)
        self._restricted_frame_size = (w, h)

    @property
    def output_frame_size(self) -> Tuple[int, int]:
        """The actual (w, h) of the frame process_frame() returns. Always
        config.frame_size: even with restrict_to_zone_id active, only the
        detector's input is cropped -- the returned/streamed frame is the
        full camera view, with detections shifted back to full-frame
        coordinates (see process_frame), so callers no longer need to treat
        a restricted camera's output size any differently."""
        return self.config.frame_size

    # --------------------------------------------------------------- drawing

    def draw_zones(self, frame: np.ndarray) -> None:
        """Draws every zone (fill, outline, name) onto `frame` in place."""
        self._draw_zones(frame, self.zone_polygons)

    def _draw_zones(self, frame: np.ndarray, zone_polygons: Dict[str, np.ndarray]) -> None:
        for zone in self.config.zones:
            poly = zone_polygons.get(zone.id)
            if poly is None or len(poly) == 0:
                continue  # fully outside the zone-only-view crop
            overlay = frame.copy()
            cv2.fillPoly(overlay, [poly], zone.color_bgr)
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, dst=frame)
            cv2.polylines(frame, [poly], True, zone.color_bgr, 2)
            label_pos = tuple(poly[0])
            cv2.putText(
                frame, zone.name, label_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                zone.color_bgr, 1, cv2.LINE_AA,
            )

    def _draw_track(
        self, frame: np.ndarray, xyxy: np.ndarray, label: str,
        speed_kmh: Optional[float], is_threat: bool,
        history: TrackHistory,
    ) -> None:
        # Night Shift theme: amber box + black label text, threats red + white text.
        color, text_color = (BOX_THREAT, (255, 255, 255)) if is_threat else (BOX_NORMAL, (0, 0, 0))
        x1, y1, x2, y2 = (int(v) for v in xyxy)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = label if speed_kmh is None else f"{label} {speed_kmh:.1f}km/h"
        (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        top = max(y1 - th - base - 4, 0)
        cv2.rectangle(frame, (x1, top), (x1 + tw + 6, top + th + base + 4), color, -1)
        cv2.putText(
            frame, text, (x1 + 3, top + th + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
            text_color, 1, cv2.LINE_AA,
        )
        if len(history) >= 2:
            x0, y0, _ = history[0]
            x1v, y1v, _ = history[-1]
            cv2.arrowedLine(
                frame, (int(x0), int(y0)), (int(x1v), int(y1v)), color, 2,
                tipLength=0.35,
            )


    @staticmethod
    def _draw_alert_banner(frame: np.ndarray, messages: List[str]) -> None:
        if not messages:
            return
        h, w = frame.shape[:2]
        banner_h = 22 * len(messages) + 10
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, banner_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, dst=frame)
        for i, msg in enumerate(messages):
            cv2.putText(
                frame, msg, (10, 20 + i * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                BOX_THREAT, 1, cv2.LINE_AA,
            )

    @staticmethod
    def _suppress_contained_boxes(
        detections: sv.Detections, threshold: float
    ) -> sv.Detections:
        """Removes the lower-confidence box of any pair whose overlap area
        covers at least `threshold` of the *smaller* box's area. Catches
        same-object duplicates that plain IoU-based NMS misses because the
        two boxes are very different sizes -- e.g. one box around a truck's
        cab and another around the whole truck, which overlap heavily but
        score a low IoU (IoU divides by the *union*, which is dominated by
        the larger box)."""
        n = len(detections)
        if n < 2:
            return detections
        xyxy = detections.xyxy
        confidence = detections.confidence if detections.confidence is not None else np.zeros(n)
        x1, y1, x2, y2 = xyxy[:, 0], xyxy[:, 1], xyxy[:, 2], xyxy[:, 3]
        areas = np.maximum(x2 - x1, 0) * np.maximum(y2 - y1, 0)

        order = np.argsort(-confidence)  # highest confidence first
        keep = np.ones(n, dtype=bool)
        for i_idx in range(n):
            i = order[i_idx]
            if not keep[i]:
                continue
            for j_idx in range(i_idx + 1, n):
                j = order[j_idx]
                if not keep[j]:
                    continue
                inter_w = max(0.0, min(x2[i], x2[j]) - max(x1[i], x1[j]))
                inter_h = max(0.0, min(y2[i], y2[j]) - max(y1[i], y1[j]))
                inter_area = inter_w * inter_h
                smaller_area = min(areas[i], areas[j])
                if smaller_area > 0 and inter_area / smaller_area >= threshold:
                    keep[j] = False  # j has the lower (or equal) confidence
        return detections[keep]

    def _filter_implausible_person_boxes(self, detections: sv.Detections) -> sv.Detections:
        """Drops "person" detections whose box isn't tall enough to
        plausibly be a standing/crouching person -- catches e.g. a pair of
        wheelie bins viewed from an elevated angle, which forms a roughly
        square silhouette the generic COCO detector sometimes misclassifies
        as "person". Never touches non-person boxes."""
        if len(detections) == 0 or self.config.person_min_aspect_ratio <= 0:
            return detections
        person_class_ids = {cid for cid, name in self.class_names.items() if name == "person"}
        if not person_class_ids:
            return detections
        is_person = np.array([int(c) in person_class_ids for c in detections.class_id])
        if not is_person.any():
            return detections
        xyxy = detections.xyxy
        widths = np.maximum(xyxy[:, 2] - xyxy[:, 0], 1e-6)
        heights = np.maximum(xyxy[:, 3] - xyxy[:, 1], 1e-6)
        aspect_ratios = heights / widths
        keep = ~is_person | (aspect_ratios >= self.config.person_min_aspect_ratio)
        return detections[keep]

    def _filter_person_shadows(self, detections: sv.Detections, frame: np.ndarray) -> sv.Detections:
        """Drops "person" boxes that are really the shadow of a person next
        to them. A shadow is attached at the feet, so only a box touching
        another person box is a candidate, and it's only dropped if that
        neighbour isn't shadow-like itself -- a lone worker in dark clothes,
        or two people side by side, are always kept."""
        if not self.config.ignore_person_shadows or len(detections) < 2:
            return detections
        person_idx = [
            i for i, c in enumerate(detections.class_id) if self._class_name(int(c)) == "person"
        ]
        if len(person_idx) < 2:
            return detections
        boxes = detections.xyxy
        neighbours: Dict[int, List[int]] = {}
        for i in person_idx:
            x1, y1, x2, y2 = boxes[i]
            m = SHADOW_TOUCH_MARGIN * (y2 - y1)
            neighbours[i] = [
                j for j in person_idx if j != i
                and boxes[j][0] <= x2 + m and boxes[j][2] >= x1 - m
                and boxes[j][1] <= y2 + m and boxes[j][3] >= y1 - m
            ]
        others = {i: [boxes[j] for j in person_idx if j != i] for i in person_idx}
        shadow_like = {
            i: self._is_shadow_like(frame, boxes[i], others[i])
            for i in person_idx if neighbours[i]
        }
        keep = np.ones(len(detections), dtype=bool)
        for i, is_shadow in shadow_like.items():
            if is_shadow and any(not shadow_like.get(j, False) for j in neighbours[i]):
                keep[i] = False
        return detections[keep]

    @staticmethod
    def _is_shadow_like(frame: np.ndarray, xyxy: np.ndarray, other_boxes: List[np.ndarray]) -> bool:
        """True if the box holds only floor (same hue and brightness as the
        ring of floor just outside it) and darkened floor (same hue, 30-85%
        as bright), with a real share of the latter."""
        sample = VisionEngine._sample_box_and_floor(frame, xyxy, other_boxes)
        if sample is None:
            return False
        _, same_colour, ratio = sample
        shadow = same_colour & (ratio >= SHADOW_DARKEN_RANGE[0]) & (ratio < SHADOW_DARKEN_RANGE[1])
        floor = same_colour & (ratio >= SHADOW_FLOOR_RANGE[0]) & (ratio <= SHADOW_FLOOR_RANGE[1])
        other = ~(shadow | floor)
        return bool(
            other.mean() < SHADOW_MAX_OTHER_FRACTION and shadow.mean() >= SHADOW_MIN_SHADOW_FRACTION
        )

    @staticmethod
    def _sample_box_and_floor(
        frame: np.ndarray, xyxy: np.ndarray, other_boxes: List[np.ndarray]
    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Compares a box's pixels with the floor in a ring just outside it
        (other person boxes left out). Returns (box HSV as int16, mask of
        pixels the floor's colour, brightness / floor brightness), or None
        if too little floor is visible to judge."""
        frame_h, frame_w = frame.shape[:2]
        x1, y1, x2, y2 = (int(round(v)) for v in xyxy)
        x1, y1, x2, y2 = max(x1, 0), max(y1, 0), min(x2, frame_w), min(y2, frame_h)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        dx = max(1, int((x2 - x1) * SHADOW_RING_FRACTION))
        dy = max(1, int((y2 - y1) * SHADOW_RING_FRACTION))
        rx1, ry1 = max(x1 - dx, 0), max(y1 - dy, 0)
        rx2, ry2 = min(x2 + dx, frame_w), min(y2 + dy, frame_h)
        hsv = cv2.cvtColor(frame[ry1:ry2, rx1:rx2], cv2.COLOR_BGR2HSV).astype(np.int16)

        # Floor sample: the ring around the box, minus any other person.
        ring = np.ones(hsv.shape[:2], dtype=bool)
        for bx1, by1, bx2, by2 in [(x1, y1, x2, y2), *other_boxes]:
            ring[
                max(int(by1) - ry1, 0):max(int(by2) - ry1, 0),
                max(int(bx1) - rx1, 0):max(int(bx2) - rx1, 0),
            ] = False
        if np.count_nonzero(ring) < 20:
            return None
        box = hsv[y1 - ry1:y2 - ry1, x1 - rx1:x2 - rx1]
        same_colour, ratio = _compare_to_floor(box, np.median(hsv[ring], axis=0))
        return box, same_colour, ratio

    def _filter_by_class_confidence(self, detections: sv.Detections) -> sv.Detections:
        """Applies independent confidence floors per class on top of the
        single floor the main detector was actually run at (detection_conf,
        set to the minimum of these so nothing needed here got dropped
        early) -- lets e.g. "truck" be tightened without also raising the
        floor for "person". bus/motorcycle share car_confidence (not
        separately exposed). Classes with no configured threshold (anything
        besides person/car/truck/bus/motorcycle) pass through untouched."""
        if len(detections) == 0 or detections.confidence is None:
            return detections
        thresholds = {
            "person": self.config.person_confidence,
            "car": self.config.car_confidence,
            "truck": self.config.truck_confidence,
            "bus": self.config.car_confidence,
            "motorcycle": self.config.car_confidence,
        }
        keep = np.array([
            detections.confidence[i] >= thresholds.get(self._class_name(int(c)), 0.0)
            for i, c in enumerate(detections.class_id)
        ])
        return detections[keep]

    def _dedup_vehicle_detections(self, detections: sv.Detections) -> sv.Detections:
        """Suppresses duplicate boxes on the same vehicle -- e.g. the
        detector calling one vehicle both "car" and "truck", or emitting two
        overlapping boxes for it at a low detection_conf. Restricted to
        "vehicle"-kind boxes only (never touches/competes against "person"
        boxes), so a person legitimately overlapping a vehicle is never
        suppressed by this."""
        if len(detections) == 0:
            return detections
        is_vehicle = np.array([
            self._object_kind(self._class_name(int(c))) == "vehicle"
            for c in detections.class_id
        ])
        if not is_vehicle.any():
            return detections
        vehicles = detections[is_vehicle].with_nms(
            threshold=self.config.vehicle_nms_iou_threshold, class_agnostic=True
        )
        vehicles = self._suppress_contained_boxes(
            vehicles, self.config.vehicle_containment_threshold
        )
        others = detections[~is_vehicle]
        if len(others) == 0:
            return vehicles
        return sv.Detections.merge([others, vehicles])

    # -------------------------------------------------------------- pipeline

    def process_frame(
        self, frame: np.ndarray, ts: Optional[float] = None
    ) -> Tuple[np.ndarray, List[dict]]:
        """`ts` = when the frame was captured (camera_manager passes its
        arrival time); defaults to now."""
        ts = time.time() if ts is None else ts
        frame = cv2.resize(frame, self.config.frame_size, interpolation=cv2.INTER_AREA)
        annotated = frame.copy()

        if self._restrict_offset is not None:
            # Zone-only *detection*: black out everything outside the target
            # zone's polygon, then crop to its bounding box, so nothing
            # outside it ever reaches the detector -- but `annotated` (what
            # gets streamed/snapshotted) stays the full, uncropped frame, so
            # the user can still see the whole camera view live; only the
            # area outside the zone never gets boxes/alerts drawn on it,
            # since nothing was ever detected there. Detections coming back
            # from `detect_frame` are in that crop's coordinate space, so
            # they're shifted back to full-frame coordinates below (right
            # after the detections are deduped) --
            # from that point on, tracking/zones/drawing all operate in the
            # same full-frame space as an unrestricted camera, no separate
            # "restricted zone polygons" needed.
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.fillPoly(mask, [self.zone_polygons[self.config.restrict_to_zone_id]], 255)
            masked = cv2.bitwise_and(frame, frame, mask=mask)
            x, y = self._restrict_offset
            w, h = self._restricted_frame_size
            detect_frame = masked[y:y + h, x:x + w]
        else:
            detect_frame = frame

        # The main detector (+ tracker) runs every frame, on the full
        # frame_size frame -- shrinking it made distant/small people fall
        # below what YOLOv8s can reliably pick up.
        detections = self.engine.predict(
            detect_frame, conf=self.config.detection_conf,
            imgsz=self.config.detector_imgsz, device=self.config.device,
        )
        detections = self._filter_implausible_person_boxes(detections)
        detections = self._filter_by_class_confidence(detections)
        detections = self._dedup_vehicle_detections(detections)
        if self._restrict_offset is not None and len(detections) > 0:
            # Shift detections from detect_frame's crop-space back to
            # full-frame coordinates -- from here on (tracking, zones,
            # drawing) everything operates in the same full-frame space as
            # an unrestricted camera.
            ox, oy = self._restrict_offset
            detections.xyxy = detections.xyxy + np.array([ox, oy, ox, oy], dtype=detections.xyxy.dtype)
        # Before tracking, so a shadow never becomes a track: no exclusion
        # alert and no heatmap hits from it.
        detections = self._filter_person_shadows(detections, frame)
        detections = self.tracker.update_with_detections(detections)

        events: List[dict] = []
        banner_messages: List[str] = []
        zones_by_id = {zone.id: zone for zone in self.config.zones}

        # Pass 1: build per-track info (position, speed, zone membership).
        tracks: List[_TrackInfo] = []
        for i in range(len(detections)):
            track_id = detections.tracker_id[i]
            if track_id is None:
                continue
            xyxy = detections.xyxy[i]
            class_name = self._class_name(int(detections.class_id[i]))
            kind = self._object_kind(class_name)
            if kind == "other":
                continue

            gx, gy = self._ground_point(xyxy)
            self._track_last_seen[track_id] = ts

            zone_hits = [
                zone.id for zone in self.config.zones
                if cv2.pointPolygonTest(self.zone_polygons[zone.id], (gx, gy), False) >= 0
            ]

            history = self.track_history[track_id]
            # An identical ground point to the last sample is a repeated frame,
            # not a measurement: recording it would show the vehicle frozen,
            # then jumping ahead on the next fresh box -- a speed spike.
            if not history or history[-1][:2] != (gx, gy):
                history.append((gx, gy, ts))
            while history and ts - history[0][2] > self.config.speed_window_s:
                history.popleft()
            speed_kmh = self._speed_kmh(history)

            tracks.append(_TrackInfo(
                track_id=int(track_id), xyxy=xyxy, class_name=class_name, kind=kind,
                point=(gx, gy), speed_kmh=speed_kmh, history=history, zone_hits=zone_hits,
                confidence=None if detections.confidence is None else float(detections.confidence[i]),
            ))

        self.last_tracks = tracks

        events.extend(self._apply_rules(tracks, ts))
        events.extend(self._run_detectors(tracks, frame, ts))

        self._frames_since_prune += 1
        if self._frames_since_prune >= PRUNE_INTERVAL_FRAMES:
            self._frames_since_prune = 0
            self._prune_stale_tracks(ts)

        # Draw.
        for ti in tracks:
            for alert in ti.alerts:
                banner_messages.append(
                    f"ALERT: track {ti.track_id} ({ti.class_name}) - {alert.replace('_', ' ')}"
                )
            conf = "" if ti.confidence is None else f" {ti.confidence:.2f}"
            self._draw_track(
                annotated, ti.xyxy, f"#{ti.track_id} {ti.class_name}{conf}", ti.speed_kmh,
                bool(ti.alerts), ti.history,
            )

        # Zones are deliberately not drawn here: the Live Monitor draws them as an
        # opt-in overlay, and event snapshots add them via draw_zones().
        self._draw_alert_banner(annotated, banner_messages)
        return annotated, events

    def _run_detectors(self, tracks: List[_TrackInfo], frame: np.ndarray, ts: float) -> List[CandidateEvent]:
        """Runs the analytics detectors; tracks named in an event's key_track_ids are drawn as threats."""
        if not self.detectors:
            return []
        ctx = FrameContext(
            camera_id=self.config.camera_id, ts=ts, frame=frame, calibration=self.config.calibration,
            zones=self.config.zones,
            tracks=[TrackView(
                track_id=t.track_id, class_name=t.class_name, kind=t.kind, xyxy=t.xyxy, point=t.point,
                speed_kmh=t.speed_kmh, zone_hits=list(t.zone_hits), confidence=t.confidence,
            ) for t in tracks],
        )
        wanted = set()
        for detector in self.detectors:
            if hasattr(detector, "pose_requests"):
                wanted |= detector.pose_requests(ctx)
        self._pose_tick = (self._pose_tick + 1) % POSE_EVERY_N_FRAMES if wanted else 0
        if wanted and self._pose_tick == 1 % POSE_EVERY_N_FRAMES:
            if self._pose is None:
                from .analytics.pose import PoseRunner
                self._pose = PoseRunner(device=self.config.device)
            keypoints = self._pose.run(frame, [t for t in ctx.tracks if t.track_id in wanted])
            for tv in ctx.tracks:
                tv.keypoints = keypoints.get(tv.track_id)
        by_id = {t.track_id: t for t in tracks}
        events: List[CandidateEvent] = []
        for detector in self.detectors:
            for ev in detector.update(ctx):
                for tid in ev.get("key_track_ids", []):
                    if tid in by_id:
                        by_id[tid].alerts.append(ev["type"])
                events.append(ev)
        return events

    def _apply_rules(self, tracks: List[_TrackInfo], ts: float) -> List[dict]:
        """Evaluates exclusion/speed/stop rules against pre-built
        track info and mutates each track's `.alerts`. Split out from
        process_frame so it can be exercised directly with synthetic tracks
        in tests, without needing a real detector/video frame."""
        events: List[dict] = []
        zones_by_id = {zone.id: zone for zone in self.config.zones}

        # Pass 2: per-track rules (exclusion, speed limit, stop required).
        for ti in tracks:
            for zone_id in ti.zone_hits:
                zone = zones_by_id[zone_id]
                if ti.kind not in zone.rules.applies_to:
                    continue
                if not zone.rules.is_active_at(ts):
                    continue

                if zone.rules.exclusion:
                    ti.alerts.append("exclusion")
                    events.append({
                        "type": "exclusion", "zone_id": zone.id,
                        "zone_name": zone.name, "track_id": ti.track_id,
                        "class_name": ti.class_name, "timestamp": ts,
                        "point": ti.point,
                    })

                if zone.rules.speed_limit_kmh is not None and ti.speed_kmh is not None:
                    if ti.speed_kmh > zone.rules.speed_limit_kmh:
                        ti.alerts.append("speeding")
                        events.append({
                            "type": "speeding", "zone_id": zone.id,
                            "zone_name": zone.name, "track_id": ti.track_id,
                            "class_name": ti.class_name, "speed_kmh": ti.speed_kmh,
                            "limit_kmh": zone.rules.speed_limit_kmh, "timestamp": ts,
                            "point": ti.point,
                        })

                if zone.rules.stop_required:
                    # Progress only, no event here -- the violation (never
                    # stopped) is only known once the track leaves the zone,
                    # checked below. `satisfied` latches True permanently for
                    # this track+zone once a long-enough stop is seen, so a
                    # vehicle that stops once then keeps moving still passes.
                    # Stopped = ground point stays within STOP_MAX_DRIFT_M of
                    # an anchor spot; moving further re-anchors and restarts
                    # the timer.
                    progress = self._stop_progress.setdefault(ti.track_id, {}).setdefault(
                        zone.id, {"anchor": None, "anchor_since": ts, "satisfied": False, "frames": 0}
                    )
                    progress["frames"] += 1
                    if not progress["satisfied"]:
                        anchor = progress["anchor"]
                        if (
                            anchor is None
                            or self.config.calibration.distance_m(anchor, ti.point) > STOP_MAX_DRIFT_M
                        ):
                            progress["anchor"], progress["anchor_since"] = ti.point, ts
                        elif ts - progress["anchor_since"] >= zone.rules.stop_min_seconds:
                            progress["satisfied"] = True

            # Zone-exit check for stop-required zones: fires once, at the
            # moment a track's ground point leaves a zone it was inside last
            # frame, if it never stayed put for `stop_min_seconds` while
            # inside (zone_hits itself has no
            # memory of previous frames, so that comparison happens here).
            prev_hits = self._track_last_zone_hits.get(ti.track_id, [])
            for zone_id in prev_hits:
                if zone_id in ti.zone_hits:
                    continue  # still inside -- not an exit
                zone = zones_by_id.get(zone_id)
                if zone is None or not zone.rules.stop_required:
                    continue
                if ti.kind not in zone.rules.applies_to:
                    continue
                progress = self._stop_progress.get(ti.track_id, {}).pop(zone_id, None)
                if (
                    progress is not None and not progress["satisfied"]
                    and progress["frames"] >= self.config.stop_min_frames_in_zone
                    and zone.rules.is_active_at(ts)
                ):
                    ti.alerts.append("failed_to_stop")
                    events.append({
                        "type": "failed_to_stop", "zone_id": zone.id,
                        "zone_name": zone.name, "track_id": ti.track_id,
                        "class_name": ti.class_name, "timestamp": ts,
                        "point": ti.point,
                    })
            self._track_last_zone_hits[ti.track_id] = list(ti.zone_hits)

        return events



    def run_on_video(self, source, display: bool = False, output_path: Optional[str] = None):
        """Generator yielding (annotated_frame, events) for each frame of `source`."""
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video source: {source}")

        writer = None
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                annotated, events = self.process_frame(frame)

                if output_path and writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    h, w = annotated.shape[:2]
                    writer = cv2.VideoWriter(output_path, fourcc, 20.0, (w, h))
                if writer is not None:
                    writer.write(annotated)

                if display:
                    cv2.imshow("Vision Engine", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                yield annotated, events
        finally:
            cap.release()
            if writer is not None:
                writer.release()
            if display:
                cv2.destroyAllWindows()
