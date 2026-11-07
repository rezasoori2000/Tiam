"""Runs one capture->detect->annotate worker thread per enabled Camera row.
Each camera gets its own VisionEngine (so tracker state and zone/calibration
config never leak between cameras), its own frame queue (for /ws/stream/{id}),
and pushes alerts (tagged with camera_id) onto one shared alert queue.

A camera's failure (bad IP, unreachable device) only affects that camera's
worker/status -- other cameras keep running.
"""
import asyncio
import datetime
import logging
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Optional, Tuple

# RTSP over TCP: UDP drops packets on busy networks, which shows up as
# smeared/blocky frames (and hurts detection). Must be set before cv2 opens
# any capture; setdefault so a deployment can still override it.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
import numpy as np

from . import crud, fisheye, heatmap
from .config import CalibrationConfig, EngineConfig
from .database import SessionLocal
from .models import Camera
from .vision_engine import VisionEngine
from .ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

TARGET_FPS = 18
FRAME_INTERVAL = 1.0 / TARGET_FPS
FRAME_QUEUE_MAXSIZE = 2
RECONNECT_DELAY_S = 3.0
HEATMAP_FLUSH_INTERVAL_S = 30.0

# Performance tuning (see VisionEngine.process_frame / EngineConfig):
# frame_size is what zones/calibration/streaming/drawing all operate in --
# changing it would misalign every already-configured camera's zones, so it
# stays fixed.
FRAME_SIZE = (960, 540)
STREAM_JPEG_QUALITY = 92  # live stream, snapshots and event images (was 80/85)


# Separate from the factory system's data/event_snapshots: files are named by event id, and both
# DBs number events from 1, so a shared folder would overwrite/delete the other system's snapshots.
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "retail_event_snapshots"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def event_snapshot_path(event_id: int, zones: bool = True) -> Path:
    # A zone-less copy sits beside each snapshot so the Coaching Workbench can
    # hide the zone outlines; events recorded before it existed only have {id}.jpg.
    return SNAPSHOTS_DIR / (f"{event_id}.jpg" if zones else f"{event_id}.nozones.jpg")


# Angle (radians) from the optical axis that the calibrated ellipse edge
# represents -- i.e. the marked circle is assumed to be where the lens's
# field of view reaches 90 degrees off-axis (a ~180 degree circular fisheye,
# the norm for this kind of lens). This is the reference used to convert
# pixel radius <-> incidence angle for the equidistant ("f-theta") fisheye
# model, which is what the vast majority of CCTV fisheye lenses follow.
FISHEYE_SRC_THETA_MAX = np.pi / 2

# Output field of view (degrees), interpolated by the calibrated
# fisheye_inner_radius field (repurposed here as a 0-1 "zoom" control rather
# than a literal inner-radius exclusion): 0 = tightest crop / least residual
# distortion, 1 = widest view / more stretching near the edges. A rectilinear
# projection cannot represent a full 180 degree hemisphere (the math blows up
# at 90 degrees off-axis), so this always stays comfortably below that.
FISHEYE_OUT_HFOV_MIN_DEG = 70.0
FISHEYE_OUT_HFOV_MAX_DEG = 150.0


