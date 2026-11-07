# Changelog

Dated log of feature work: **what** changed, **why**, **where** (files), **how it was verified**,
and **open follow-ups**. `CLAUDE.md` describes how the system works now; this file records how it
got there and what's still unresolved. Newest first.

---

## 2026-11-08

### Security fixes, spec grilling, ADRs (branch `retail-parking`)

**Why:** ADR 0006 – before the code leaves the company network (GitHub), no secret may be in it.

**What:**
- `settings.py`: Azure Communication Services connection string / sender come only from env vars
  (no hard-coded fallback). The old key is still in the factory repo history -> rotate it in Azure.
- `crud.seed_default_admin`: random one-time password printed once to the console/log,
  `User.must_change_password` (new column, in `_add_missing_columns`). `auth.get_current_user` returns
  403 for everything but `/api/auth/me` + new `POST /api/auth/change-password`; WebSockets close.
  Frontend `pages/ChangePassword.tsx` replaces the app until changed.
- Dev DB `RetailParkingMonitor`: old `admin` deleted and reseeded with a one-time password.
- Grilling of the car-park spec: `CONTEXT.md`, ADRs 0001-0007, spec moved to `docs/spec/` and
  updated (hospital first, whole system, built-in optional ANPR, new phase order).

**Verified:** throwaway DB `Tiam_AuthTest` (dropped after): login with one-time password, other API
403, short/wrong password rejected, change ok, API 200 after, old password 401, no Azure fallback
(9/9). `tsc -b` clean. Not click-tested in the browser.


### Factory-only features removed; Tiam logo (branch `retail-parking`)

**Why:** not needed for car parks / shopping malls. User chose to remove separation (crowded car
parks would mostly false-alarm) and stationary-vehicle suppression (it hid parked cars).

**What:**
- **PPE / hi-vis**: model loading, colour + reflective-stripe checks, `missing_ppe` events, `rule_ppe`,
  all hi-vis Detection Settings, `scripts/fetch_ppe_model.py`, `ppe_model.pt` in the release.
- **Separation**: rule + distance, Walkway and Barrier zone types, the obstruction check,
  `separation_breach` events, `Event.person_track_id/vehicle_track_id`, the incident-search
  distance filter. `_apply_rules(tracks, ts)` now returns just the events.
- **Stationary-vehicle suppression** and its settings; `heavy_model_interval_frames` (only throttled
  PPE); the unused `forklift_confidence` / `detection_downscale` columns.
- Seeded zone types now: Pedestrian Exclusion, Vehicle Exclusion, Speed 10/15 km/h, Stop Required.
- `RetailParkingMonitor` was dropped and recreated (it held only seed data) so the schema matches.
- Logo: APL SVGs deleted; placeholder `components/TiamLogo.tsx` (token colours) + favicon
  `public/brand/tiam-icon.svg`; page title "Tiam".

**Verified:** `verify_logic.py` 16/16 (PPE/separation checks removed, exclusion check added); a
real `process_frame` run on the GPU; `tsc -b`; Detection Settings and Zone Types checked in Chrome,
no console errors. `SecurityCamera` untouched.

**Not done:** CLAUDE.md's detailed sections still describe the removed features (flagged at the
top). `backend/models/ppe_model.pt` left on disk.

### Separate database + branch for the retail / car-park system (branch `retail-parking`)

**Why:** the retail/car-park work must not affect the factory system (DB `SecurityCamera`, code
`main`).

**What:** new empty DB `RetailParkingMonitor` on the same SQL Express instance; `settings.py`
default points there; event snapshots go to `data/retail_event_snapshots` (snapshot files are
named by event id, so sharing the folder with the other DB would overwrite/delete its files). The
forklift removal + setup work (2026-11-07) moved onto this branch, `main` unchanged.

**Bug fixed:** `create_all` could never build a fresh DB: `cameras.restricted_zone_id` (FK SET
NULL) + `zones.camera_id` (FK CASCADE) is a cycle SQL Server rejects. Existing DBs only had it as
a plain `INT NULL` (added by `_add_missing_columns`), so the model now matches that and
`crud.delete_zone` clears it.

**Verified:** backend starts on the new DB (11 tables, admin user, 9 zone types seeded, no
cameras). `SecurityCamera` had no events/heatmap/sessions written after 2026-11-05.

## 2026-11-07

### Forklift model removed (start of the retail / car-park conversion)

**Why:** the system is being repurposed from factory safety to shopping centres and car parks; the
custom forklift detector isn't needed. COCO car/truck/bus/motorcycle detection stays (car parks
need it).

