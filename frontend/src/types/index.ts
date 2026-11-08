// Mirrors backend/app/schemas.py and models.py. Keep in sync when those change.

export type Point = [number, number];

// "fisheye_view" = one virtual camera view cut out of a "fisheye" camera
// (no connection settings of its own -- see backend app/fisheye.py).
export type CameraSourceType = "ip" | "webcam" | "fisheye" | "fisheye_view" | "file";
export type CameraProtocol = "rtsp" | "http" | "https";

export interface Camera {
  id: number;
  name: string;
  source_type: CameraSourceType;
  protocol: CameraProtocol | null;
  ip: string | null;
  port: number | null;
  stream_path: string | null;
  device_index: number | null;
  is_enabled: boolean;
  // password is never sent back by the API
  username: string | null;
  // fisheye de-warp calibration -- ratios (0-1), null until calibrated on
  // the Fisheye Setup page. Only meaningful when source_type === "fisheye".
  fisheye_center_x: number | null;
  fisheye_center_y: number | null;
  fisheye_radius_x: number | null;
  fisheye_radius_y: number | null;
  fisheye_inner_radius: number | null;
  // See backend models.Camera.restricted_zone_id -- when set, this
  // camera's live view + detection are restricted to just this one zone.
  restricted_zone_id: number | null;
  // source_type === "fisheye_view" only: the fisheye camera it comes from,
  // and where its virtual camera is aimed (degrees; direction 0 = top of the
  // raw fisheye image, clockwise; tilt 0 = straight down, 90 = horizon).
  fisheye_parent_id: number | null;
  view_direction_deg: number | null;
  view_tilt_deg: number | null;
  view_fov_deg: number | null;
  site_id: number | null;
}

export interface FisheyeViewPayload {
  id?: number;
  name: string;
  direction_deg: number;
  tilt_deg: number;
  fov_deg: number;
}

export interface CameraCreatePayload {
  name: string;
  source_type: CameraSourceType;
  protocol?: CameraProtocol | null;
  ip?: string | null;
  port?: number | null;
  stream_path?: string | null;
  device_index?: number | null;
  username?: string | null;
  password?: string | null;
  is_enabled?: boolean;
}

export interface FisheyeCalibrationPayload {
  fisheye_center_x: number;
  fisheye_center_y: number;
  fisheye_radius_x: number;
  fisheye_radius_y: number;
  fisheye_inner_radius: number;
}

export type CameraStatus = "starting" | "connected" | "reconnecting" | "stopped" | "error";

export interface CameraStatusResponse {
  status: CameraStatus;
  last_error: string | null;
}

export type AppliesTo = "person" | "vehicle" | "both";

export interface ZoneTypeRules {
  applies_to: AppliesTo;
  rule_exclusion: boolean;
  default_max_speed_kmh: number | null;
  rule_stop_required: boolean;
  default_stop_min_seconds: number;
  rule_prowling: boolean;
  default_prowling_min_vehicles: number; // score needed to alert, see analytics/car_prowling.py
  time_restriction_enabled: boolean;
  default_from_time: string | null;
  default_to_time: string | null;
}

export interface ZoneType extends ZoneTypeRules {
  id: number;
  name: string;
  description: string | null;
  is_system: boolean;
}

export interface ZoneTypeCreatePayload extends ZoneTypeRules {
  name: string;
  description?: string | null;
}

export interface ZoneRulesInput {
  applies_to: AppliesTo;
  rule_exclusion: boolean;
  max_speed_kmh: number | null;
  rule_stop_required: boolean;
  stop_min_seconds: number;
  rule_prowling: boolean;
  prowling_min_vehicles: number;
  time_restriction_enabled: boolean;
  from_time: string | null;
  to_time: string | null;
}

export interface Zone extends ZoneRulesInput {
  id: number;
  camera_id: number;
  zone_type_id: number | null;
  name: string;
  polygon_points: Point[];
}

// zone_type_id is required; the rule fields are optional overrides -- if
// omitted, the backend copies them from that zone type.
export interface ZoneCreatePayload extends Partial<ZoneRulesInput> {
  camera_id: number;
  zone_type_id: number;
  name: string;
  polygon_points: Point[];
}

export interface Calibration {
  id: number;
  camera_id: number;
  name: string;
  // 2 points = reference line; 4 = rectangle corners in order (perspective-correct)
  line_points: Point[];
  real_world_meters: number; // line length, or rectangle side 1->2
  real_world_width_m: number | null; // rectangle side 2->3
  pixels_per_meter: number;
  is_active: boolean;
}