def _build_fisheye_maps(
    camera: Camera, src_w: int, src_h: int, out_w: int, out_h: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Builds cv2.remap lookup maps that correct a circular/elliptical
    fisheye frame into a normal-looking flat (rectilinear) view of size
    (out_w, out_h) -- the same style of correction as the `defisheye`
    library, generalized to an elliptical lens crop (source sensors aren't
    always perfectly round).

    For every output pixel we treat it as a standard pinhole camera ray:
    compute its angle off the optical axis (theta) and azimuth (phi), then
    look up where a ray at that same theta lands in the source fisheye image
    using the equidistant fisheye model (r_src = f_src * theta, with f_src
    derived from the calibrated ellipse radius at theta = 90 degrees). This
    straightens lines that pass near the lens center and removes the barrel
    curvature, unlike a polar/panorama unwrap which deliberately keeps every
    azimuth direction visible at once.
    """
    cx = (camera.fisheye_center_x if camera.fisheye_center_x is not None else 0.5) * src_w
    cy = (camera.fisheye_center_y if camera.fisheye_center_y is not None else 0.5) * src_h
    rx = (camera.fisheye_radius_x if camera.fisheye_radius_x else 0.5) * src_w
    ry = (camera.fisheye_radius_y if camera.fisheye_radius_y else 0.5) * src_h

    zoom = camera.fisheye_inner_radius if camera.fisheye_inner_radius is not None else 0.5
    zoom = min(max(zoom, 0.0), 1.0)
    hfov_deg = FISHEYE_OUT_HFOV_MIN_DEG + zoom * (FISHEYE_OUT_HFOV_MAX_DEG - FISHEYE_OUT_HFOV_MIN_DEG)
    hfov = np.radians(hfov_deg)

    fx_src = rx / FISHEYE_SRC_THETA_MAX
    fy_src = ry / FISHEYE_SRC_THETA_MAX
    f_out = (out_w / 2.0) / np.tan(hfov / 2.0)

    xs, ys = np.meshgrid(
        np.arange(out_w, dtype=np.float32), np.arange(out_h, dtype=np.float32)
    )
    xn = (xs - out_w / 2.0) / f_out
    yn = (ys - out_h / 2.0) / f_out
    theta = np.arctan(np.sqrt(xn * xn + yn * yn))
    phi = np.arctan2(yn, xn)

    map_x = (cx + fx_src * theta * np.cos(phi)).astype(np.float32)
    map_y = (cy + fy_src * theta * np.sin(phi)).astype(np.float32)
    return map_x, map_y


# An incident only ends once its key hasn't fired for this long. A single
# missed frame (detector flicker, a brief
# occlusion) must not split one breach into many events + snapshots.
INCIDENT_COOLDOWN_S = 60.0
# Events emitted once (a verdict, not a per-frame breach): they skip the
# min-observations count, which they could never reach. Their noise guard
# lives in the vision engine instead (see EngineConfig.stop_min_frames_in_zone).
ONE_SHOT_EVENT_TYPES = {"failed_to_stop"}


def _incident_key(ev: dict) -> tuple:
    """Identifies *who* is breaching *what*, so the same person/vehicle
    continuously breaching one zone's rule only ever counts as one ongoing
    incident, while a different track breaching the same zone/rule is a
    separate incident."""
    return (ev.get("zone_id"), ev.get("type"), ev.get("track_id"))


# When the tracker loses someone (occluded by a car, a missed detection)
# they come back under a NEW track id -- a new _incident_key -- even though
# it's the same person still breaching the same rule. A new key is merged into
# an open incident of the same zone + rule if it appears within this many
# frame pixels (960x540 space) of where that incident was last seen; the
# allowance grows with how long it's been gone, since they kept walking.
INCIDENT_MATCH_BASE_PX = 80.0
INCIDENT_MATCH_PX_PER_S = 60.0
INCIDENT_MATCH_MAX_PX = 300.0


class _IncidentTracker:
    """Decides whether a breach event starts a NEW incident (-> save one
    event + snapshot) or continues an ongoing one (-> suppress), so the
    Coaching Workbench shows a single event per breach per object.

    A brand-new incident isn't persisted on its first observation -- it must
    first be seen in at least `min_observations` of the last `window_frames`
    processed frames (DetectionSettings.confirmation_min_observations/
    confirmation_window_frames), so a one-frame false/transient detection
    (a tracker glitch) never reaches
    the database. `min_observations=1` reproduces the old "persist on first
    sighting" behavior. An incident that goes quiet (see INCIDENT_COOLDOWN_S)
    before reaching that count is dropped by `prune()` without ever being
    persisted."""

    def __init__(self, min_observations: int = 1, window_frames: int = 1) -> None:
        # Each open incident: {"zone_rule", "point", "last_seen", "frame",
        # "confirmed", "observations" (frame numbers within the trailing
        # window), "first_seen_ts"}.
        self._incidents: list = []
        self._by_key: Dict[tuple, dict] = {}
        self._frame = 0
        self._min_observations = max(1, min_observations)
        self._window_frames = max(self._min_observations, window_frames)

    def start_frame(self) -> None:
        self._frame += 1

    def observe(self, ev: dict, now: float) -> bool:
        """Records one observation of this breach for the current frame.
        Returns True exactly once per incident -- the frame it first reaches
        confirmation -- which is also when the caller should persist it.
        `ev["timestamp"]` is rewritten to the incident's first-observed time
        (not this confirmation frame) so the saved Event reflects when the
        breach actually started, not when it was confirmed."""
        key = _incident_key(ev)
        zone_rule = (ev.get("zone_id"), ev.get("type"))
        point = ev.get("point")

        inc = self._by_key.get(key)
        if inc is not None and now - inc["last_seen"] >= INCIDENT_COOLDOWN_S:
            inc = None  # quiet for over a minute: a genuinely fresh breach
        if inc is None and point is not None:
            inc = self._match_nearby(zone_rule, point, now)

        if inc is None:
            inc = {
                "zone_rule": zone_rule,
                "confirmed": False,
                "observations": [],
                "first_seen_ts": ev.get("timestamp", now),
            }
            self._incidents.append(inc)

        inc["observations"].append(self._frame)
        cutoff = self._frame - self._window_frames
        inc["observations"] = [f for f in inc["observations"] if f > cutoff]
        inc.update(point=point, last_seen=now, frame=self._frame)
        self._by_key[key] = inc

        if inc["confirmed"]:
            return False
        if len(inc["observations"]) < self._min_observations and ev.get("type") not in ONE_SHOT_EVENT_TYPES:
            return False
        inc["confirmed"] = True
        ev["timestamp"] = inc["first_seen_ts"]
        return True

    def _match_nearby(self, zone_rule: tuple, point, now: float) -> Optional[dict]:
        best, best_dist = None, None
        for inc in self._incidents:
            if inc["zone_rule"] != zone_rule or inc["point"] is None:
                continue
            # Already claimed by another object THIS frame -> that's a
            # different person standing nearby, not this one reappearing.
            if inc["frame"] == self._frame:
                continue
            gap = now - inc["last_seen"]
            if gap >= INCIDENT_COOLDOWN_S:
                continue
            dist = float(np.hypot(point[0] - inc["point"][0], point[1] - inc["point"][1]))
            limit = min(INCIDENT_MATCH_BASE_PX + INCIDENT_MATCH_PX_PER_S * gap, INCIDENT_MATCH_MAX_PX)
            if dist <= limit and (best_dist is None or dist < best_dist):
                best, best_dist = inc, dist
        return best

    def prune(self, now: float) -> None:
        """Forget incidents quiet for longer than the cooldown, so the same
        object re-breaching later is a fresh incident (and memory is bounded)."""
        self._incidents = [i for i in self._incidents if now - i["last_seen"] < INCIDENT_COOLDOWN_S]
        live = {id(i) for i in self._incidents}
        self._by_key = {k: i for k, i in self._by_key.items() if id(i) in live}


RAW_JPEG_INTERVAL_S = 1.0


class _SharedCapture:
    """One connection to a physical camera, read on its own thread as fast as
    the camera sends. Only the newest frame is kept, stamped with the time it
    arrived: a worker slower than the camera skips frames instead of falling
    behind on a queue, so the live view doesn't lag and speed uses real
    capture times (it once used processing time on frames read in order,
    which read low and spiked whenever the backlog overflowed). A fisheye
    camera's connection is also shared by all of its virtual view workers
    (source_type "fisheye_view"), so 4 views still open a single RTSP stream
    and decode each frame once. Started on the first acquire, stopped when
    the last worker releases it (see _acquire_capture / _release_capture)."""

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.refs = 0
        self.status = "starting"
        self.last_error: Optional[str] = None
        # Still-circular frame for the Fisheye Setup page (re-encoded at
        # most once a second -- a 2048x2048 JPEG every frame is wasted work).
        self.last_raw_jpeg: Optional[bytes] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_ts = 0.0  # time.time() when self._frame arrived
        self._seq = 0
        self._cond = threading.Condition()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop_event,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.status = "stopped"

    def restart(self) -> None:
        """Reconnect with freshly-loaded camera settings."""
        self.stop()
        self.status = "starting"
        self.start()

    def latest_frame(self) -> Optional[np.ndarray]:
        with self._cond:
            return None if self._frame is None else self._frame.copy()

    def wait_frame(
        self, after_seq: int, timeout: float
    ) -> Tuple[int, Optional[np.ndarray], float]:
        """Blocks until a frame newer than `after_seq` arrives (or timeout).
        Returns (seq, frame, arrival time)."""
        with self._cond:
            if self._seq <= after_seq:
                self._cond.wait(timeout)
            if self._seq <= after_seq or self._frame is None:
                return after_seq, None, 0.0
            return self._seq, self._frame, self._frame_ts

    def _run(self, stop_event: threading.Event) -> None:
        db = SessionLocal()
        try:
            camera = crud.get_camera(db, self.camera_id)
        finally:
            db.close()
        if camera is None:
            self.status = "error"
            self.last_error = "camera row not found"
            return
        source = _CameraWorker._capture_source(camera)
        is_fisheye = camera.source_type == "fisheye"
        last_jpeg_at = 0.0
        try:
            while not stop_event.is_set():
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
                    self.status = "reconnecting"
                    self.last_error = f"could not open source {_CameraWorker._redact_source(source)!r}"
                    cap.release()
                    stop_event.wait(RECONNECT_DELAY_S)
                    continue
                self.status = "connected"
                self.last_error = None
                try:
                    while not stop_event.is_set():
                        ok, frame = cap.read()
                        if not ok:
                            self.status = "reconnecting"
                            self.last_error = "frame read failed"
                            break
                        with self._cond:
                            self._frame = frame
                            self._frame_ts = time.time()
                            self._seq += 1
                            self._cond.notify_all()
                        if is_fisheye and time.time() - last_jpeg_at >= RAW_JPEG_INTERVAL_S:
                            ok_raw, raw = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            if ok_raw:
                                self.last_raw_jpeg = raw.tobytes()
                                last_jpeg_at = time.time()
                finally:
                    cap.release()
                if not stop_event.is_set():
                    stop_event.wait(RECONNECT_DELAY_S)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Camera %s capture crashed", self.camera_id)
            self.status = "error"
            self.last_error = _CameraWorker._redact_source(exc)


_shared_captures: Dict[int, _SharedCapture] = {}
_captures_lock = threading.Lock()


def _acquire_capture(camera_id: int) -> _SharedCapture:
    with _captures_lock:
        cap = _shared_captures.get(camera_id)
        if cap is None:
            cap = _SharedCapture(camera_id)
            _shared_captures[camera_id] = cap
            cap.start()
        cap.refs += 1
        return cap


def _release_capture(camera_id: int) -> None:
    with _captures_lock:
        cap = _shared_captures.get(camera_id)
        if cap is None:
            return
        cap.refs -= 1
        if cap.refs > 0:
            return
        del _shared_captures[camera_id]
    cap.stop()


class _CameraWorker:
    def __init__(self, camera_id: int, loop: asyncio.AbstractEventLoop, alert_queue: asyncio.Queue):
        self.camera_id = camera_id
        self.loop = loop
        self.alert_queue = alert_queue
        self.frame_queue: asyncio.Queue = asyncio.Queue(maxsize=FRAME_QUEUE_MAXSIZE)
        self.status = "starting"  # starting | connected | reconnecting | stopped | error
        self.last_error: Optional[str] = None
        # Clean (un-annotated) frame, for the Zone Studio snapshot endpoint --
        # drawing new zones on a frame that's already covered in existing
        # zone/box overlays is confusing.
        self.last_raw_frame_jpeg: Optional[bytes] = None
        # cv2.remap tables for a fisheye camera's de-warp or a fisheye
        # view's virtual camera (built on the first frame, see _dewarp).
        self._fisheye_maps: Optional[Tuple[np.ndarray, np.ndarray]] = None
        # fisheye_view only: the parent's saved lens circle (None = auto-detect).
        self._view_circle: Optional[fisheye.Circle] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # One saved event per ongoing breach per object -- see _IncidentTracker.
        self._incidents = _IncidentTracker()
        # In-memory Usage/Violations Heatmap accumulator: (day, metric) ->
        # GRID_ROWS x GRID_COLS counts, flushed to the DB periodically (never
        # written per-frame -- see _flush_heatmap).
        self._heatmap_counts: Dict[Tuple[str, str], np.ndarray] = {}
        self._last_heatmap_flush = time.time()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.status = "stopped"

    def _enqueue_frame(self, jpeg_bytes: bytes) -> None:
        if self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.frame_queue.put_nowait(jpeg_bytes)

    def _push_frame(self, jpeg_bytes: bytes) -> None:
        self.loop.call_soon_threadsafe(self._enqueue_frame, jpeg_bytes)

    def _push_alert(self, payload: dict) -> None:
        self.loop.call_soon_threadsafe(self.alert_queue.put_nowait, payload)

    @staticmethod
    def _capture_source(camera: Camera):
        if camera.source_type == "webcam":
            return camera.device_index or 0
        if camera.username:
            user = urllib.parse.quote(camera.username, safe="")
            pwd = urllib.parse.quote(camera.password or "", safe="")
            auth = f"{user}:{pwd}@"
        else:
            auth = ""
        path = camera.stream_path or ""
        if path and not path.startswith("/"):
            path = "/" + path
        return f"{camera.protocol}://{auth}{camera.ip}:{camera.port}{path}"

    @staticmethod
    def _redact_source(source) -> str:
        """Strips embedded RTSP/HTTP credentials before a capture source is
        surfaced in last_error, which is readable via the unauthenticated
        /api/cameras/{id}/status endpoint."""
        text = str(source)
        return re.sub(r"://[^@/]+@", "://***@", text)

    def _build_engine(self, db) -> VisionEngine:
        settings = crud.get_detection_settings(db)
        self._incidents = _IncidentTracker(
            min_observations=settings.confirmation_min_observations,
            window_frames=settings.confirmation_window_frames,
        )
        camera = crud.get_camera(db, self.camera_id)
        restrict_to_zone_id = (
            str(camera.restricted_zone_id)
            if camera is not None and camera.restricted_zone_id is not None
            else None
        )
        # The main detector's own predict() call (and the ByteTrack
        # activation threshold derived from it) needs a single floor -- use
        # the loosest of the per-class thresholds below so none of them get
        # dropped before _filter_by_class_confidence can apply its own,
        # clamped so a very low setting doesn't flood the tracker.
        detection_conf = max(0.05, min(
            settings.person_confidence, settings.car_confidence, settings.truck_confidence,
        ))
        config = EngineConfig(
            camera_id=self.camera_id,
            zones=[],
            calibration=CalibrationConfig(),
            detector_model_path="yolov8s.pt",
            detection_conf=detection_conf,
            person_confidence=settings.person_confidence,
            car_confidence=settings.car_confidence,
            truck_confidence=settings.truck_confidence,
            person_min_aspect_ratio=settings.person_min_aspect_ratio,
            restrict_to_zone_id=restrict_to_zone_id,
            stop_min_frames_in_zone=settings.confirmation_min_observations,
            device="cuda",
            frame_size=FRAME_SIZE,
            detector_imgsz=settings.detector_imgsz,
            ignore_person_shadows=settings.ignore_person_shadows,
        )
        engine = VisionEngine(config)
        engine.refresh_from_db(db)
        return engine

    def _bump_heatmap(self, day: str, metric: str, row: int, col: int) -> None:
        grid = self._heatmap_counts.get((day, metric))
        if grid is None:
            grid = np.zeros((heatmap.GRID_ROWS, heatmap.GRID_COLS), dtype=np.int64)
            self._heatmap_counts[(day, metric)] = grid
        grid[row, col] += 1

    def _record_usage(self, tracks, frame_size: tuple) -> None:
        """Usage Heatmap: bump one cell per tracked object per frame, so the
        accumulated grid approximates dwell time/traffic density."""
        if not tracks:
            return
        day = datetime.date.today().isoformat()
        frame_w, frame_h = frame_size
        for ti in tracks:
            row, col = heatmap.grid_cell(ti.point[0], ti.point[1], frame_w, frame_h)
            self._bump_heatmap(day, ti.class_name, row, col)

    def _record_violation(self, event: dict, frame_size: tuple) -> None:
        """Violations Heatmap: bump one cell per NEW incident (called only
        from the "not already active" branch in _run, so an ongoing breach
        is counted once, not once per frame)."""
        point = event.get("point")
        if point is None:
            return
        day = datetime.date.today().isoformat()
        frame_w, frame_h = frame_size
        row, col = heatmap.grid_cell(point[0], point[1], frame_w, frame_h)
        self._bump_heatmap(day, heatmap.violation_metric(event["type"]), row, col)

    def _flush_heatmap(self, db) -> None:
        if not self._heatmap_counts:
            return
        by_day: Dict[str, Dict[Tuple[str, int, int], int]] = {}
        for (day, metric), grid in self._heatmap_counts.items():
            nonzero = np.argwhere(grid > 0)
            if len(nonzero) == 0:
                continue
            deltas = by_day.setdefault(day, {})
            for row, col in nonzero:
                deltas[(metric, int(row), int(col))] = int(grid[row, col])
        self._heatmap_counts = {}
        self._last_heatmap_flush = time.time()
        try:
            for day, deltas in by_day.items():
                crud.upsert_heatmap_counts(db, self.camera_id, day, deltas)
        except Exception:  # pragma: no cover - defensive: don't let a heatmap
            # DB hiccup take down the camera's live video/alerts.
            logger.exception("Camera %s heatmap flush failed", self.camera_id)

    def _process_frame(self, db, engine: VisionEngine, frame: np.ndarray, ts: float) -> None:
        """Detect/annotate one frame, stream it, and persist new incidents."""
        resized = cv2.resize(frame, engine.config.frame_size, interpolation=cv2.INTER_AREA)
        ok_snap, snap_jpeg = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
        if ok_snap:
            self.last_raw_frame_jpeg = snap_jpeg.tobytes()

        annotated, events = engine.process_frame(frame, ts)
        self._record_usage(engine.last_tracks, engine.output_frame_size)

        ok_enc, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
        if ok_enc:
            self._push_frame(jpeg.tobytes())

        now = time.time()
        snapshot_jpeg: Optional[bytes] = None
        self._incidents.start_frame()
        for ev in events:
            if not self._incidents.observe(ev, now):
                continue  # not yet confirmed, or already recorded for this ongoing breach

            self._record_violation(ev, engine.output_frame_size)
            ev["camera_id"] = self.camera_id
            row = crud.create_event(db, ev)
            if snapshot_jpeg is None:
                # The annotated frame (box/banner drawn) plus the zone
                # outlines, which the live stream leaves out, is the
                # violation snapshot for the Coaching Workbench. Encoded once
                # per frame, however many events it raised.
                with_zones = annotated.copy()
                engine.draw_zones(with_zones)
                ok_snapshot, encoded = cv2.imencode(
                    ".jpg", with_zones, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY]
                )
                snapshot_jpeg = encoded.tobytes() if ok_snapshot else b""
            if snapshot_jpeg:
                event_snapshot_path(row.id).write_bytes(snapshot_jpeg)
                if ok_enc:  # the stream frame is the same image minus the zones
                    event_snapshot_path(row.id, zones=False).write_bytes(jpeg.tobytes())
                crud.mark_event_has_snapshot(db, row)
            self._push_alert(crud.to_alert_payload(row))

        self._incidents.prune(now)

    def _frames(self, camera: Camera):
        """Yields (newest raw frame, its arrival time) until the worker is
        stopped, keeping self.status/last_error current. Every camera reads
        through a _SharedCapture (fisheye views through their parent's)."""
        source_id = camera.fisheye_parent_id if camera.source_type == "fisheye_view" else camera.id
        shared = _acquire_capture(source_id)
        try:
            seq = 0
            while not self._stop_event.is_set():
                seq, frame, ts = shared.wait_frame(seq, timeout=1.0)
                self.status, self.last_error = shared.status, shared.last_error
                if frame is not None:
                    yield frame, ts
        finally:
            _release_capture(source_id)

    def _dewarp(self, camera: Camera, frame: np.ndarray, out_size: tuple) -> np.ndarray:
        """Fisheye cameras: straighten the circular frame (whole-lens view).
        Fisheye views: cut out and flatten this view's virtual camera. The
        remap tables are built once, on the first frame."""
        if camera.source_type == "fisheye":
            if camera.fisheye_center_x is None or not camera.fisheye_radius_x:
                return frame  # uncalibrated: stream the raw circle
            if self._fisheye_maps is None:
                src_h, src_w = frame.shape[:2]
                self._fisheye_maps = _build_fisheye_maps(camera, src_w, src_h, *out_size)
        elif camera.source_type == "fisheye_view":
            if self._fisheye_maps is None:
                src_h, src_w = frame.shape[:2]
                circle = self._view_circle
                if circle is None:
                    circle = fisheye.detect_lens_circle(frame)
                if circle is None:
                    return cv2.resize(frame, out_size)  # no lens found (dark frame?) -- retry next frame
                self._fisheye_maps = fisheye.build_view_maps(
                    src_w, src_h, circle,
                    camera.view_direction_deg or 0.0,
                    camera.view_tilt_deg if camera.view_tilt_deg is not None else fisheye.DEFAULT_VIEW_TILT,
                    camera.view_fov_deg or fisheye.DEFAULT_VIEW_FOV,
                    *out_size,
                )
        else:
            return frame
        return fisheye.render_view(frame, self._fisheye_maps)

    def _run(self) -> None:
        db = SessionLocal()
        try:
            camera = crud.get_camera(db, self.camera_id)
            if camera is None:
                self.status = "error"
                self.last_error = "camera row deleted before worker started"
                return
            if camera.source_type == "fisheye_view":
                parent = crud.get_camera(db, camera.fisheye_parent_id) if camera.fisheye_parent_id else None
                if parent is None or parent.source_type != "fisheye":
                    self.status = "error"
                    self.last_error = "the fisheye camera this view belongs to no longer exists"
                    return
                if parent.fisheye_center_x is not None and parent.fisheye_radius_x:
                    self._view_circle = (
                        parent.fisheye_center_x, parent.fisheye_center_y,
                        parent.fisheye_radius_x, parent.fisheye_radius_y or parent.fisheye_radius_x,
                    )
            engine = self._build_engine(db)

            for frame, frame_ts in self._frames(camera):
                t0 = time.time()
                frame = self._dewarp(camera, frame, engine.config.frame_size)
                self._process_frame(db, engine, frame, frame_ts)

                if time.time() - self._last_heatmap_flush >= HEATMAP_FLUSH_INTERVAL_S:
                    self._flush_heatmap(db)

                remaining = FRAME_INTERVAL - (time.time() - t0)
                if remaining > 0:
                    time.sleep(remaining)
        except Exception as exc:  # pragma: no cover - defensive: isolate camera failures
            logger.exception("Camera %s worker crashed", self.camera_id)
            self.status = "error"
            self.last_error = self._redact_source(exc)
        finally:
            self._flush_heatmap(db)
            db.close()


_workers: Dict[int, _CameraWorker] = {}
_stream_managers: Dict[int, ConnectionManager] = {}
_pump_futures: Dict[int, "asyncio.Future"] = {}
_loop: Optional[asyncio.AbstractEventLoop] = None
_alert_queue: Optional[asyncio.Queue] = None


async def _pump_camera_frames(camera_id: int, worker: _CameraWorker) -> None:
    manager = get_stream_manager(camera_id)
    while True:
        data = await worker.frame_queue.get()
        await manager.broadcast_bytes(data)


def start_all(loop: asyncio.AbstractEventLoop, alert_queue: asyncio.Queue, db) -> None:
    global _loop, _alert_queue
    _loop, _alert_queue = loop, alert_queue
    for camera in crud.get_cameras(db):
        if camera.is_enabled:
            _start_worker(camera.id)


def stop_all() -> None:
    for camera_id in list(_workers.keys()):
        _stop_worker(camera_id)


def _start_worker(camera_id: int) -> None:
    if camera_id in _workers:
        return
    worker = _CameraWorker(camera_id, _loop, _alert_queue)
    _workers[camera_id] = worker
    worker.start()
    # _start_worker may be called from the event-loop thread (app startup)
    # or from a FastAPI request thread (CRUD-triggered restart) -- schedule
    # the pump coroutine thread-safely in both cases.
    _pump_futures[camera_id] = asyncio.run_coroutine_threadsafe(
        _pump_camera_frames(camera_id, worker), _loop
    )


def _stop_worker(camera_id: int) -> None:
    worker = _workers.pop(camera_id, None)
    if worker is not None:
        worker.stop()
    future = _pump_futures.pop(camera_id, None)
    if future is not None:
        future.cancel()


def get_stream_manager(camera_id: int) -> ConnectionManager:
    if camera_id not in _stream_managers:
        _stream_managers[camera_id] = ConnectionManager()
    return _stream_managers[camera_id]


def on_camera_changed(db, camera_id: int) -> None:
    """Call after create/update of a Camera or any Zone/Calibration bound to
    it: restarts that camera's worker so it picks up the new config/source."""
    if _loop is None:
        return  # manager not started yet (e.g. during tests without lifespan)
    camera = crud.get_camera(db, camera_id)
    affected = [camera] if camera is not None else []
    if camera is not None and camera.source_type == "fisheye":
        # Its views read the same shared capture and use its lens-circle
        # calibration, so they restart with it.
        affected += crud.get_fisheye_views(db, camera_id)
    _stop_worker(camera_id)
    for view in affected[1:]:
        _stop_worker(view.id)
    if camera is not None and camera.source_type != "fisheye_view":
        # Normally the last release above already stopped the shared
        # capture; if a worker thread was slow to exit it's still running
        # with the old connection settings, so force a reconnect. (A view
        # has no connection of its own -- its parent's is left alone.)
        shared = _shared_captures.get(camera_id)
        if shared is not None:
            shared.restart()
    for cam in affected:
        if cam.is_enabled:
            _start_worker(cam.id)


def restart_camera(db, camera_id: int) -> None:
    """Manual full reset: tears down the worker thread (and its
    VideoCapture/VisionEngine) and starts a fresh one. Stronger than the
    worker's own automatic reconnect loop, which just reopens the capture
    inside the same thread -- useful when a camera gets stuck cycling
    connected/reconnecting on a flaky driver."""
    on_camera_changed(db, camera_id)


def restart_all(db) -> None:
    """Restarts every enabled camera's worker -- used after a global
    detection-settings change, since (like zones/calibration) there's no
    hot-reload into a running VisionEngine."""
    if _loop is None:
        return
    for camera in crud.get_cameras(db):
        if camera.is_enabled:
            on_camera_changed(db, camera.id)


def on_camera_removed(camera_id: int) -> None:
    if _loop is None:
        return
    _stop_worker(camera_id)


def get_status(camera_id: int) -> dict:
    worker = _workers.get(camera_id)
    if worker is None:
        return {"status": "stopped", "last_error": None}
    return {"status": worker.status, "last_error": worker.last_error}


def get_frame_queue(camera_id: int) -> Optional[asyncio.Queue]:
    worker = _workers.get(camera_id)
    return worker.frame_queue if worker else None


def get_latest_snapshot(camera_id: int) -> Optional[bytes]:
    worker = _workers.get(camera_id)
    return worker.last_raw_frame_jpeg if worker else None


def get_latest_fisheye_raw_snapshot(camera_id: int) -> Optional[bytes]:
    """Still-circular JPEG for a fisheye camera -- available while the
    camera itself or any of its views is running."""
    shared = _shared_captures.get(camera_id)
    return shared.last_raw_jpeg if shared else None


def get_latest_fisheye_raw_frame(camera_id: int) -> Optional[np.ndarray]:
    """Full-resolution still-circular frame (for view previews and lens
    auto-detection on the Fisheye Setup page)."""
    shared = _shared_captures.get(camera_id)
    return shared.latest_frame() if shared else None