**What:** removed forklift model loading (`main.py`, `camera_manager.FORKLIFT_MODEL_PATH`), the
forklift predict/merge/cache block, `FORKLIFT_CLASS_ID_OFFSET`, the "forklift label beats COCO
truck" dedup step, `_overlaps_any`, `_rescale_detections` (`vision_engine.py`),
`forklift_model_path`/`forklift_detection_conf`/`detection_downscale` and `"forklift"`/`"tug"` from
`vehicle_class_names` (`config.py`), Forklift/Tug from the Usage Heatmap dropdown, the Forklift
confidence + downscale fields from Detection Settings (API schema + UI), `forklift_model.pt` from
`build-release.ps1`, `scripts/build_forklift_tug_dataset.py`. The `forklift_confidence` and
`detection_downscale` DB columns stay on `models.DetectionSettings` (unused) because older DBs have
them as NOT NULL. `heavy_model_interval_frames` stays -- it still throttles the PPE check.
`verify_logic.py` section 7 now tests car+truck dedup instead.

**Verified:** `verify_logic.py` 36/36 pass (its speed check was already broken by the 11-05
3-sample minimum and was updated); `tsc -b` clean; backend starts, `/api/health` ok.

**Local setup (same day):** created `backend/venv` (torch 2.14 cu126, CUDA ok on the RTX 3050),
pinned `supervision<0.31` in requirements.txt (0.31 removed `sv.ByteTrack`), `npm ci` in frontend.

