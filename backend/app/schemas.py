"""Pydantic request/response schemas for the cameras, zones & calibration APIs."""
import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Point = List[float]


class CameraBase(BaseModel):
    name: str
    source_type: Literal["ip", "webcam", "fisheye", "fisheye_view", "file"]
    protocol: Optional[Literal["rtsp", "http", "https"]] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    # optional stream path appended after host:port, e.g. "/MediaInput/h264/stream_1"
    stream_path: Optional[str] = None
    device_index: Optional[int] = None
    is_enabled: bool = True
    # fisheye de-warp calibration -- ratios (0-1), see models.Camera
    fisheye_center_x: Optional[float] = None
    fisheye_center_y: Optional[float] = None
    fisheye_radius_x: Optional[float] = None
    fisheye_radius_y: Optional[float] = None
    fisheye_inner_radius: Optional[float] = None
    # See models.Camera.restricted_zone_id -- when set, restricts this
    # camera's live view + detection to just this one zone.
    restricted_zone_id: Optional[int] = None
    # source_type == "fisheye_view" only -- see models.Camera
    fisheye_parent_id: Optional[int] = None
    view_direction_deg: Optional[float] = None
    view_tilt_deg: Optional[float] = None
    view_fov_deg: Optional[float] = None
    site_id: Optional[int] = None

    @model_validator(mode="after")
    def _validate_source_fields(self) -> "CameraBase":
        if self.source_type in ("ip", "fisheye"):
            if not (self.protocol and self.ip and self.port):
                raise ValueError(f"{self.source_type} cameras require protocol, ip, and port")
        elif self.source_type == "webcam":
            if self.device_index is None:
                self.device_index = 0
        elif self.source_type == "fisheye_view":
            if self.fisheye_parent_id is None:
                raise ValueError("fisheye_view cameras require fisheye_parent_id")
        elif self.source_type == "file":
            # A looping video file for tests/demos, named relative to data/retail_test_clips --
            # never an arbitrary server path.
            name = (self.stream_path or "").replace("\\", "/").strip("/")
            if not name or ".." in name.split("/") or ":" in name:
                raise ValueError("file cameras need stream_path = a file name inside data/retail_test_clips")
            self.stream_path = name
        return self


class CameraCreate(CameraBase):
    # optional basic-auth credentials for the camera itself
    username: Optional[str] = None
    password: Optional[str] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    protocol: Optional[Literal["rtsp", "http", "https"]] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    stream_path: Optional[str] = None
    device_index: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    is_enabled: Optional[bool] = None
    fisheye_center_x: Optional[float] = None
    fisheye_center_y: Optional[float] = None
    fisheye_radius_x: Optional[float] = None
    fisheye_radius_y: Optional[float] = None
    fisheye_inner_radius: Optional[float] = None
    restricted_zone_id: Optional[int] = None
    view_direction_deg: Optional[float] = None
    view_tilt_deg: Optional[float] = None
    view_fov_deg: Optional[float] = None


class FisheyeViewIn(BaseModel):
    # id of an existing view to update; omitted = create a new one
    id: Optional[int] = None
    name: str = Field(min_length=1)
    direction_deg: float
    tilt_deg: float = Field(ge=0, le=89)
    fov_deg: float = Field(ge=20, le=150)


class FisheyeViewsIn(BaseModel):
    # The full set of views for one fisheye camera: existing views not
    # listed are deleted.
    views: list[FisheyeViewIn] = Field(max_length=8)


