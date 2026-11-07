# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Also read `CHANGELOG.md`** -- a dated log of recent feature work (what changed, why, how it was
verified, and open follow-ups / production caveats) that this file only summarises.

## What this app is

> **`retail-parking` branch = "Tiam"**, the conversion of the factory system (on `main`, DB
> `SecurityCamera` -- never touch either) into a car-park / shopping-mall monitor (DB
> `RetailParkingMonitor`). Removed on this branch (2026-11-08): PPE / hi-vis / reflective stripes
> (+ `ppe_model.pt`), pedestrian-vehicle separation with Walkway / Barrier zones and the
> obstruction check, stationary-vehicle suppression, the forklift model. Zone rules left:
> exclusion, speed limit, stop required, time window. This file describes the branch as it is now;
> CHANGELOG.md has the history.

"Tiam" (formerly "APL Security Monitor") — a self-hosted security-camera monitoring system with
real-time object detection (person/vehicle), zone-based rules (exclusion zones, speed limits,
stop-required zones, time-of-day restrictions), live streaming, alerting, heatmaps, and an
incident-review workflow. Two independent apps in one repo:

- `backend/` — FastAPI + SQLAlchemy + YOLO (ultralytics) + OpenCV, talks to SQL Server.
- `frontend/` — React 19 + TypeScript + Vite + Tailwind, talks to the backend over REST + WebSockets.

They are developed and run independently (no monorepo tooling, no shared package). Run both when
testing an end-to-end change.

---

# BACKEND (`backend/`)

## Stack

FastAPI, Python 3.12, SQLAlchemy 2.0 (`Mapped`/`mapped_column` style), SQL Server via
`mssql+pyodbc`, `ultralytics.YOLO` for detection, `supervision` (`sv.ByteTrack`, `sv.Detections`)
for tracking/NMS, OpenCV for capture/annotation. No pyproject.toml — deps are in
`backend/requirements.txt` (unpinned except `supervision<0.31` -- 0.31 removed `sv.ByteTrack`).
Install CUDA PyTorch **before** requirements.txt, or ultralytics pulls the CPU-only build and the
hardcoded `device="cuda"` fails.

## Commands

No linter config and no CI. Tests: `backend/tests/` (pytest; no GPU or DB needed – the detection
engine is faked) plus `scripts/verify_logic.py`.

```bash
# setup (from backend/)
python -m venv venv
venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
venv\Scripts\pip install -r requirements.txt

# secret-encryption key for stored API keys (once per dev machine; PowerShell, new terminal after):
#   [Environment]::SetEnvironmentVariable("TIAM_SECRET_KEY", (venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"), "User")

# run (from backend/)
venv\Scripts\uvicorn app.main:app --reload

# tests (from backend/)
venv\Scripts\python -m pytest -q tests
venv\Scripts\python scripts\verify_logic.py
venv\Scripts\python scripts\replay.py --make-demo          # synthetic demo clip, scored
venv\Scripts\python scripts\replay.py data\retail_test_clips\<name>.yaml   # see docs/test_clips.md
```

Never run test servers against `RetailParkingMonitor` you care about: create a throwaway `Tiam_*`
DB and point `SECURITYCAM_DATABASE_URL` at it (they still write into `backend/data/retail_*`).

- No `pytest` suite exists. `backend/scripts/` has standalone manual/integration scripts run
  directly with `python scripts/<name>.py` (e.g. `test_multi_camera.py` spins up a `TestClient`
  against real cameras/websockets and just prints/asserts — not wired to a runner).
- No Alembic. Tables are created via `Base.metadata.create_all()` in `main.py` at startup. Columns
  added after initial deployment are patched on via a hand-rolled `_add_missing_columns()` in
  `main.py`, which runs raw `ALTER TABLE ... ADD` statements guarded by
  `INFORMATION_SCHEMA.COLUMNS` checks. **When adding a new model column, add it to the model AND to
  `_add_missing_columns()`** or existing databases won't pick it up.

## Architecture

### Entry point & wiring

`app/main.py` builds the FastAPI `app`, runs `create_all` + `_add_missing_columns` +
`crud.seed_default_zone_types` + `crud.seed_default_admin` on startup, calls `camera_manager.start_all()` on startup / `stop_all()` on
shutdown, and runs a background `_pump_alerts` task that drains the shared alert queue onto the
`/ws/alerts` broadcaster.

Routers are mounted with `dependencies=[Depends(auth.get_current_user)]` (i.e. login required) for
everything except `auth` (login itself) and `GET /api/health`. `users` and `roles` additionally
gate on `Depends(auth.require_admin)` at the router level.

### Database schema (`app/models.py`)

- **Camera** (`cameras`) — `id, name, source_type("ip"|"webcam"|"fisheye"|"fisheye_view"|"file"), protocol("rtsp"|"http"|
  "https")?, ip?, port?, stream_path?, username?, password?` (plaintext camera creds),
  `device_index?, is_enabled(bool, default True)`, plus fisheye de-warp calibration (only
  meaningful when `source_type == "fisheye"`, null until calibrated on the Fisheye Setup page):
  `fisheye_center_x?, fisheye_center_y?, fisheye_radius_x?, fisheye_radius_y?` (all ratios 0-1 of
  the *raw* camera frame's width/height — the lens circle is modelled as an ellipse, not assumed
  perfectly round) and `fisheye_inner_radius?` (ratio 0-1 of the outer radius, to exclude the area
  directly under the camera). See "Fisheye camera de-warping" below.
  `restricted_zone_id?` (plain INT, not a FK -- SQL Server rejects the cameras<->zones cascade
  cycle; `crud.delete_zone` nulls it) — when set, this camera's
  live view *and* detection are both restricted to just that one zone (masked + cropped to its
  polygon before the detector ever runs), rather than the normal full-frame detect + filter-by-
  zone-membership. See "Zone-only camera view" below.
  `fisheye_parent_id?` (plain INT, deliberately **not** a ForeignKey -- SQL Server rejects
  self-referencing cascades), `view_direction_deg?, view_tilt_deg?, view_fov_deg?` — only for
  `source_type == "fisheye_view"`: a virtual view cut out of the parent `"fisheye"` camera, with no
  connection settings of its own. See "Fisheye views" below.
  `source_type == "file"`: `stream_path` is a file name inside `backend/data/retail_test_clips`
  (validated: no paths outside it), read in a loop at the file's own fps – for tests and demos.
  `site_id?` (plain INT → `sites`, assigned to the default site by `crud`).