**Not done:** factory wording/seed data (forklift separation, walkway, barrier zone types, "Pedestrian/Forklift
Separation Breach" policy text) -- part of the later conversion. `backend/models/forklift_model.pt`
left on disk.

---

## 2026-11-05

### Speed spikes on steady-moving vehicles (branch `speed-accuracy`)

**Why:** a vehicle moving at a steady ~4 km/h showed jumps to 7-9 km/h. Live recording (all 6
cameras, 60 s, boxes read from the stream): frame timing was even (10 fps, gaps ≤ 0.35 s) -- the
cause is the **box** jumping. The forklift model runs every `heavy_model_interval_frames` (4)
and its box is reused unchanged in between, so the forklift looks frozen, then jumps ahead
(Canopy Entrance: bottom edge 290 for 4 frames, then 304; box frozen on 33 of 79 frames). When the
forklift model misses, the main detector's differently-sized box is used until its next run
(height 91 → 101 px). Perspective magnifies it: 1 px vertical = 6-17 cm on these cameras.

**What** (`vision_engine`):
- A sample identical to the track's previous one (a reused box) isn't added to the speed history.
- `_speed_kmh`: Theil-Sen (median of pairwise velocities) instead of least squares.
- `speed_window_s` 1.0 → 1.5 s (speeding alerts ~0.5 s later). `SPEED_MIN_SAMPLES` 4 → 3 so a
  vehicle only the forklift model sees still gets a speed.

**Verified:** replaying the live Canopy Entrance forklift through the formula: peak 6.9 → 4.4 km/h,
median unchanged. Scratchpad `test_speed_spikes.py` (steady 4 km/h, forklift model missing 25% of
runs): 95th percentile 7.4 → 5.9 km/h at interval 4, 5.5 → 4.6 at interval 1; parked forklift with
only cached boxes reads 0.03 km/h. Earlier tests still pass.

**Open:** the detector switch isn't fully removable by averaging. Lowering Detection Settings
"Heavy model interval" to 2 or 1 cuts it further (more GPU).


### Frame timing, fitted speed, position-based stop (branch `speed-timing-fix`)

**Why:** speeds were inaccurate even after calibrating, and parked cars still got "Failed to
Stop". Cul De Sac Overview Camera was being processed at ~10 fps (stalls up to 0.8 s) while normal
IP cameras read frames **in order** and stamped them with processing time. When the server is
slower than the camera, speeds read low (25 fps camera at 10 fps = ~40%), the live view lags, and
backlog overflow drops frames, which shows up as speed spikes. Speed was also first-vs-8th sample
(~0.4-0.8 s depending on fps), so a few px of box jitter read as > 2 km/h, which reset the stop
timer.

**What:**
1. **Timing** (`camera_manager`): every camera now reads through `_SharedCapture` (previously
   fisheye only): a thread reads at camera speed, keeps only the newest frame + its arrival time;
   the worker passes that time to `VisionEngine.process_frame(frame, ts)`. Raw-JPEG encoding stays
   fisheye-only. `on_camera_changed` force-reconnects any non-view camera's capture.
2. **Speed** (`vision_engine._speed_kmh`): least-squares fit over the last `speed_window_s` = 1.0 s
   of ground points in metres (`CalibrationConfig.ground_points`), replacing
   `speed_window_frames`.
3. **Stop** (`_apply_rules`): stopped = stayed within `STOP_MAX_DRIFT_M` = 0.5 m of an anchor for
   `stop_min_seconds`. With 1 s that's about the old 2 km/h; longer stop times are stricter.

**Verified:** scratchpad `test_speed_timing.py`: 5/10/20 km/h within 15% at 10 and 18 fps with 3 px
jitter; parked with 5 px jitter < 2 km/h; parked 3 s with ±12 cm jitter passes a 2 s stop zone;
roll-through, 2 km/h crawl and a 1.5 s stop fire; fake 25 fps camera read by a 10 fps worker skips
frames, timestamps match camera time, frames < 0.1 s old. `test_stop_zone.py` (updated to move the
point), `test_4pt_calibration.py` pass. Not tested against a real camera.

**Watch:** the reader thread now decodes every frame the camera sends (previously the backlog
throttled it), so CPU per camera goes up -- using cameras' sub-streams helps. Webcams also go
through the shared reader now.


### 4-point (rectangle) calibration (branch `4points-calibration`)

**Why:** speeds were wrong on long-view cameras (Cul De Sac Overview Camera). One pixels-per-metre
scale can't fit a picture where a metre is 42 px near the camera and 12 px far away, so speed was
only right near the calibration line. (Also found: none of that camera's 3 calibrations was
active, so the 0.02 m/px placeholder was in use.)

**What:**
- Calibration Tool "Method": **Rectangle (4 points)** (default) -- click the 4 corners of a real
  rectangle on the floor in order and enter both side lengths -- or the old **Line (2 points)**.
- Backend: `calibrations.real_world_width_m` (in `_add_missing_columns`); `line_points` accepts 2
  or 4 points (4 must be in order around a convex shape). The active rectangle becomes an image →
  ground-metres homography (`config_loader.ground_homography`); `CalibrationConfig.distance_m`
  maps both points to the ground and measures there. Used for speed (so speeding and the stop
  zone's "stopped" check) and person/vehicle separation distance. Line calibrations work as before.

**Verified:** scratchpad `test_4pt_calibration.py`: synthetic perspective camera, 5 m steps near,
far, outside the rectangle and diagonal all measure 5.000 m, both corner orders; above-horizon
points fall back to the flat scale; collinear corners rejected; API validation (crossed order,
missing/zero width). Stop-zone/tracker/stripe tests still pass. Frontend builds. Not click-tested
in a browser.

**Open:** frame timing -- speed uses processing time, not capture time, and normal IP cameras read
frames in order, so when the server processes slower than the camera sends (measured ~10 fps on
Cul De Sac Overview), speeds read low and frame drops make spikes. Not fixed here.

---

## 2026-11-02

### Forklift separation: ignore pairs with something between them (branch `forklift-seperation-improvement`)

**Why:** a person and a forklift 2.1 m apart with boxes, a conveyor and bins between them raised a
separation breach.

**What:**
- **Barrier zone rule** (`rule_barrier` on Zone + ZoneType, both in `_add_missing_columns`; system
  zone type "Barrier / Obstruction" seeded into existing DBs): if the floor line between person
  and vehicle crosses a barrier zone, it's not a breach. If either end is *inside* the zone
  (someone working in the racking), it still is. Tickbox in Zone Studio and Zone Types.
- **Automatic obstruction** (Detection Settings "Detect obstructions as accepted separation",
  `separation_ignore_obstructed`, default **off**): skip the breach when an unbroken run of the
  floor line (≥ 8 px and ≥ 25% of it) doesn't match the floor sampled below each ground point.
  Shadows count as floor (30–140% brightness), tracked boxes are skipped, thin floor markings don't
  count.

**Verified:** `verify_logic.py`: barrier between them / off to the side / person inside it;
obstruction on with boxes / clear floor / thin marking; obstruction off. The old "separation breach
fires at 2.0m" check had been failing because its test vehicle had no speed and only *moving*
vehicles can breach. Test vehicles now move at 8 km/h and it passes. Not tested on the site
picture: the snapshot has the separation line and distance label drawn exactly along the floor
line being sampled.

**Limits:** (b) can't tell items *between* the pair from items between the camera and the pair
(both hide the floor line), so it can cancel a real breach. That's why it's off by default and (a)
is preferred. Barrier zones are static: moved pallets need the zone redrawn.

### Reflective-stripe jackets count as hi-vis (branch `Ref-Stripe-Jecket`)

**Why:** workers in dark jackets with white reflective tape were flagged missing PPE. Site rule:
striped jackets count as hi-vis at any time of day (no night-only window, even though AS/NZS
4602.1 Class N is night-only).

**What (`vision_engine._reflective_stripe_pixels`, part of the colour fallback):** in the torso
band (rows 15–65%, cols 15–85% of the box), count pixels with S < 70, V ≥ 150 and V ≥ torso
median + 60. Floor-coloured pixels are left out using the floor ring (the shadow filter's
sampling, now shared as `_sample_box_and_floor`). Passes if ≥ `stripe_min_fraction` of the band
(and ≥ `hivis_min_pixels`). Settings: "Accept reflective stripes as hi-vis" (default **on**) +
"Stripe sensitivity" (default 0.5 → 5%). Event detail shows "Reflective stripe pixels".

**Verified:** 4 site crops of striped jackets pass at screenshot size (closest 33 px vs 26 needed).
White shirt 0 px, shadow/floor-bleed 1 px → fail. `verify_logic.py`: striped jacket passes, plain
dark jacket on bright floor fails, white shirt fails, toggle off fails.

**Limits:** at ~0.6× size (distant people) thin tape blurs: 2 of the 4 crops fall below the
default and only pass at sensitivity ~0.7–0.8. White prints or logos on dark clothing in the
torso band could pass. There are still no real samples of dark-clothed people without hi-vis.

### Ignore human shadows (branch `shadow-detection`)

**Why:** a person's shadow on the floor was detected as a second "person" and flagged missing PPE.

**What (`vision_engine._filter_person_shadows`, before tracking):** for each person box touching
another person box, sample the floor in a ring around it (other person boxes excluded) and
classify its pixels as floor (same hue, 85–115% brightness), shadow (same hue, 30–85%) or
other. On a grey floor, low saturation stands in for "same hue". Drop it if other < 8% and
shadow ≥ 15%, unless its neighbour is shadow-like too. Pixels under 30% brightness (hair,
black clothing) count as other. Toggle: Detection Settings → "Ignore human shadows"
(`ignore_person_shadows`, default on, column added to `_add_missing_columns`).

**Verified:** site screenshot: shadow box 2% other pixels → dropped, person 22% → kept. The 4
hi-vis crops → never shadow-like. `verify_logic.py` synthetic cases: person+shadow, hi-vis
worker+shadow, two people side by side, a shadow-like box with no neighbour, filter off.

**Limits:** a shadow whose person isn't detected is kept (no neighbour). Someone in dark
floor-coloured clothing touching another person, with no skin or hair visible, could be
dropped. Thresholds come from one site picture.

### PPE — fewer false "missing hi-vis" alerts + tunable hi-vis colours

**Why:** people in hi-vis still flagged "Missing PPE" (4 sample crops).

**Root cause:** 3 of the 4 crops pass the colour check easily in the snapshot frame (54–87 hi-vis
px vs 5 needed). One PPE check is cached for `heavy_model_interval_frames` (4) frames, and
incident confirmation is 3-of-6 frames, so **one** bad check (new track's badly fitted box, blur,
vest turned away) was enough to raise an alert. The 4th crop's vest is a pale amber-yellow
(hue 14–22) just under the yellow band's hue-22 start. Lowering that start isn't safe because
common light skin tones are at hue 16–18.

**What:**
- `_check_ppe` reports missing PPE only after `ppe_min_failed_checks` (default 4) separate checks
  fail in a row. Any passing check still clears the track for good.
- Hi-vis saturation floors and pixel count moved from constants to `EngineConfig.hivis_*`. New
  Detection Settings fields: yellow/orange/purple sensitivity (0–1, saturation floor =
  255·(1−s); defaults 0.8/0.33/0.33 = the old 50/170/170), hi-vis pixels needed (5), failed
  checks before alert (4). Columns added to `_add_missing_columns`.
- `missing_ppe` events store `hivis_pixels` {yellow, orange, purple} + `hivis_min_pixels` in
  `raw_payload`. The Coaching Workbench detail shows them.

**Verified:** `scripts/verify_logic.py` covers the new checks (passes until N fails, sticky pass,
counts recorded). Its separation-breach check already failed before this change. On the 4
crops: orange sensitivity 0.5 passes the amber vest (8 px). At 0.6, skin/other areas of the
other three crops already reach 11–14 orange px, so ≥0.6 would let bare skin pass.

**Open:** no crops of people *without* hi-vis to tune against. Hue edges are still fixed.

## 2026-10-19

### PPE — any yellow / orange / purple pixel counts as hi-vis

**Why:** 10 workers were flagged "Missing PPE". User's rule: if any dot or pixel of yellow, orange
or purple (any shade) is on the person, treat them as wearing hi-vis.

**What (`vision_engine._heuristic_hivis_check`):** the three separate bands and the >5%-of-crop
threshold are replaced by one hue arc, 125→180→0→45 (purple/pink/red → orange → yellow incl. fluoro
yellow-green). A person passes if `HIVIS_MIN_PIXELS` (=1) pixel falls in it. Only colourless pixels
are rejected (`HIVIS_MIN_SATURATION`/`HIVIS_MIN_VALUE` = 60: grey/white/black).

**Verified:** all 10 sample crops → pass. Solid grey/black/white/navy/green → fail. Solid skin tone
→ **pass**. The PPE model detected nothing on any of the 10, and the *previous* heuristic already
passed all 10 (14–77% vs 5%), so those alerts most likely came from a server running code older than
`9b0d42c`.

**Caveat:** skin is orange hue, and these cameras tint the floor/walls magenta, so almost every
person now passes. On these cameras, missing-PPE alerts will almost never fire. To make the check
stricter again, raise `HIVIS_MIN_PIXELS` / the S/V floors.

## 2026-10-07

Branch: `JevQuery`.

### Zone-only camera view: detection stays restricted, live view no longer crops

**Why:** user running a camera restricted to one zone (`Camera.restricted_zone_id`) wanted the
Live Monitor to still show the whole camera view, even though detection is deliberately limited to
just that zone.

**What:** previously the *entire pipeline* operated on the cropped frame (detector input AND the
streamed/snapshotted/heatmap output), so a restricted camera's live view only ever showed the
cropped zone. Now only the detector's input (`detect_frame`) is masked+cropped; `annotated` (what
gets streamed/snapshotted) is always a copy of the full, unmasked frame. Detections coming back
from the crop are shifted back to full-frame coordinates (via `self._restrict_offset`) right after
they're merged/deduped and before tracking, so everything downstream (tracking, zone membership,
`_apply_rules`, drawing) operates in the same full-frame coordinate space as an unrestricted
camera -- the separate "restricted zone polygons" translation this used to need is gone entirely.
`VisionEngine.output_frame_size` now always equals `config.frame_size` (never a cropped size).