class CameraOut(CameraBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # credentials are write-only -- username is shown for editing convenience,
    # password is deliberately excluded from every response.
    username: Optional[str] = None


AppliesTo = Literal["person", "vehicle", "both"]


class ZoneTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    applies_to: AppliesTo = "person"
    rule_exclusion: bool = False
    default_max_speed_kmh: Optional[float] = None
    rule_stop_required: bool = False
    default_stop_min_seconds: float = 1.0
    rule_prowling: bool = False
    default_prowling_min_vehicles: float = Field(default=3.0, ge=1, le=20)
    time_restriction_enabled: bool = False
    default_from_time: Optional[str] = None
    default_to_time: Optional[str] = None


class ZoneTypeCreate(ZoneTypeBase):
    pass


class ZoneTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    applies_to: Optional[AppliesTo] = None
    rule_exclusion: Optional[bool] = None
    default_max_speed_kmh: Optional[float] = None
    rule_stop_required: Optional[bool] = None
    default_stop_min_seconds: Optional[float] = None
    rule_prowling: Optional[bool] = None
    default_prowling_min_vehicles: Optional[float] = Field(default=None, ge=1, le=20)
    time_restriction_enabled: Optional[bool] = None
    default_from_time: Optional[str] = None
    default_to_time: Optional[str] = None


class ZoneTypeOut(ZoneTypeBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_system: bool


class ZoneBase(BaseModel):
    camera_id: int
    zone_type_id: Optional[int] = None
    name: str
    polygon_points: List[Point]
    applies_to: AppliesTo = "person"
    max_speed_kmh: Optional[float] = None
    rule_exclusion: bool = False
    rule_stop_required: bool = False
    stop_min_seconds: float = 1.0
    rule_prowling: bool = False
    prowling_min_vehicles: float = Field(default=3.0, ge=1, le=20)
    time_restriction_enabled: bool = False
    from_time: Optional[str] = None
    to_time: Optional[str] = None

    @field_validator("polygon_points")
    @classmethod
    def _at_least_three_points(cls, v: List[Point]) -> List[Point]:
        if len(v) < 3:
            raise ValueError("polygon_points must contain at least 3 [x, y] points")
        return v


class ZoneCreate(BaseModel):
    """zone_type_id is required (pick a type first); the rule fields below
    are optional overrides -- if omitted, they're copied from that type."""
    camera_id: int
    zone_type_id: int
    name: str
    polygon_points: List[Point]
    applies_to: Optional[AppliesTo] = None
    max_speed_kmh: Optional[float] = None
    rule_exclusion: Optional[bool] = None
    rule_stop_required: Optional[bool] = None
    stop_min_seconds: Optional[float] = None
    rule_prowling: Optional[bool] = None
    prowling_min_vehicles: Optional[float] = Field(default=None, ge=1, le=20)
    time_restriction_enabled: Optional[bool] = None
    from_time: Optional[str] = None
    to_time: Optional[str] = None

    @field_validator("polygon_points")
    @classmethod
    def _at_least_three_points(cls, v: List[Point]) -> List[Point]:
        if len(v) < 3:
            raise ValueError("polygon_points must contain at least 3 [x, y] points")
        return v


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    polygon_points: Optional[List[Point]] = None
    applies_to: Optional[AppliesTo] = None
    max_speed_kmh: Optional[float] = None
    rule_exclusion: Optional[bool] = None
    rule_stop_required: Optional[bool] = None
    stop_min_seconds: Optional[float] = None
    rule_prowling: Optional[bool] = None
    prowling_min_vehicles: Optional[float] = Field(default=None, ge=1, le=20)
    time_restriction_enabled: Optional[bool] = None
    from_time: Optional[str] = None
    to_time: Optional[str] = None

    @field_validator("polygon_points")
    @classmethod
    def _at_least_three_points(cls, v: Optional[List[Point]]) -> Optional[List[Point]]:
        if v is not None and len(v) < 3:
            raise ValueError("polygon_points must contain at least 3 [x, y] points")
        return v


class ZoneOut(ZoneBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


def _check_calibration_points(v: List[Point]) -> List[Point]:
    """2 points = reference line; 4 = corners of a ground rectangle, in order
    around it (a crossed or collinear order would give a nonsense mapping)."""
    if len(v) == 2:
        return v
    if len(v) != 4:
        raise ValueError("line_points must be 2 points (line) or 4 points (rectangle)")
    turns = [
        (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        for a, b, c in ((v[i], v[(i + 1) % 4], v[(i + 2) % 4]) for i in range(4))
    ]
    if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        raise ValueError("the 4 corners must be clicked in order around the rectangle")
    return v


def _check_positive(v: Optional[float]) -> Optional[float]:
    if v is not None and v <= 0:
        raise ValueError("real-world lengths must be > 0")
    return v


class CalibrationBase(BaseModel):
    camera_id: int
    name: str
    line_points: List[Point]
    real_world_meters: float = 1.0
    # rectangle only: length of side 2->3 (real_world_meters is side 1->2)
    real_world_width_m: Optional[float] = None

    @field_validator("line_points")
    @classmethod
    def _points(cls, v: List[Point]) -> List[Point]:
        return _check_calibration_points(v)

    @field_validator("real_world_meters", "real_world_width_m")
    @classmethod
    def _lengths(cls, v: Optional[float]) -> Optional[float]:
        return _check_positive(v)

    @model_validator(mode="after")
    def _rectangle_needs_width(self):
        if len(self.line_points) == 4 and self.real_world_width_m is None:
            raise ValueError("a 4-point calibration needs real_world_width_m")
        return self


class CalibrationCreate(CalibrationBase):
    pass


class CalibrationUpdate(BaseModel):
    name: Optional[str] = None
    line_points: Optional[List[Point]] = None
    real_world_meters: Optional[float] = None
    real_world_width_m: Optional[float] = None

    @field_validator("line_points")
    @classmethod
    def _points(cls, v: Optional[List[Point]]) -> Optional[List[Point]]:
        return None if v is None else _check_calibration_points(v)

    @field_validator("real_world_meters", "real_world_width_m")
    @classmethod
    def _lengths(cls, v: Optional[float]) -> Optional[float]:
        return _check_positive(v)


class CalibrationOut(CalibrationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pixels_per_meter: float
    is_active: bool


class DetectionSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    person_confidence: float
    car_confidence: float
    truck_confidence: float
    person_min_aspect_ratio: float
    detector_imgsz: int
    confirmation_min_observations: int
    confirmation_window_frames: int
    ignore_person_shadows: bool
    detector_model: str


class DetectionSettingsUpdate(BaseModel):
    person_confidence: Optional[float] = None
    car_confidence: Optional[float] = None
    truck_confidence: Optional[float] = None
    person_min_aspect_ratio: Optional[float] = None
    detector_imgsz: Optional[int] = None
    confirmation_min_observations: Optional[int] = None
    confirmation_window_frames: Optional[int] = None
    ignore_person_shadows: Optional[bool] = None
    detector_model: Optional[str] = None

    @field_validator(
        "person_confidence", "car_confidence", "truck_confidence",
    )
    @classmethod
    def _confidence_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 < v <= 1):
            raise ValueError("confidence must be between 0 (exclusive) and 1")
        return v

    @field_validator("person_min_aspect_ratio")
    @classmethod
    def _positive_aspect_ratio(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("person_min_aspect_ratio must be >= 0")
        return v


    @field_validator("detector_imgsz")
    @classmethod
    def _imgsz_range(cls, v: Optional[int]) -> Optional[int]:
        # YOLO needs a multiple of its max stride (32).
        if v is not None and (not (320 <= v <= 1920) or v % 32 != 0):
            raise ValueError("detector_imgsz must be a multiple of 32 between 320 and 1920")
        return v

    @field_validator("confirmation_min_observations")
    @classmethod
    def _min_observations_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 30):
            raise ValueError("confirmation_min_observations must be between 1 and 30")
        return v

    @field_validator("confirmation_window_frames")
    @classmethod
    def _window_frames_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 60):
            raise ValueError("confirmation_window_frames must be between 1 and 60")
        return v


class AlertOut(BaseModel):
    """Matches the /ws/alerts broadcast payload shape."""
    model_config = ConfigDict(from_attributes=True)
    event_id: int
    camera_id: Optional[int] = None
    zone_name: str
    policy_type: str
    risk_score: int
    timestamp: datetime.datetime


EventStatus = Literal["to_review", "coached", "dismissed"]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: Optional[int] = None
    zone_id: Optional[int] = None
    zone_name: str
    policy_type: str
    risk_score: int
    track_id: Optional[int] = None
    raw_payload: dict
    timestamp: datetime.datetime
    status: EventStatus
    has_snapshot: bool
    event_type: Optional[str] = None
    has_clip: bool = False
    vlm_status: str = "none"
    vlm_verdict: Optional[str] = None
    vlm_confidence: Optional[float] = None
    vlm_reason: Optional[str] = None
    vlm_observed: Optional[list] = None
    vlm_model: Optional[str] = None
    vlm_latency_ms: Optional[int] = None
    vlm_error: Optional[str] = None
    verified_at: Optional[datetime.datetime] = None


class EventUpdate(BaseModel):
    status: Optional[EventStatus] = None
    # Reviewer override of the auto-assigned score; level (Low/Medium/High) is derived from it.
    risk_score: Optional[int] = Field(default=None, ge=1, le=10)


class EventBulkUpdate(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    status: EventStatus


# All selectable page keys (route paths) that a non-admin role can be
# granted access to. The Admin menu itself is never in this list -- it's
# always restricted to the built-in Admin role.
PAGE_KEYS = [
    "/",
    "/admin/cameras",
    "/admin/zone-types",
    "/admin/zones",
    "/admin/calibration",
    "/admin/fisheye",
    "/coaching",
    "/incidents/search",
    "/analytics",
    "/heatmap/usage",
    "/heatmap/violations",
]


class RoleBase(BaseModel):
    name: str
    pages: List[str] = []

    @field_validator("pages")
    @classmethod
    def _valid_pages(cls, v: List[str]) -> List[str]:
        unknown = set(v) - set(PAGE_KEYS)
        if unknown:
            raise ValueError(f"Unknown page key(s): {sorted(unknown)}")
        return v


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    pages: Optional[List[str]] = None

    @field_validator("pages")
    @classmethod
    def _valid_pages(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            unknown = set(v) - set(PAGE_KEYS)
            if unknown:
                raise ValueError(f"Unknown page key(s): {sorted(unknown)}")
        return v


class RoleOut(RoleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_system: bool


class UserCreate(BaseModel):
    username: str
    password: str
    role_id: int


class UserUpdate(BaseModel):
    role_id: Optional[int] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role_id: int
    is_system: bool
    must_change_password: bool = False


class PasswordResetRequest(BaseModel):
    new_password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut
    role: RoleOut


class MeResponse(BaseModel):
    user: UserOut
    role: RoleOut


class EventEmailRequest(BaseModel):
    to_address: str
    subject: str
    body: str

    @field_validator("to_address")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("to_address must be a valid email address")
        return v


class EventCommentCreate(BaseModel):
    text: str


class EventCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int
    text: str
    created_at: datetime.datetime


# ------------------------------------------------------------------- sites

SiteType = Literal["hospital", "mall", "other"]
_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    site_type: SiteType
    timezone: str
    after_hours_from: str
    after_hours_to: str
    trading_hours: Optional[dict] = None
    max_stay_hours: Optional[float] = None


class SiteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    site_type: Optional[SiteType] = None
    timezone: Optional[str] = None
    after_hours_from: Optional[str] = Field(default=None, pattern=_HHMM)
    after_hours_to: Optional[str] = Field(default=None, pattern=_HHMM)
    trading_hours: Optional[dict] = None
    max_stay_hours: Optional[float] = Field(default=None, gt=0)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import zoneinfo
            try:
                zoneinfo.ZoneInfo(v)
            except Exception:
                raise ValueError(f"unknown timezone {v!r}")
        return v


# ------------------------------------------------------------- AI verification

VlmProvider = Literal["anthropic", "openai_compatible", "google"]
VlmMode = Literal["off", "annotate", "gate"]


class VlmSettingsOut(BaseModel):
    """Never contains the API key: only whether one is stored and its last 4 characters."""
    model_config = ConfigDict(from_attributes=True)
    enabled: bool
    provider: VlmProvider
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key_set: bool = False
    api_key_last4: Optional[str] = None
    local_only: bool
    timeout_s: float
    max_concurrent: int
    max_calls_per_hour: int
    gate_timeout_s: float
    min_confidence: float
    rejected_retention_days: int
    secret_key_configured: bool = False  # TIAM_SECRET_KEY present -> API keys can be stored


class VlmSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[VlmProvider] = None
    base_url: Optional[str] = Field(default=None, max_length=500)
    model: Optional[str] = Field(default=None, max_length=200)
    # Write-only. Omitted or "" keeps the stored key; use DELETE /api/vlm/settings/api-key to remove it.
    api_key: Optional[str] = Field(default=None, max_length=500)
    local_only: Optional[bool] = None
    timeout_s: Optional[float] = Field(default=None, ge=2, le=120)
    max_concurrent: Optional[int] = Field(default=None, ge=1, le=16)
    max_calls_per_hour: Optional[int] = Field(default=None, ge=1, le=10000)
    gate_timeout_s: Optional[float] = Field(default=None, ge=2, le=60)
    min_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    rejected_retention_days: Optional[int] = Field(default=None, ge=1, le=365)

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, v: Optional[str]) -> Optional[str]:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v or None


class VlmEventTypeOut(BaseModel):
    event_type: str
    label: str
    mode: VlmMode
    prompt_template: str
    is_default_prompt: bool


class VlmEventTypeUpdate(BaseModel):
    event_type: str = Field(min_length=1, max_length=64)
    mode: VlmMode
    prompt_template: Optional[str] = Field(default=None, max_length=8000)  # null = reset to default