- **Site** (`sites`) — `id, name, site_type(hospital|mall|other), timezone (Pacific/Auckland),
  after_hours_from/to ("20:00"/"06:00", the night window), trading_hours? (JSON), max_stay_hours?`.
  One server per site (ADR 0004): one default row is seeded (`crud.seed_default_site`).
- **ZoneType** (`zone_types`) — reusable rule presets. `id, name, description?, applies_to("person"|
  "vehicle"|"both", default "person"), rule_exclusion(bool), default_max_speed_kmh?,
  rule_stop_required(bool), default_stop_min_seconds(default 1.0), time_restriction_enabled(bool),
  default_from_time?("HH:MM"), default_to_time?("HH:MM"), is_system(bool)` (seeded types are
  non-deletable). Seeded: Pedestrian Exclusion, Vehicle Exclusion, Vehicle Speed Limit 10/15 km/h,
  Vehicle Stop Required.
- **Zone** (`zones`) — per-camera drawn zone. `id, camera_id`→cameras (CASCADE), `zone_type_id`→
  zone_types (SET NULL, optional), `name, polygon_points`(JSON `[[x,y],...]`), plus the same rule
  fields as ZoneType minus the "default_" prefix (`applies_to, max_speed_kmh, rule_exclusion,
  rule_stop_required, stop_min_seconds, time_restriction_enabled, from_time?, to_time?`).
- **Calibration** (`calibrations`) — `id, camera_id`→cameras (CASCADE), `name, line_points`(JSON,
  2 points = reference line, or 4 = ground-rectangle corners in order, convexity validated in
  `schemas`), `real_world_meters(default 1.0)` (line length / rectangle side 1→2),
  `real_world_width_m?` (rectangle side 2→3), `pixels_per_meter`(derived = first segment's pixel
  length / real_world_meters), `is_active(bool)` — only one active calibration per camera, enforced
  in `crud.activate_calibration`. A 4-point calibration becomes a homography
  (`config_loader.ground_homography`, image → ground metres) on `CalibrationConfig.homography`.
- **Event** (`events`) — a fired alert/incident. `id, camera_id?, zone_id?, zone_name, policy_type`
  (human-readable, from `risk.score_event`), `event_type` (machine type, e.g. `exclusion`),
  `has_clip` (raw clip + overlay, see "Incident pipeline and clips"), `risk_score(int 1-10), track_id?`, `raw_payload`(JSON, full vision-engine
  event dict), `timestamp, status("to_review"|"coached"|"dismissed"), has_snapshot(bool)`.
  **Dismissing deletes the event** (row + comments + snapshot JPEG in
  `backend/data/retail_event_snapshots/{id}.jpg`) rather than storing `status="dismissed"`, so "dismissed"
  should never be persisted any more; `crud.get_events` with no status filter also excludes any
  leftover `dismissed` rows (e.g. from a server not yet upgraded).
- **Role** (`roles`) — `id, name(unique), pages`(JSON list of allowed frontend route keys, see
  `schemas.PAGE_KEYS`), `is_system(bool)` (the built-in "Admin" role bypasses the `pages` allowlist
  entirely).
- **User** (`users`) — `id, username(unique), password_hash, password_salt, role_id`→roles,
  `is_system(bool)` (seeded "admin" user).
- **UserSession** (`user_sessions`) — `token`(PK, bearer token), `user_id`→users (CASCADE),
  `created_at`. **No expiry field — sessions never expire automatically.**
- **HeatmapCell** (`heatmap_cells`) — `id, camera_id`→cameras (CASCADE), `day`("YYYY-MM-DD"),
  `metric`(class name like "person"/"car"/"truck", or "violation:<event_type>"),
  `grid_row, grid_col, count`. Unique on (camera_id, day, metric, grid_row, grid_col). Grid is fixed
  25 rows × 40 cols (`app/heatmap.py`).