**Files:** `backend/app/vision_engine.py` (`process_frame`, `_recompute_restriction`,
`output_frame_size`); `CLAUDE.md`'s "Zone-only camera view" section updated to match.

**Verified:** `py_compile` clean. End-to-end synthetic test: a `VisionEngine` with
`restrict_to_zone_id` set, detector mocked to return one box in crop-space coordinates, run through
the real `process_frame()` -- confirmed `annotated` comes back at the full configured `frame_size`
(not the crop size), and the resulting track's ground point/zone membership correctly reflect the
offset-back full-frame position. Not yet tested against a real camera/live stream.

---

### Stop-required zones ("must come to a stop, e.g. a stop sign")

**Why:** user wants a zone where any vehicle passing through must come to a near-stop for at least
N seconds, with an incident logged if it drives through without ever stopping.

**What:**
- New rule type `failed_to_stop`, alongside the existing exclusion/speeding/missing_ppe/
  separation_breach. New `Zone`/`ZoneType` columns `rule_stop_required` (bool) +
  `stop_min_seconds`/`default_stop_min_seconds` (float, default 1.0) — same "default_"-prefix-on-
  ZoneType convention as every other rule field. Seeded as a new built-in Zone Type "Vehicle Stop
  Required" (`applies_to="vehicle"`).
