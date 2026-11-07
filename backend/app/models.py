"""SQLAlchemy ORM models: Camera, Zone and Calibration config tables (scoped
per-camera), and Event log."""
import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # "ip", "webcam" or "fisheye" (a fisheye camera connects the same way as
    # "ip" but its circular frame is de-warped -- see fisheye_* below -- into
    # a rectangular panorama before zones/detection/streaming ever see it)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    # ip-camera fields (also used by "fisheye" to reach the raw circular stream)
    protocol: Mapped[str | None] = mapped_column(String, nullable=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # optional RTSP/HTTP stream path, e.g. "/MediaInput/h264/stream_1"
    stream_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # optional basic-auth credentials for the camera itself
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)
    # webcam field (device index on the machine running the backend)
    device_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Fisheye de-warp calibration (only meaningful when source_type ==
    # "fisheye"). The lens circle is modelled as an ellipse (many fisheye
    # sensor crops aren't perfectly round) with its own horizontal/vertical
    # radius, stored as ratios (0-1) of the *raw* camera frame's width/height
    # respectively, so they stay valid regardless of the camera's native
    # resolution. Null until calibrated on the Fisheye Setup page -- until
    # then the worker streams the raw circular frame unmodified.
    # fisheye_inner_radius is a fraction (0-1) of the outer radius on both
    # axes, excluding the (usually uninteresting) area right under the
    # camera; 0 or null = use the full disk.
    fisheye_center_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    fisheye_center_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    fisheye_radius_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    fisheye_radius_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    fisheye_inner_radius: Mapped[float | None] = mapped_column(Float, nullable=True)
    # When set, this camera's live view AND detection are both restricted to
    # this one zone: the frame is masked/cropped to the zone's polygon
    # before the detector ever sees it (so nothing outside it is detected,
    # and the stream only shows that area), rather than detecting over the
    # full frame and filtering alerts by zone membership afterwards like
    # every other zone rule. Null (default) = normal full-frame behaviour.
    # Plain int, not a ForeignKey: with zones.camera_id -> cameras (CASCADE)
    # SQL Server rejects the cycle, so create_all failed on a fresh DB.
    # crud.delete_zone clears it instead (what ON DELETE SET NULL did).
    restricted_zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # source_type == "fisheye_view": one of several virtual camera views cut
    # out of a physical "fisheye" camera (see app/fisheye.py). It has no
    # connection settings of its own -- frames come from the parent camera,
    # whose fisheye_* circle calibration it uses. Plain int, not a
    # ForeignKey: SQL Server rejects self-referencing cascades, so
    # crud.delete_camera removes a parent's views itself.
    fisheye_parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Virtual camera aim, in degrees: direction 0 = towards the top of the
    # raw fisheye image, clockwise; tilt 0 = straight down the lens axis,
    # 90 = horizon; fov = horizontal field of view.
    view_direction_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    view_tilt_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    view_fov_deg: Mapped[float | None] = mapped_column(Float, nullable=True)


class ZoneType(Base):
    """Reusable rule preset (not camera-scoped -- e.g. "Pedestrian Exclusion"
    or "Vehicle Speed Limit 10km/h" is a general concept). Creating a Zone
    from a type copies these fields onto the Zone, where they can then be
    edited independently."""
    __tablename__ = "zone_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # which object classes this type's rules apply to: "person" | "vehicle" | "both"
    applies_to: Mapped[str] = mapped_column(String, nullable=False, default="person")
    rule_exclusion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_max_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    # stop-sign-style compliance: see Zone.rule_stop_required below.
    rule_stop_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_stop_min_seconds: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # optional time-of-day window ("HH:MM") the rule applies in; when
    # time_restriction_enabled is False the rule applies at all times.
    time_restriction_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_from_time: Mapped[str | None] = mapped_column(String, nullable=True)
    default_to_time: Mapped[str | None] = mapped_column(String, nullable=True)
    # seeded built-in types: shown but not deletable from the Zone Types page
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    camera_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_type_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("zone_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    polygon_points: Mapped[list] = mapped_column(JSON, nullable=False)
    # which object classes this zone's rules apply to: "person" | "vehicle" | "both"
    applies_to: Mapped[str] = mapped_column(String, nullable=False, default="person")
    max_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_exclusion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Stop-sign-style compliance: a vehicle must come to a near-stop for at
    # least stop_min_seconds at some point while inside this zone, or a
    # "failed_to_stop" incident fires when it leaves without having done so.
    rule_stop_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stop_min_seconds: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # optional time-of-day window ("HH:MM") the rules above apply in; when
    # time_restriction_enabled is False the rules apply at all times.
    time_restriction_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    from_time: Mapped[str | None] = mapped_column(String, nullable=True)
    to_time: Mapped[str | None] = mapped_column(String, nullable=True)


class Calibration(Base):
    __tablename__ = "calibrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    camera_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    line_points: Mapped[list] = mapped_column(JSON, nullable=False)
    real_world_meters: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # 4-point (rectangle) calibration only: line_points holds the 4 corners in
    # order, real_world_meters is side 1->2 and this is side 2->3 (metres).
    real_world_width_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    pixels_per_meter: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_name: Mapped[str] = mapped_column(String, nullable=False)
    policy_type: Mapped[str] = mapped_column(String, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    # "to_review" | "coached" | "dismissed"
    status: Mapped[str] = mapped_column(String, default="to_review", nullable=False)
    has_snapshot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Role(Base):
    """A named set of pages users with this role are allowed to see. The
    built-in "Admin" role (is_system) always has full access to every page,
    including the Admin menu itself, regardless of its `pages` list."""
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # length-bound so SQL Server can build a unique index on it (VARCHAR(MAX)
    # columns can't be indexed)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    pages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    password_salt: Mapped[str] = mapped_column(String, nullable=False)
    # no ondelete clause -- SQL Server's default FK behavior already blocks
    # deleting a role while users reference it (enforced again at the API
    # layer in crud.get_users_by_role for a clearer error message)
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id"), nullable=False, index=True
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set for the seeded admin (random one-time password): every API call except
    # /api/auth/me, /change-password and /logout is refused until it's changed.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)


class HeatmapCell(Base):
    """One (camera, day, metric, grid cell) bucket's accumulated count --
    see heatmap.py for the grid definition. `metric` is either a detected
    class name ("person", "car", "truck", for the Usage
    Heatmap) or "violation:<event type>" (for the Violations Heatmap)."""
    __tablename__ = "heatmap_cells"
    __table_args__ = (
        UniqueConstraint("camera_id", "day", "metric", "grid_row", "grid_col"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    camera_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # "YYYY-MM-DD"
    metric: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    grid_row: Mapped[int] = mapped_column(Integer, nullable=False)
    grid_col: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DetectionSettings(Base):
    """Global (not per-camera) detection-tuning knobs, applied to every
    camera's VisionEngine on worker (re)start. Singleton row -- id is
    always 1; crud.get_detection_settings creates it with defaults on first
    access if missing."""
    __tablename__ = "detection_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Per-class confidence floors (see EngineConfig.person/car/truck_confidence)
    person_confidence: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    car_confidence: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    truck_confidence: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    # Minimum person box height/width ratio (see EngineConfig.person_min_aspect_ratio)
    person_min_aspect_ratio: Mapped[float] = mapped_column(Float, default=1.2, nullable=False)
    # YOLO inference input size for the main person/vehicle detector (EngineConfig.detector_imgsz)
    detector_imgsz: Mapped[int] = mapped_column(Integer, default=960, nullable=False)
    # Multi-frame incident confirmation (see camera_manager._IncidentTracker): a breach must be
    # observed in confirmation_min_observations of the last confirmation_window_frames frames for
    # the same track_id before it is persisted as an Event -- filters transient/one-frame false
    # detections. confirmation_min_observations=1 reproduces the old "log on first sighting" behavior.
    confirmation_min_observations: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    confirmation_window_frames: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    # Drop person detections that are another person's shadow (EngineConfig.ignore_person_shadows)
    ignore_person_shadows: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EventComment(Base):
    __tablename__ = "event_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