- **EventComment** (`event_comments`) — `id, event_id`→events (CASCADE), `text, created_at`.
- **DetectionSettings** (`detection_settings`) — singleton row (id 1, created with defaults by
  `crud.get_detection_settings`): `person_confidence, car_confidence, truck_confidence` (0.2; bus/
  motorcycle use car's), `person_min_aspect_ratio` (1.2), `detector_imgsz` (960),
  `confirmation_min_observations` (3) / `confirmation_window_frames` (6), `ignore_person_shadows`
  (true), `detector_model` ("yolov8s.pt"; choices from `detection_engine.available_models`). Saving
  restarts every camera worker.

### API surface (all under `/api`, all require login unless noted)

| Router | Path prefix | Notes |
|---|---|---|
| `auth.py` | `/api/auth` | `POST /login` (no auth), `POST /logout`, `GET /me` |
| `cameras.py` | `/api/cameras` | CRUD + `GET /{id}/status`, `POST /{id}/restart`. Create/update/delete all call `camera_manager.on_camera_changed`/`on_camera_removed` to hot start/stop the worker (deleting a fisheye camera also deletes its views). Fisheye: `GET|PUT /{id}/fisheye-views`, `POST /{id}/fisheye/detect-circle`. |
| `camera_feed.py` | `/api/camera` | `GET /snapshot?camera_id=` — latest de-warped/clean JPEG from the live worker (503 if none yet). `GET /snapshot-raw?camera_id=` — fisheye cameras only: the still-circular pre-de-warp frame, used by Fisheye Setup. `GET /fisheye-view-preview?camera_id=&direction=&tilt=&fov=[&cx&cy&rx&ry]` — 640×360 render of one virtual view |
| `zones.py` | `/api/zones` | CRUD, optional `?camera_id=` filter on list; writes restart the affected camera's worker |
| `zone_types.py` | `/api/zone-types` | CRUD; delete blocked (400) if `is_system` |
| `calibration.py` | `/api/calibration` | CRUD + `GET /active?camera_id=`, `POST /{id}/activate` (deactivates siblings) |
| `events.py` | `/api/events` | `GET ""` (filter by status/camera_id, paginated; no status = everything except dismissed), `PATCH /{id}` (status; `"dismissed"` hard-deletes via `delete_events_and_snapshots`), `POST /bulk-status` (`{ids[], status}`, max 1000; `"dismissed"` deletes snapshot + clip too), `GET /{id}/snapshot`, `GET /{id}/clip` (mp4), `GET /{id}/clip-overlay` (JSON boxes), `POST /{id}/email` (Azure email, 503 if unconfigured), `GET|POST /{id}/comments` |
| `incidents.py` | `/api/incidents` | `GET /search?q=` — natural-language search ("speeding on Gate 2 last week", "over 20 km/h"): `incident_search.parse_query` extracts rule type, camera, dates and a min speed |
| `detection_settings.py` | `/api/detection-settings` | admin: `GET ""`, `PUT ""` (restarts all workers), `GET /models` |
| `sites.py` | `/api/sites` | `GET ""`; `PUT /{id}` (admin) |
| `system.py` | `/api/system` | admin: `GET /metrics` (per-camera fps / ms per frame / incidents, GPU via pynvml, `data/retail_*` sizes, disk) |
| `analytics.py` | `/api/analytics` | `GET /breaches-by-day`, `/risk-by-policy`, `/camera-leaderboard` |
| `heatmap.py` | `/api/heatmap` | `GET /usage-options`, `/violation-options`, `/usage`, `/violations` (all return `{rows, cols, grid, max_count}`) |
| `users.py` | `/api/users` | **admin-only**, CRUD + reset-password |
| `roles.py` | `/api/roles` | **admin-only**, CRUD + `GET /pages` (returns `PAGE_KEYS`) |

Plus in `main.py` directly: `GET /api/health` (no auth), `WS /ws/stream/{camera_id}?token=` (binary
JPEG frames), `WS /ws/alerts?token=` (JSON alert broadcast). WebSockets take the bearer token as a
`?token=` query param (can't set headers on WS) and close with code 1008 if invalid.

### Camera worker / detection pipeline (`app/camera_manager.py` + `app/vision_engine.py`)

One daemon-thread `_CameraWorker` per **enabled** camera, each with its own `VisionEngine` instance
(own tracker/history so state never leaks across cameras), a bounded `asyncio.Queue` (maxsize=2,
drop-oldest) feeding its `/ws/stream/{id}` connections, and pushing onto one shared `alert_queue`.
`camera_manager.start_all()` runs at app startup and **skips disabled cameras**; any Camera/Zone/
Calibration write calls `on_camera_changed`, which fully stops and (if `is_enabled`) restarts the
worker — there is no hot-reload of zones/calibration into a running worker, only full restart.

Key constants (`camera_manager.py`): `TARGET_FPS=18`, `FRAME_QUEUE_MAXSIZE=2`,
`RECONNECT_DELAY_S=3.0`, `HEATMAP_FLUSH_INTERVAL_S=30.0`, `FRAME_SIZE=(960,540)` (fixed — all
zones/calibration/streaming operate in this coordinate space), `STREAM_JPEG_QUALITY=92`. The
detector + tracker run on every processed frame.

Worker loop: every camera is read by a `_SharedCapture` thread (`cv2.VideoCapture` on the
camera's RTSP/HTTP URL, basic-auth embedded, or webcam index) that reads as fast as the camera
sends and keeps only the **newest** frame plus its arrival time; the worker processes that frame
and passes the arrival time to `VisionEngine.process_frame(frame, ts)` -- so a worker slower than
the camera skips frames (no growing live-view lag) and speed uses capture time, not processing
time. Status cycles `starting → connected → reconnecting/error → stopped`. A bad camera never
crashes other workers or the app (top-level `except Exception` sets status="error" and retries after
`RECONNECT_DELAY_S`). `last_error` has credentials redacted before being exposed via
`GET /{id}/status`. Per frame: resize to `FRAME_SIZE`, keep a clean copy for `/snapshot`, run
`VisionEngine.process_frame()` → `(annotated_frame, events)`, JPEG-encode and push to
the stream queue, record per-track Usage Heatmap hits, dedupe ongoing breaches into single incidents
via `_IncidentTracker` (keyed by `_incident_key()`: zone_id + type + track_id — fires once per breach, not once per frame; an incident only ends
after `INCIDENT_COOLDOWN_S`=60s without firing, and a *new* track id appearing near an open
incident of the same zone+rule is merged into it, since that's usually the same person re-acquired
by the tracker after an occlusion; ByteTrack's `lost_track_buffer` is also raised to 90 frames
≈5s for the same reason), persist via
`crud.create_event` + save the annotated frame as the event snapshot, push an alert payload onto
`alert_queue`. Heatmap counts are buffered in-memory and flushed to DB every 30s, not per-frame.

**`VisionEngine.process_frame` pipeline** (`vision_engine.py`):
1. Main YOLO detector (`yolov8s.pt`, conf=0.2, `device="cuda"`) runs on the full frame every frame.
   Per-class confidence floors (`_filter_by_class_confidence`) and `_filter_implausible_person_boxes`
   (box height/width below `person_min_aspect_ratio`, e.g. bins) are applied next. The detector is
   never downscaled -- that caused small/distant people to be missed.
2. `_dedup_vehicle_detections`: class-agnostic NMS (IoU 0.5) + a second custom containment-suppression
   pass (`_suppress_contained_boxes`, threshold 0.7, based on intersection-over-smaller-box-area
   rather than IoU), restricted to vehicle-kind boxes — catches one vehicle boxed twice (e.g. car + truck, or
   cab + whole truck: low IoU but high containment).
   Then `_filter_person_shadows` (Detection Settings "Ignore human shadows", default on): a
   "person" box touching another person box is dropped if it's only floor + darkened floor
   (hue-matched against a ring of floor around it, `SHADOW_*` constants) -- the person's shadow,
   which the detector often boxes as a second person. Kept if its neighbour is shadow-like too.
3. Tracking via `sv.ByteTrack`, with `track_activation_threshold` explicitly lowered to
   `max(0.05, detection_conf - 0.1)` — ByteTrack's default silently drops any detection scoring
   between 0.2 and 0.35 before it can become a track, which is exactly the confidence band typical
   for distant/occluded people (also part of commit `2ad6275`).
4. Classes used: COCO `person`, plus configured `vehicle_class_names = ["car","truck","bus",
   "motorcycle"]`; anything else is `kind="other"` and dropped.
5. Zone rules (`ZoneRules` in `app/config.py`): `exclusion, speed_limit_kmh, stop_required,
   stop_min_seconds, applies_to, time_restriction_enabled, from_time?, to_time?`. `ZoneRules.is_active_at(ts)` checks whether "now" falls in
   `[from_time, to_time]` (HH:MM local time), supporting overnight wraparound (e.g. 22:00→06:00 when
   `from > to`). `_apply_rules` checks this before evaluating any rule — a time-windowed rule outside its window is fully skipped (no alert, no
   event), whichever type of rule it is.
6. Speed: per-track history of ground points trimmed to the last `speed_window_s` (1.5 s; a sample
   identical to the previous one is skipped -- a repeated frame, not a measurement),
   mapped to ground metres via `CalibrationConfig.ground_points` (with a 4-point calibration,
   perspective-correct anywhere in the frame; points at/above the horizon fall back to the flat
   scale; otherwise pixel × `meters_per_pixel` = 1 / active `pixels_per_meter`, default
   placeholder 0.02 m/px if uncalibrated), then a Theil-Sen velocity (median of all pairwise
   velocities, `_speed_kmh`), so box jitter and jumps don't drag it up. Only reported once samples span 70% of the window (≥3 samples).
   Stop-required zones: "stopped" = ground point stayed within `STOP_MAX_DRIFT_M` (0.5 m) of one
   spot for `stop_min_seconds` (position, not per-frame speed, so a jittery box doesn't reset it);
   `failed_to_stop` fires once, when the track leaves the zone without having stopped.
7. Drawing: boxes + labels (`#id class confidence [speed]`) in amber (`BOX_NORMAL`), red with a
   white label for tracks with an alert (`BOX_THREAT`), plus a red alert banner.

Zones/calibration are loaded per-camera from the DB via `config_loader.load_zones_from_db`/
`load_calibration_from_db`, called once in `VisionEngine.refresh_from_db()` at worker start.

### Incident pipeline, clips, detectors (phase 1 of the car-park spec)

- **Detection engine** (`app/detection_engine.py`, ADR 0007): `VisionEngine` only talks to a
  `DetectionEngine` (`predict(frame, conf, imgsz, device) -> sv.Detections`, `class_names`).
  `load_engine(model)` shares one engine per weights file across cameras. Only `UltralyticsEngine`
  exists (AGPL – licence decision before first sale); a non-AGPL engine just implements the same two
  members. Tests replace `vision_engine.load_engine` with a fake.
- **Detectors** (`app/analytics/__init__.py`, spec 5.1): `Detector` protocol (`name`, `event_types`,
  `update(FrameContext) -> [candidate event]`, `prune(live_track_ids)`). `VisionEngine(config,
  detectors=[...])` runs them after the built-in zone rules (`_run_detectors`); `key_track_ids` in an
  event marks those tracks as threats (red boxes). No network, no heavy models inside `update`.
- **Incident pipeline** (`app/incident_pipeline.py`): after `_IncidentTracker` confirms an incident,
  `IncidentPipeline.handle_frame` persists it (`crud.create_event`, sets `event_type`), writes the
  snapshot, starts the clip and calls `_route` → `AlertDispatcher.dispatch` (today: `/ws/alerts`).
  `_route` is where phase 2's AI verification plugs in.
- **Clips** (`app/clips.py`, ADR 0008): per worker a `FrameRing` keeps the last 10 s of clean frames at
  5 fps (JPEG + the boxes on that frame). On an incident a `ClipRecorder` collects 10 s more, then a
  background thread writes `data/retail_event_clips/{id}.mp4` (raw H.264 via PyAV/libx264, real
  capture timing, **millisecond time base for encoder and frames** – a 1/5 s encoder time base or the
  muxer-changed stream time base made the mp4 muxer fail with error 22 on uneven frame times) and
  `{id}.json` (per-frame boxes), then sets `has_clip`. Constants `CLIP_PRE_S/POST_S/FPS`.
- **Metrics**: `_CameraWorker.metrics` (EMA fps, ms per frame, frames, incidents) → `GET /api/system/metrics`.
- **Secrets** (`app/secrets_store.py`): Fernet with env `TIAM_SECRET_KEY` only (no fallback;
  `available()` False → refuse to store). `install.ps1` generates it into `config.ps1`,
  `start-server.ps1` exports it.
- **Replay harness** (`scripts/replay.py`): video + YAML (zones, ground truth) through the real
  `VisionEngine` + `_IncidentTracker` using video time; prints precision/recall per event type.

### Zone-only camera view

`EngineConfig.restrict_to_zone_id` (set from `Camera.restricted_zone_id` in
`camera_manager._CameraWorker._build_engine`) restricts **detection only** to a single zone — the
live view stays full-frame. In `VisionEngine.process_frame`, right after the frame is resized to
`FRAME_SIZE`, the target zone's polygon is used to mask out everything else (`cv2.fillPoly` +
`bitwise_and`) and that masked copy is cropped to the polygon's bounding box (`cv2.boundingRect`)
into a separate `detect_frame`, fed to the detector instead of the full frame — so nothing outside
the zone is ever detected, not just filtered out afterwards. `annotated` (what's streamed/
snapshotted/used for the heatmap) is a copy of the *original, unmasked, uncropped* frame, so the
user can still see the whole camera view live; only the area outside the zone never gets a
box/alert drawn on it, since nothing was ever detected there. Detections coming back from
`detect_frame` are in that crop's coordinate space; right after the detections are
deduped (and before `tracker.update_with_detections`), they're shifted back to full-frame
coordinates by `self._restrict_offset` — from that point on (tracking, zone membership,
drawing, `_apply_rules`), everything operates in the same full-frame space as an unrestricted
camera, with no separate "restricted zone polygons" needed anywhere. `VisionEngine.
_recompute_restriction()` (called on load and on every `refresh_from_db()`) precomputes just the
crop offset/size — falls back to normal full-frame behaviour (detection included) if the configured
zone id doesn't match any currently-loaded zone (e.g. it was deleted). `VisionEngine.
output_frame_size` always equals `config.frame_size` now (never a cropped size); `camera_manager`
still reads it (rather than `engine.config.frame_size` directly) for the Usage/Violations Heatmap
grid mapping, which is now always in full-frame space regardless of restriction. Zone Studio and
Calibration Tool are unaffected either way — their camera snapshot (`GET /api/camera/snapshot`) is
captured from the full unrestricted frame *before* `VisionEngine.process_frame` runs, so you can
always see and edit the full camera view (including picking which zone to restrict to, via the Crop
icon next to a zone in Zone Studio's "Existing zones on this camera" list) regardless of the live
detection restriction.

### Fisheye camera de-warping

A `source_type="fisheye"` camera connects exactly like an "ip" camera (same protocol/ip/port/
stream_path/credentials) but its raw frame is a circular (modelled as elliptical) fisheye image.
`_CameraWorker._run()` in `camera_manager.py`, right after `cap.read()` and before the existing
resize-to-`FRAME_SIZE` step: (1) JPEG-encodes the still-circular raw frame into
`worker.last_fisheye_raw_jpeg` (served by `GET /api/camera/snapshot-raw`, consumed only by the
Fisheye Setup page), then (2) if the camera has been calibrated (`fisheye_center_x`/`radius_x` not
null), reassigns `frame` to the output of `cv2.remap()` using lookup maps from
`_build_fisheye_maps()`, built once per worker (lazily, on first frame, then cached in
`worker._fisheye_maps`) directly at `FRAME_SIZE` (960×540). Everything downstream — the snapshot
endpoint, `VisionEngine.process_frame`, zones, calibration, `/ws/stream/{id}` — is completely
unaware a dewarp happened; it just sees a normal rectangular frame, which is what makes zones/
detection/live-view "just work" on a fisheye camera once calibrated.

`_build_fisheye_maps` performs a **rectilinear** correction (the same approach as the `defisheye`
Python library), not a polar/panorama unwrap: it treats the calibrated ellipse edge as the point
where the lens reaches 90° off its optical axis (`FISHEYE_SRC_THETA_MAX`, a ~180° circular fisheye,
the norm for this kind of lens) and derives a per-axis source focal length
`fx_src = fisheye_radius_x*src_w / (π/2)` (same for `fy_src`). For every output pixel it computes
the ray angle off-axis (`theta`) and azimuth (`phi`) a standard pinhole camera would see, then
samples the source at `r_src = f_src * theta` along that azimuth (the equidistant "f-theta" fisheye
model) — i.e. it straightens barrel curvature into a normal flat view, rather than unrolling the
disk into a 360° strip. A rectilinear projection can't represent a full 180° hemisphere (the math
diverges at 90° off-axis), so the output field of view is always kept below that, controlled by
`fisheye_inner_radius` (repurposed as a 0-1 "zoom" knob, not a literal geometric inner-radius
exclusion): 0 → `FISHEYE_OUT_HFOV_MIN_DEG` (70°, tightest/least-curved crop), 1 →
`FISHEYE_OUT_HFOV_MAX_DEG` (150°, widest view with more residual stretching near the edges). An
uncalibrated fisheye camera (no `fisheye_radius_x` set) is streamed/detected-on unmodified (still
circular) until calibrated. Worker restart (via the existing `on_camera_changed` hook, triggered by
any camera PUT) is what picks up a new calibration — there's no hot-reload.

#### Fisheye views (split one fisheye into several cameras)

The whole-lens de-warp above is of limited use for a ceiling-mounted fisheye (looking straight
down, everything near the lens edge -- aisles, walls, people -- gets stretched). The main use is
instead **fisheye views** (`app/fisheye.py`): `source_type="fisheye_view"` camera rows with
`fisheye_parent_id` → the physical `"fisheye"` camera (a plain int, *not* a ForeignKey, because SQL
Server rejects self-referencing cascades -- `crud.delete_camera` deletes a parent's views itself and
returns every deleted id) plus `view_direction_deg` (0 = top of the raw image, clockwise),
`view_tilt_deg` (0 = straight down, 90 = horizon) and `view_fov_deg`. Each view is a virtual
pinhole camera at the lens centre, aimed by those angles and flattened on its own with the
equidistant 180° model (`fisheye.build_view_maps`), output at `FRAME_SIZE` -- so it behaves exactly
like a normal camera everywhere else (its own zones, calibration, detection, Live Monitor tile,
events). Defaults: 4 views at directions 315/45/135/225 (the raw image's diagonals), tilt 55°,
FOV 95°.

A fisheye camera and all its views share **one** connection via `camera_manager._SharedCapture`
(ref-counted `_acquire_capture`/`_release_capture`, started by whichever worker needs it first),
so 4 views = 1 RTSP stream, 1 decode. `_CameraWorker._frames()` yields (frame, arrival time)
from that (every camera type reads through one); `_dewarp()` applies the whole-lens or per-view remap (tables built on
the first frame); `_process_frame()` is the detect/stream/persist step. The raw circular JPEG
(`GET /api/camera/snapshot-raw`) comes from the shared capture, so it's available while the
camera *or any of its views* is running. `on_camera_changed` on a fisheye parent also restarts its
views (they use its circle calibration) and force-reconnects the shared capture. A view whose
parent has no saved circle auto-detects it (`fisheye.detect_lens_circle`, fits an ellipse to the
bright lens image against the black surround).

API: `GET|PUT /api/cameras/{id}/fisheye-views` (PUT replaces the whole set: listed ids updated,
new ones created, the rest deleted; the first time views are created on an enabled parent, the
parent is disabled so alerts aren't raised twice), `POST /api/cameras/{id}/fisheye/detect-circle`
(returns the detected circle, doesn't save), `GET /api/camera/fisheye-view-preview?camera_id=&
direction=&tilt=&fov=[&cx&cy&rx&ry]` (640×360 JPEG of one view from the latest raw frame).

The frontend's `pages/FisheyeSetup.tsx` (route `/admin/fisheye`, nav icon `Aperture`): (1) lens
circle -- raw snapshot at its *native* resolution (no aspect stretch, which would distort the
ellipse), Auto-detect button or drag a box (corner-resize, move), with coloured spokes showing
where each view points; (2) views -- one card per view with name, live server-rendered preview
(debounced) and Direction/Tilt/Zoom sliders, "Default 4 views", "Add view" (max 8). "Save views"
saves an edited circle first (`PUT /api/cameras/{id}`), then the views.

### Alerting

`_apply_rules(tracks, ts)` returns raw event dicts (`type: exclusion|speeding|failed_to_stop`
+ type-specific fields). `risk.score_event()` converts this to a human `policy_type` string + a
1-10 `risk_score` (exclusion=7, failed_to_stop=6, speeding scaled by how far over the limit). `crud.create_event` persists it; camera_manager builds an alert payload
(`crud.to_alert_payload`) and pushes it onto the shared queue; `main.py`'s `_pump_alerts` task
broadcasts it live to every `/ws/alerts` client. **There is no automatic email/webhook
notification** — email (`app/email_service.py`, Azure Communication Services) is only sent
on-demand via `POST /api/events/{id}/email` from the Coaching Workbench UI.

### Auth (`app/auth.py`)

Custom DB-backed bearer-token sessions — no JWT/OAuth. Passwords: `hashlib.pbkdf2_hmac("sha256",
..., iterations=260_000)` + random 16-byte salt, verified with `secrets.compare_digest`. Login
issues a random 32-byte token stored in `UserSession` (no expiry, no cleanup job — sessions are
forever until explicit logout/deletion). `auth.require_admin` checks `Role.is_system`. **RBAC is
page-based and frontend-enforced only** — `Role.pages` gates which routes the SPA shows/allows; the
backend itself only distinguishes "any authenticated user" vs "admin" (`/api/users`, `/api/roles`).
No rate limiting, no lockout, no CSRF (pure bearer-token API, no cookies).
`User.must_change_password`: while set, `get_current_user` returns 403 `password_change_required` for
everything except `GET /api/auth/me` and `POST /api/auth/change-password` (`{current_password,
new_password}`, min 10 chars), and the WebSockets close with 1008; the SPA's `RequireAuth` shows
`pages/ChangePassword.tsx` instead of the app.

### Config (`app/settings.py`, `app/config.py`, `app/database.py`)

- `SECURITYCAM_DATABASE_URL` env var overrides the DB connection string; default is a hardcoded SQL
  Server ODBC connection string (`Driver={ODBC Driver 17 for SQL Server}`,
  `Server=PGLHAM-ITLT03I\SQLEXPRESS1`, `Trusted_Connection=yes`, `Database=RetailParkingMonitor`
  on the `retail-parking` branch; `SecurityCamera` on `main`). **The retail/car-park work must never
  touch the factory system**: its DB is `SecurityCamera`, its code is `main`, its snapshots are
  `data/event_snapshots` (this branch uses `data/retail_event_snapshots`).
- CORS is a hardcoded allow-list in `main.py`: `http://localhost:5173` / `:5174` only. Add any
  production frontend origin here.
- `app/config.py` (name is misleading) holds the vision-engine dataclasses (`ZoneRules, Zone,
  CalibrationConfig, EngineConfig`) — detector paths, confidence/NMS/containment thresholds,
  `device="cuda"` hardcoded, frame size, speed window, `vehicle_class_names`.
- No `.env`/dotenv loading anywhere in the backend.

### Deployment / production (`build-release.ps1`, `deploy/`)

- **Build**: `powershell -ExecutionPolicy Bypass -File .\build-release.ps1` → `release\APL-SecurityMonitor-<yyyy.MM.dd>-<sha>[-dirty].zip`
  (backend `app/`, built frontend as `backend/static/` served by FastAPI on the same port, weights
  `yolov8s.pt`, the `deploy/*.ps1` scripts; the zip/task names still say "APL"). A dirty working
  tree adds `-dirty` to the name -- commit first. Zip paths use backslashes (PowerShell 5.1
  `Compress-Archive`); `Expand-Archive` handles that fine.
- **Upgrade in place**: `deploy/update-release.ps1 -ReleaseZip <zip> -InstallDir <folder with config.ps1>`
  -- stops the "APL Security Monitor" scheduled task, moves `backend/app` + `backend/static` +
  `backend/models` (custom weights) aside as `.bak-<stamp>`, copies the new ones in, restarts,
  health-checks `GET /api/health`, rolls back automatically on failure. Keeps `venv`, `data`,
  `config.ps1`. (Before 2026-10-23 it skipped `models`, so servers kept their first-install weights.)
  The health check doesn't notice a custom model failing to load -- check `logs\server.log`.
- **Production DB connection string** is NOT in the code: `start-server.ps1` builds it from the
  install folder's `config.ps1` (`$SqlServer`, `$SqlDatabase`, `$SqlUsername`/`$SqlPassword` or
  Windows auth as SYSTEM) via `sql-connection.ps1` and passes it in `SECURITYCAM_DATABASE_URL`.
  **Hazard**: if the app is started any other way (e.g. bare `uvicorn`), `settings.py` silently falls
  back to the hardcoded dev server `PGLHAM-ITLT03I\SQLEXPRESS1` -- which is the developer's laptop.
  Removing that fallback (fail loudly) was proposed but not done. See `CHANGELOG.md` for the open
  "production DB has no tables" investigation.

### Security notes

Fixed on this branch (2026-11-08, ADR 0006; `main` still has both issues):
- The Azure Communication Services connection string and sender come **only** from env vars
  `AzureCommunicationServiceConnectionString` / `AzureCommunicationServicesSenderEmail`; unset =
  email disabled with a clear error. The key that used to be hard-coded is still in the factory
  repo's history and must be rotated in the Azure portal.
- `crud.seed_default_admin` creates `admin` with a **random one-time password**, printed once to the
  server console/log, and `User.must_change_password = True`. Never put a password in source.

---

# FRONTEND (`frontend/`)

## Stack

React 19, TypeScript ~6.0, Vite 5 (`@vitejs/plugin-react`), `react-router-dom` v7 (`BrowserRouter`,
all routes statically imported in `src/App.tsx`), Tailwind CSS 3 for styling, `lucide-react` for
icons, `recharts` v3 for the Analytics charts only. No global state library — plain
`useState`/`useEffect` per page, plus one `AuthContext` (`src/hooks/useAuth.tsx`). No data-fetching
library (no react-query/swr) — hand-rolled axios calls, polling, and WebSockets. No test runner
configured at all (no vitest/jest).

## Commands (`frontend/package.json`)

```bash
npm run dev       # vite dev server
npm run build     # tsc -b (typecheck) && vite build
npm run preview   # preview a production build
npm run lint      # oxlint (NOT eslint — no eslint config exists)
```

There is no separate `typecheck` script — type errors surface via `npm run build`. There is no
`test` script — no test tooling exists in this frontend.

## Architecture

### Routing & auth guards (`src/App.tsx`)

Single route tree, no code-splitting. Guards: `RequireAuth` (redirect to `/login` if not
authenticated), `RequireAdmin` (checks `role.is_system`), `RedirectIfAuthed` (keeps logged-in users
off `/login`). Non-admin roles get the sidebar nav filtered by `role.pages` against the
`PAGE_KEYS`/`PAGE_LABELS` constants in `src/types/index.ts`; `/admin/users` and `/admin/roles` are
never grantable via `pages` — always admin-only.

### Pages (`src/pages/`, one per route)

| File | Route | Purpose |
|---|---|---|
| `LiveMonitor.tsx` | `/` | Grid of live camera tiles (WebSocket video), per-tile status polling + restart, fullscreen toggle, floating alert toasts. Filters to `camera.is_enabled` cameras only. |
| `Cameras.tsx` | `/admin/cameras` | CRUD for camera registration (IP/RTSP, bulk "4-lens quad" add, fisheye, or server webcam); enable/disable, restart, status pill. `fisheye_view` rows show "View of fisheye camera …" and their settings icon opens the parent's Fisheye Setup. No edit form -- only add/toggle/restart/delete. |
| `ZoneTypes.tsx` | `/admin/zone-types` | CRUD for reusable zone-rule presets (exclusion/speed limit/stop required/time window). |
| `ZoneStudio.tsx` | `/admin/zones` | Canvas polygon editor over a camera snapshot to draw/save per-camera zones + rules (seeded from a Zone Type, then overridable). Each zone in the "existing zones" list has a Crop-icon toggle to restrict that camera's whole view + detection to just that zone (`PUT /api/cameras/{id}` with `restricted_zone_id`) — see "Zone-only camera view" above. |
| `CalibrationTool.tsx` | `/admin/calibration` | Canvas line-draw tool over a camera snapshot to compute `pixels_per_meter` from a known real-world reference distance; multiple calibrations per camera, one "active". |
| `FisheyeSetup.tsx` | `/admin/fisheye` | For `source_type="fisheye"` cameras: mark the lens circle (auto-detect or drag) and split the camera into named virtual views (`fisheye_view` cameras) with direction/tilt/zoom and live previews -- see "Fisheye views" above. |
| `CoachingWorkbench.tsx` | `/coaching` | **"Incidents"** page (renamed). Review queue (All/Open/Resolved – stored as `to_review`/`coached`; no Dismissed tab, dismissing deletes); detail modal plays the clip (`components/EventClip.tsx`, boxes drawn on a canvas from the overlay JSON); per-card hover **Dismiss** button, Ctrl/Cmd+click toggle and Shift+click range multi-select with a top-right "N selected · Clear · Dismiss N" bar (`POST /api/events/bulk-status`, `window.confirm` first; Esc or tab change clears). Cards are `div role="button"` (not `<button>`) so the Dismiss button can nest. Detail modal: snapshot, raw payload incl. track id/speed, comments, status transitions, "email incident". |
| `IncidentSearch.tsx` | `/incidents/search` | Free-text incident search (`GET /api/incidents/search`) with example queries. |
| `DetectionSettings.tsx` | `/admin/detection-settings` | Admin-only: confidence thresholds, incident confirmation (N of M frames), shadow filter, detector resolution, min person aspect ratio. |
| `Analytics.tsx` | `/analytics` | Recharts dashboards: breaches-by-day, risk-by-policy, camera leaderboard. |
| `UsageHeatmap.tsx` | `/heatmap/usage` | Wraps shared `HeatmapView` for object-dwell heatmaps. |
| `ViolationsHeatmap.tsx` | `/heatmap/violations` | Wraps shared `HeatmapView` for rule-violation location heatmaps. |
| `Login.tsx` | `/login` | Auth form with the Tiam logo. |
| `SystemStatus.tsx` | `/admin/system` | Admin-only: live worker fps / ms per frame / incidents, GPU, storage (polls every 3 s). |
| `SiteSettings.tsx` | `/admin/site` | Admin-only: site name/type/timezone, after-hours window, max stay. |
| `ChangePassword.tsx` | (none) | Shown by `RequireAuth` instead of the app while `user.must_change_password`. |
| `UserManagement.tsx` | `/admin/users` | Admin-only: CRUD users, assign role, reset password. |
| `RoleManagement.tsx` | `/admin/roles` | Admin-only: CRUD custom roles with a checkbox matrix over `PAGE_KEYS`. |

### API client & config

- `src/lib/config.ts`: `API_BASE_URL`/`WS_BASE_URL` from `import.meta.env.VITE_API_BASE_URL`
  (default `http://localhost:8000`). No Vite dev-server proxy — the SPA talks to the backend's
  absolute URL directly, so CORS must be correct backend-side (see backend CORS section above).
- `src/lib/api.ts`: axios instance; request interceptor attaches
  `Authorization: Bearer <token>` from `localStorage["securitycam_token"]`; response interceptor
  clears the token and hard-redirects to `/login` on any 401 (except the login call itself).
- `src/lib/ws.ts`: `buildWsUrl(path)` appends the token as a `?token=` query param (WS can't carry
  headers) — matches the backend's `/ws/*` token-in-query auth.

### Live streaming (`src/hooks/useCameraStream.ts`)

Not MJPEG-over-HTTP, not polling — a WebSocket to `/ws/stream/{cameraId}` with
`binaryType = "blob"`; each `onmessage` blob → `URL.createObjectURL` → set as `<img src>` (previous
object URL revoked). Auto-reconnects after 3000ms on close/error. Camera *status* (as opposed to the
frame feed) is polled separately via `GET /api/cameras/:id/status` (every 3s on LiveMonitor, every
5s on the Cameras admin page) — not pushed over the socket. Alerts arrive separately via
`useAlertToasts.ts` listening on `/ws/alerts`.

### Zone / calibration editors

`ZoneStudio.tsx`: fetches `GET /api/camera/snapshot?camera_id=` (retries up to 5× at 1.5s if the
worker hasn't produced a frame yet) as a fixed 960×540 canvas background (matches backend
`FRAME_SIZE` — coordinates are shared 1:1, no rescale math needed against the detector). Click adds
a polygon point; clicking the first (highlighted) point closes the polygon at ≥3 points; drag moves
a point; right-click deletes the nearest point. A "zone rule" =
`{applies_to, rule_exclusion, max_speed_kmh?, rule_stop_required (+ stop_min_seconds),
time_restriction_enabled + from_time/to_time}` — selecting a Zone Type pre-fills
these via `rulesFromType`, then they're freely overridable before save.

`CalibrationTool.tsx`: same snapshot-canvas approach. Method "Rectangle (4 points)" (default):
click 4 floor corners in order + both side lengths; "Line (2 points)": single draggable line,
`pixels_per_meter = pixelDistance / realWorldMeters`.

### Key types (`src/types/index.ts` — mirrors `backend/app/schemas.py`/`models.py`, keep in sync)

```ts
type Point = [number, number];
type CameraSourceType = "ip" | "webcam" | "fisheye" | "fisheye_view";
type CameraProtocol = "rtsp" | "http" | "https";
type CameraStatus = "starting" | "connected" | "reconnecting" | "stopped" | "error";
type AppliesTo = "person" | "vehicle" | "both";
type EventStatus = "to_review" | "coached" | "dismissed";

interface Camera {
  id: number; name: string; source_type: CameraSourceType;
  protocol: CameraProtocol | null; ip: string | null; port: number | null;
  stream_path: string | null; device_index: number | null;
  is_enabled: boolean; username: string | null; // password never returned to the client
  // fisheye de-warp calibration (ratios 0-1), null until calibrated -- see backend's Fisheye
  // camera de-warping section
  fisheye_center_x: number | null; fisheye_center_y: number | null;
  fisheye_radius_x: number | null; fisheye_radius_y: number | null;
  fisheye_inner_radius: number | null;
  restricted_zone_id: number | null; // set -> view+detection restricted to this one zone
  // fisheye_view only: parent fisheye camera + virtual camera aim (degrees)
  fisheye_parent_id: number | null;
  view_direction_deg: number | null; view_tilt_deg: number | null; view_fov_deg: number | null;
}

interface Zone {
  id: number; camera_id: number; zone_type_id: number | null;
  name: string; polygon_points: Point[];
  applies_to: AppliesTo; max_speed_kmh: number | null;
  rule_exclusion: boolean; rule_stop_required: boolean; stop_min_seconds: number;
  time_restriction_enabled: boolean; from_time: string | null; to_time: string | null; // "HH:MM"
}

interface ZoneType extends /* same rule shape, "default_" prefixed */ {} {
  id: number; name: string; description: string | null; is_system: boolean;
}

interface Calibration {
  id: number; camera_id: number; name: string;
  line_points: [Point, Point]; real_world_meters: number; pixels_per_meter: number; is_active: boolean;
}

interface Event {
  id: number; camera_id: number | null; zone_id: number | null; zone_name: string;
  policy_type: string; risk_score: number; // 1-10, only "confidence-like" value shown in UI
  track_id: number | null;
  raw_payload: Record<string, unknown>; timestamp: string; status: EventStatus; has_snapshot: boolean;
}

interface Role { id: number; name: string; pages: string[]; is_system: boolean; }
interface User { id: number; username: string; role_id: number; is_system: boolean; }
```

Detector confidence is only shown burned into the video (box labels); the UI displays `risk_score`
(a policy severity, not a detection confidence): red ≥8, amber ≥5, else green. `CoachingWorkbench.tsx`
shows `track_id` in the event detail modal and does no client-side dedup.

### Theme ("Night Shift", `retail-parking` branch)

- **All colours are CSS variables on `:root` in `src/index.css`** (`--bg, --panel, --panel-2,
  --border, --text, --text-muted, --accent` amber, `--critical, --warning, --success, --video-from,
  --video-to, --radius` 4px). Never hard-code a colour. A light theme = override the same variables
  under `:root[data-theme="light"]`.
- `tailwind.config.js` maps every Tailwind colour onto them via `color-mix` (opacity modifiers
  still work): semantic names `bg, panel, panel-2, line, fg, muted, accent, critical, warning,
  success`; the legacy `slate` ramp (<=300 text, 400-500 muted, 600-700 border, 800 panel-2, 900
  panel, 950 bg), `red/amber/emerald` = critical/warning/success, `apl-midnight/sunset` = bg/accent.
  All `rounded-*` (except `full`) = `--radius`. `text-sm` = 13px.
- Canvas/Recharts code reads tokens with `token(name)` from `src/lib/theme.ts`.
- Detection boxes are drawn by the backend (`vision_engine.BOX_NORMAL/BOX_THREAT`, BGR copies of
  `--accent`/`--critical`) -- keep them in sync by hand.
- Component classes in `src/index.css`: `dm-card, dm-input, dm-label, dm-btn-primary,
  dm-btn-secondary, dm-pill*, dm-chip-critical, dm-skeleton`. Animations: `animate-alert-pulse`,
  `animate-slide-in-right`.
- Font: Inter only (self-hosted). Logo: placeholder `src/components/TiamLogo.tsx` (inline SVG, token
  colours; sidebar + login); favicon `public/brand/tiam-icon.svg` (hard-coded hex, can't read tokens).
- Live Monitor: tiles show a name chip + red LIVE chip on the video, a red outline and pulsing ALERT
  chip while that camera has an alert toast on screen; toasts are severity-bordered and slide in.