- "Stopped" tolerance is a fixed `STOP_MAX_SPEED_KMH = 2.0` constant in `vision_engine.py`, not
  configurable per zone (it's a measurement tolerance for tracking jitter, not a policy choice).
- This required new bookkeeping that didn't exist anywhere in the pipeline before: `zone_hits` is a
  fully memoryless per-frame recomputation (no prior-frame zone membership was ever stored), so
  detecting a zone *exit* (as opposed to continuous in-zone presence, which is all the other 4 rule
  types need) needed two new per-track dicts on `VisionEngine`: `_stop_progress` (has this track
  ever recorded a continuous near-stop of `stop_min_seconds` inside this zone) and
  `_track_last_zone_hits` (previous frame's zone_hits, to diff against this frame's and detect the
  exit transition). Both pruned in `_prune_stale_tracks` alongside the existing `_ppe_cache`/
  `_vehicle_static_check` dicts.
- `risk.py`: `"Failed to Stop (Stop-Required Zone)"`, fixed risk score 6. `incident_search.py`:
  added matching keywords ("stop sign", "didn't stop", etc.) so Incident Search can find these too.
  `camera_manager.py`'s `_IncidentTracker`/`_incident_key` needed no changes — generic over
  `ev["type"]` already.

**Files:** `backend/app/vision_engine.py`, `config.py`, `config_loader.py`, `models.py`, `main.py`
(`_add_missing_columns`), `schemas.py`, `crud.py`, `risk.py`, `incident_search.py`;
`frontend/src/pages/ZoneTypes.tsx`, `ZoneStudio.tsx`, `src/types/index.ts`.

**Verified:** backend `py_compile` clean, frontend `npm run build` clean. Synthetic unit test
directly against `VisionEngine._apply_rules` (no DB/camera needed, by design) confirmed: a vehicle
passing through without ever dropping below 2 km/h fires `failed_to_stop` on exit; one that stops
for ≥1s at some point inside the zone does not. Not yet tested against a real camera/DB.

---

## 2026-09-30

Branches: `coaching-dismiss-ppe-dedupe` (merged to `main` as `ecfc97a`), then `fisheye-4div`
(`6a52e05` fisheye views; tug removal + these docs committed after).

### Quick index

| # | Change | Commit / branch |
|---|--------|-----------------|
| 1 | Coaching Workbench: per-card Dismiss, multi-select, bulk dismiss | `4b8c865` → `main` |
| 2 | Dismiss = permanent delete (row + comments + snapshot); no Dismissed tab | `4b8c865` → `main` |
| 3 | PPE: hi-vis check falls through to colour when the model sees nothing | `4b8c865` → `main` |
| 4 | PPE: any yellow / orange top counts as hi-vis (fluoro yellow-green was rejected) | `4b8c865` → `main` |
| 5 | Incidents: one event per breach per object (60 s window + re-ID by position) | `4b8c865` → `main` |
| 6 | Fisheye: split one fisheye camera into named virtual views ("4 cameras") | `6a52e05` on `fisheye-4div` |
| 7 | Tug detection removed | `fisheye-4div` |
| — | Release zip, production DB investigation, BS-1 stream path | no code / see Operations |

---

### 1. Coaching Workbench — Dismiss button, multi-select, bulk dismiss

**Why:** users had to open an event's detail view just to dismiss it, one at a time.

**What:**
- Hover a card → **Dismiss** pill (bottom-right of the snapshot). Hidden on already-dismissed cards.
- **Ctrl/Cmd+click** toggles a card, **Shift+click** selects the range from the last clicked card
  (Ctrl+Shift adds the range). Plain click still opens the detail modal.
- While anything is selected, top right shows **"N selected · Clear · Dismiss N"**; bulk dismiss asks
  `window.confirm` first (it's a permanent delete, see #2). **Esc** or switching tab clears.
- Cards changed from `<button>` to `div role="button"` (a `<button>` can't contain the Dismiss
  `<button>`); keyboard Enter/Space still opens.

**Files:** `frontend/src/pages/CoachingWorkbench.tsx`; backend `POST /api/events/bulk-status`
(`routers/events.py`, `crud.bulk_update_event_status`, `schemas.EventBulkUpdate`, max 1000 ids).

**Verified:** `tsc -b` clean. Not click-tested in a browser at the time.

### 2. Dismiss permanently deletes the event

**Why:** user asked that dismissed events be removed from the database *and* the snapshot folder,
and not appear under "All".

**What:**
- `PATCH /api/events/{id}` with `status="dismissed"` and `POST /bulk-status` with `"dismissed"` call
  `routers/events.delete_events_and_snapshots` → `crud.delete_events` (deletes comments explicitly,
  not relying on the FK cascade older DBs may lack) + unlinks `data/event_snapshots/{id}.jpg`.
- Frontend **Dismissed tab removed**. `crud.get_events` with no status filter excludes
  `status="dismissed"` rows (safety net for servers not yet upgraded).

**Data cleanup done:** on the dev machine's DB, 1223 leftover `dismissed` rows (from before the
change; their JPEGs were already gone) were deleted at the user's explicit request. An earlier
attempt to do this automatically at app startup was **blocked by the permission check and
removed** — don't re-add an automatic startup purge.

**Open:** the production server's DB may still hold old dismissed rows (hidden by the filter, not
deleted). Only clean them up if the user asks.