export type EventStatus = "to_review" | "coached" | "dismissed";

// Persisted alert row shape (backend/app/models.py Event / schemas.py EventOut).
export interface Event {
  id: number;
  camera_id: number | null;
  zone_id: number | null;
  zone_name: string;
  policy_type: string;
  risk_score: number;
  track_id: number | null;
  raw_payload: Record<string, unknown>;
  timestamp: string;
  status: EventStatus;
  has_snapshot: boolean;
  event_type: string | null; // machine type, e.g. "exclusion"; policy_type is the human label
  has_clip: boolean; // raw clip + box overlay (ADR 0008)
}

// GET /api/events/{id}/clip-overlay: boxes per clip frame, in `width` x `height` pixels
export interface ClipOverlay {
  width: number;
  height: number;
  start_ts: number;
  frames: { t: number; boxes: { id: number; cls: string; xyxy: number[]; conf: number | null; threat: boolean }[] }[];
}

export interface EventComment {
  id: number;
  event_id: number;
  text: string;
  created_at: string;
}

// Exact shape broadcast over /ws/alerts (backend/app/schemas.py AlertOut).
export interface AlertPayload {
  event_id: number;
  camera_id: number | null;
  zone_name: string;
  policy_type: string;
  event_type: string | null;
  risk_score: number;
  timestamp: string;
}

export interface HeatmapOption {
  value: string;
  label: string;
}

export interface HeatmapGridResponse {
  rows: number;
  cols: number;
  grid: number[][];
  max_count: number;
}

export interface BreachByDay {
  date: string;
  count: number;
}

export interface RiskByPolicy {
  policy_type: string;
  avg_risk: number;
  count: number;
}

export interface CameraLeaderboardEntry {
  camera_id: number;
  camera_name: string;
  total_events: number;
  avg_risk: number;
}

// -------------------------------------------------------- auth / roles / users

// Route paths that a non-admin role can be granted access to. Keep in sync
// with backend/app/schemas.py PAGE_KEYS. The Admin menu is never in this
// list -- it's always restricted to the built-in Admin role.
export const PAGE_KEYS = [
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
] as const;

export const PAGE_LABELS: Record<string, string> = {
  "/": "Live Monitor",
  "/admin/cameras": "Cameras",
  "/admin/zone-types": "Zone Types",
  "/admin/zones": "Zone Studio",
  "/admin/calibration": "Calibration Tool",
  "/admin/fisheye": "Fisheye Setup",
  "/coaching": "Incidents",
  "/incidents/search": "Incident Search",
  "/analytics": "Analytics & Reports",
  "/heatmap/usage": "Usage Heatmap",
  "/heatmap/violations": "Violations Heatmap",
};

export interface Role {
  id: number;
  name: string;
  pages: string[];
  is_system: boolean;
}

export interface RoleCreatePayload {
  name: string;
  pages: string[];
}

export interface User {
  id: number;
  username: string;
  role_id: number;
  is_system: boolean;
  must_change_password: boolean;
}

export interface UserCreatePayload {
  username: string;
  password: string;
  role_id: number;
}

export interface LoginResponse {
  token: string;
  user: User;
  role: Role;
}

// ---------------------------------------------------------- detection settings

export interface DetectionSettings {
  person_confidence: number;
  car_confidence: number;
  truck_confidence: number;
  person_min_aspect_ratio: number;
  detector_imgsz: number;
  confirmation_min_observations: number;
  confirmation_window_frames: number;
  ignore_person_shadows: boolean;
  detector_model: string;
}

export type DetectionSettingsUpdatePayload = Partial<DetectionSettings>;

// ------------------------------------------------------------------ sites / system

export type SiteType = "hospital" | "mall" | "other";

export interface Site {
  id: number;
  name: string;
  site_type: SiteType;
  timezone: string;
  after_hours_from: string; // "HH:MM"
  after_hours_to: string;
  trading_hours: Record<string, [string, string]> | null;
  max_stay_hours: number | null;
}

export interface CameraMetrics {
  camera_id: number;
  status: CameraStatus;
  fps: number;
  process_ms: number;
  frames: number;
  incidents: number;
  stream_queue: number;
}

export interface SystemMetrics {
  cameras: CameraMetrics[];
  gpus: { name: string; memory_used_mb: number; memory_total_mb: number; utilization_pct: number }[];
  models_loaded: string[];
  data_folders: Record<string, number>; // MB
  disk_free_gb: number;
  disk_total_gb: number;
  verification_queue: number | null;
}