### 3. PPE — "model found no vest" no longer means "missing PPE"

**Why:** people in obvious hi-vis were flagged "Missing PPE (Hi-Vis Vest)"
(`Documents/Error/1.jpg`, canopy camera).

**Root cause:** `ppe_model.pt` (classes Gloves, Vest, goggles, helmet, mask, safety_shoe) is trained
on close-ups; on elevated CCTV a person is ~20–60 px tall and the model detects *nothing*, even at
conf 0.05. `_check_ppe_uncached` treated "no vest class found" as missing and never ran the colour
check (which only ran when no model was loaded at all).

**What:** Vest detected → OK; a "no-vest" class → missing; nothing found → **fall through to the
HSV colour heuristic** (`_heuristic_hivis_check`). Also: once a track has been seen in hi-vis it
stays compliant (`_check_ppe`), so shade / turning away / occlusion mid-walk don't raise alerts.

**Files:** `backend/app/vision_engine.py`.

**Verified:** the 4 workers cropped from the screenshot: model found nothing on all 4; colour check
25–42% hi-vis pixels vs 5% threshold → pass; bare-ground control 0% → fail.

### 4. PPE — any yellow or orange top counts as hi-vis

**Why:** still flagged after #3; user rule: "a yellow or orange shirt = hi-vis".

**Root cause:** fluoro hi-vis "yellow" is really yellow-green at OpenCV hue **36–40** (0–180
scale); the yellow band stopped at 35, so real hi-vis failed while a plain yellow shirt passed.

**What (`_heuristic_hivis_check`):**
- Yellow band `(20, 80, 80)–(45, 255, 255)` — up to hue 45 (real green is ~60), lower S/V floors
  for shade/overcast.
- Orange band `(5, 145, 100)–(19, 255, 255)` — V floor lowered for deep shade; **S floor kept at
  145**, just above skin (~70–130 at the same hue) and brown clothing (~140).

**Verified (synthetic colour patches):** passes fluoro yellow in sun/shade/washed, plain & mustard
yellow, orange in sun/shade/deep shade/overcast, red-orange, amber. Rejects 5 skin tones, brown,
tan concrete, red ute, grey, green, navy. Known miss: *very* washed-out orange (S≈110) — same
saturation as skin, can't be separated by colour.

**Limits:** colour inside the person's box can be fooled by an orange forklift / yellow floor line
behind someone. Proper fix = fine-tune the PPE model on this site's elevated-camera footage.

### 5. Incidents — one event per breach per object

**Why:** the Coaching Workbench showed several events for the same person and breach (e.g. track
#6055 twice, #6040 twice).

**Root causes:**
1. An incident was "active" only while its key fired on *every* frame; one missed frame (detector
   flicker, PPE check flip) ended it and the next frame saved a new event + snapshot.
2. ByteTrack's default `lost_track_buffer` = 30 frames ≈ **1.7 s** at our ~18 fps; a briefly
   occluded person (behind a forklift) came back under a **new track id** = new incident key.

**What:**
- `camera_manager._IncidentTracker`: an incident ends only after `INCIDENT_COOLDOWN_S = 60` s
  without firing. A *new* key appearing within `min(80 + 60·gap_s, 300)` px of an open incident of
  the same zone+rule is merged into it — unless that incident was already claimed *this frame*
  (so two people side by side stay separate).
- `vision_engine`: `sv.ByteTrack(..., lost_track_buffer=90)` (~5 s).

**Verified (simulated tracks):** flickering person → 1; occluded 4 s + new id → 1; two people
together → 2; two far apart → 2; same person back after 2 min → 2; one person, two rules → 2.

**Known trade-offs:** a different person stepping into the exact spot a lost person vanished from,
within seconds, can merge into their event. The same person on two cameras / two overlapping
zones still gives one event each.

### 6. Fisheye cameras split into named virtual views

**Why:** the old Fisheye Setup (one whole-lens rectilinear de-warp) produced nothing useful.
User asked to "flatten the circular image, then divide it into 4 views, like 4 cameras, each
nameable" (referenced https://github.com/duducosmos/defisheye).

**Findings on the real camera (BS-1, 10.150.150.51, 2048×2048, ceiling-mounted, looking down):**
- Its saved calibration was wrong: centre (0.45, 0.62), radius 0.31×0.27; the real lens circle is
  centre (0.50, 0.50), radius ≈0.49. The old de-warp was straightening the wrong region.
- defisheye's method is the same equidistant (f-theta) rectilinear maths the app already used.
  Flattening the whole lens and cutting it into 4 squares gives 4 badly stretched corners (tall
  racks/walls smear outwards), because the camera looks straight down.
- What works: **4 virtual pinhole cameras** at the lens centre, each aimed at one side
  (direction), tilted out from straight down (tilt ~55°), own FOV (~95°), each flattened on its
  own. Result looks like 4 normal angled CCTV cameras; hi-vis workers clearly visible.

**What:**
- `backend/app/fisheye.py` (new): `detect_lens_circle` (threshold + fitEllipse on the bright lens
  vs black surround), `build_view_maps` (per-view cv2.remap tables; image rotated 180° so the
  horizon is at the top for a ceiling mount), `render_view`. Direction 0 = top of the raw image,
  clockwise; defaults 315/45/135/225 (the diagonals), tilt 55, FOV 95. One remap ≈ 1 ms.
- New camera kind `source_type="fisheye_view"`: `fisheye_parent_id` (plain int, not an FK — SQL
  Server rejects self-referencing cascades), `view_direction_deg`, `view_tilt_deg`,
  `view_fov_deg` (in `_add_missing_columns`). A view is a full camera: own zones, calibration,
  detection, Live Monitor tile, events.
- `camera_manager._SharedCapture`: one ref-counted RTSP connection per physical fisheye camera,
  shared by its own worker and all its views (4 views = 1 stream, 1 decode). Worker loop split into
  `_frames()` / `_dewarp()` / `_process_frame()`. Raw circular JPEG now comes from the shared
  capture. Changing a fisheye camera restarts its views and force-reconnects the capture. A view
  whose parent has no saved circle auto-detects it.
- API: `GET|PUT /api/cameras/{id}/fisheye-views` (PUT replaces the set; creating views on an
  enabled parent **disables the parent** so alerts aren't doubled), `POST
  /api/cameras/{id}/fisheye/detect-circle`, `GET /api/camera/fisheye-view-preview`. Deleting a
  fisheye camera deletes its views.
- `FisheyeSetup.tsx` rebuilt: (1) lens circle — Auto-detect or drag, coloured spokes show where
  each view points; (2) view cards — name, debounced live preview, Direction/Tilt/Zoom sliders,
  "Default 4 views", "Add view" (max 8); **Save views** saves an edited circle first, then views.
  `Cameras.tsx`: views show "View of fisheye camera …", settings icon → parent's Fisheye Setup;
  deleting a parent warns it removes N views.

**Verified:** E2E script against the real BS-1 via a *temporary* copy of the camera row (deleted
afterwards): shared capture connects, snapshot-raw 200, detect-circle (0.500, 0.500, 0.493,
0.492), preview 200, save 4 / rename / drop one, invalid tilt → 422, real view worker → 960×540,
refcount goes 2 → 1 → released, deleting the parent removes all views. In Chrome: Fisheye Setup
loads, Auto-detect snaps the circle, all 4 previews correct, no console errors. `tsc -b` clean.

**Not done:** the user hadn't pressed **Save views** for BS-1 yet (naming is theirs); BS-1 still
has the old, wrong saved circle until they save.

### 7. Tug detection removed

**Why:** user: tug detection "is not correct". (The tug model, `forklift_tug_model.pt`, was trained
only 56 epochs, mAP50 ≈ 0.65 per `CODE_REVIEW_LOG.md`.)

**What:** removed tug model loading (`main.py`), `FORKLIFT_TUG_MODEL_PATH` (`camera_manager.py`),
`tug_model_path`/`tug_detection_conf` and `"tug"` from `vehicle_class_names` (`config.py`), the tug
predict/merge block + `TUG_CLASS_ID_OFFSET` (`vision_engine.py`), "Tug" from the Usage Heatmap
dropdown (`routers/heatmap.py`), tug wording in `DetectionSettings.tsx`, and the weights from
`build-release.ps1` (release zip ~22 MB smaller). The `.pt` file is left on disk. 3 old `tug`
heatmap rows remain in the dev DB, unused.

**Verified:** backend imports; `vehicle_class_names` = car, truck, bus, motorcycle, forklift;
`tsc -b` clean.

---

## Operations notes (2026-09-30)

- **BS-1 "not connected"**: stream path `/MediaInput/jpeg/stream_1` doesn't exist on that camera.
  Tested from the server: `/MediaInput/h264/stream_1` and `/MediaInput/h264` work (2048×2048);
  h265 and jpeg paths fail. Creds and port 554 were fine. The camera was re-added as id 52 with
  `/MediaInput/h264`.
- **Production DB "has no tables"** — unresolved, no access to the prod server from here. The
  connection string lives in the install folder's `config.ps1` (see CLAUDE.md → Deployment). Checks
  given to the user: print `Get-OdbcConnectionString $SqlDatabase` from the install folder, check
  `Get-ScheduledTaskInfo "APL Security Monitor"` + `logs\\server.log`, and in SSMS query
  `sys.dm_exec_sessions WHERE program_name='Python'` and `sys.tables` (+ refresh Object Explorer).
  Most likely causes: SSMS looking at a different instance/DB than `config.ps1`, the app failing to
  connect (log), or the app started without `start-server.ps1` → silent fallback to the dev laptop
  (`PGLHAM-ITLT03I\\SQLEXPRESS1`). At check time only the laptop itself was connected to its SQL
  Server. Proposed (not done): remove the fallback and log the target server at startup.
- **Release built**: `release\\APL-SecurityMonitor-2026.09.30-4b8c865.zip` (items 1–5). Items 6–7
  need a new build after merging `fisheye-4div`.
- **Dev backend**: on 2026-09-30 the port-8000 backend had stopped answering and was restarted
  from a Claude session (no `--reload`) — restart it after code changes.

## Gotchas learned

- Editing files with Python via a Bash heredoc on this Windows/Git-Bash setup can silently
  truncate at `'''` or mangle the heredoc; write the script with the file tool, then run it.
- `git status` may show files as modified with **no content diff** after edits that rewrote line
  endings; check with `git diff --ignore-cr-at-eol` before committing or building a release (the
  build marks the zip `-dirty`).
- `oxlint` (`npm run lint`) fails in this checkout with a missing native binding
  (`@oxlint/binding-wasm32-wasi`) — use `npx tsc -b` for the frontend check.
