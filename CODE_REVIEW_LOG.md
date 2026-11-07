# Code Review Log — branch `reviewCode`

Reviewed as a senior full-stack pass over the backend (FastAPI + YOLO vision
pipeline) and frontend (React/TS), focused on correctness, memory/VRAM use,
and the reported "forklifts are rarely detected" issue.

## Root cause: forklift detection

- Every camera's detector is hardcoded to `yolov8s.pt`
  (`backend/app/camera_manager.py:123`), the stock COCO-pretrained YOLO
  model. Its 80 classes do not include `forklift` (closest is `truck`/`car`),
  so forklifts are only ever picked up incidentally, at low confidence, when
  their shape happens to resemble a COCO `truck`/`car`.
- A purpose-trained forklift model already exists on disk at
  `backend/models/forklift_model.pt` (single class `forklift`, 150 epochs,
  mAP50 ≈ 0.95 per `runs/detect/output/forklift_runs/train_v2/results.csv`)
  but is **never loaded or referenced anywhere in the backend** — confirmed
  by a repo-wide search. A second candidate, `forklift_tug_model.pt`
  (3 classes: `forklift_with_load` / `forklift_without_load` / `tug`), was
  trained for only 56 epochs with noisier mAP50 (~0.65) and is also unused.
- **Fix applied**: wire `forklift_model.pt` in as a third shared model
  (loaded once, shared across all camera workers — same pattern as the
  existing PPE model), run alongside the main detector, and merge its boxes
  into the same tracker/zone pipeline so forklifts get tracked, zoned, and
  rate-limited exactly like any other vehicle.

## Applied changes

| # | File | Change |
|---|------|--------|
| 1 | `backend/app/config.py` | Added `forklift_model_path` to `EngineConfig`; added `"forklift"` to default `vehicle_class_names` so forklift detections classify as `kind="vehicle"` for zone/speed/separation rules. |
| 2 | `backend/app/vision_engine.py` | Load the forklift model through the existing shared-model cache; run it each frame alongside the main detector; merge detections (class ids offset to avoid colliding with COCO ids) before handing off to the tracker, so forklifts get a track id, zone membership, speed, and alerts like any other object. |
| 3 | `backend/app/camera_manager.py` | Added `FORKLIFT_MODEL_PATH` module global (mirrors the existing `PPE_MODEL_PATH` pattern) and wired it into `_build_engine`. |
| 4 | `backend/app/main.py` | Set `camera_manager.FORKLIFT_MODEL_PATH` at startup when `backend/models/forklift_model.pt` exists, mirroring the PPE model bootstrap. |
| 5 | `backend/app/vision_engine.py` | **Memory leak fix**: `track_history` (and the new per-track last-seen map) grew forever — entries were added per track id but never evicted, and ByteTrack ids increase monotonically for the life of a long-running camera worker. Added periodic pruning of tracks not seen for 30s, checked every 100 frames. |
| 6 | `backend/app/vision_engine.py` | Removed `last_alert_state` — declared but never read or written anywhere (dead field). |
| 7 | `backend/app/vision_engine.py`, `camera_manager.py` | Replaced silent `except Exception` handling with logged errors (`logging.exception` / `logging.warning`) so a failed model load or a crashed camera worker leaves a traceback in the logs instead of only a stringified `last_error`/`warnings.warn` that's easy to miss. |
| 8 | `backend/app/auth.py` | Added `get_user_from_token()`, a token-lookup helper usable outside a `Request` (refactored out of `get_current_user`), so WebSocket routes can authenticate the same session tokens the REST API uses. |
| 9 | `backend/app/main.py` | **Security fix**: `/ws/stream/{camera_id}` and `/ws/alerts` had no authentication — unlike every REST route — so anyone who could reach the server could watch any camera's live feed or the full alert stream. Both now require a valid session `token` query param (WebSocket clients can't set custom headers) and close with code 1008 if it's missing/invalid. |
| 10 | `frontend/src/hooks/useCameraStream.ts`, `useAlertToasts.ts`, `useConnectionStatus.ts` | Pass the stored session token as a `?token=` query param when opening each WebSocket, matching the backend auth change above. |

## Follow-up: duplicate detections after the forklift model was added

Reported via a screenshot (`Documents/Error/MultiDetection.jpg`): the same
real truck tracked twice (`#3`/`#121`, near-identical overlapping boxes),
and a forklift boxed both as `forklift` and as `truck` (`#122`/`#123`)
simultaneously. Root cause: merging the main detector's and the forklift
model's detections (added above) had no cross-model deduplication, and a
single vehicle could also dodge each model's own internal NMS at the
configured `detection_conf=0.2`.

**Fix**: `VisionEngine._dedup_vehicle_detections` (`vision_engine.py`) runs
a class-agnostic IoU-based NMS (`vehicle_nms_iou_threshold` in
`config.py`, default 0.5) after merging detector + forklift output and
before tracking, restricted to `kind == "vehicle"` boxes only. It never
touches or competes against `person` boxes, so a person legitimately
overlapping a vehicle (riding on the forks, a pedestrian/vehicle
separation breach) is never suppressed. Verified with a synthetic case
reproducing the screenshot's exact overlap pattern, plus a full pipeline
smoke test.

## Follow-up: aluminium racking misdetected as forklift + duplicate forklift ids

Reported via a screenshot (`Documents/Error/multiple-detection.jpg`, branch
`improve_detection`): stacked aluminium racking boxed as `forklift` (a false
positive), and the same physical forklift carrying two live track ids
(`#16`/`#22`) simultaneously.

- **False positive root cause**: the forklift/tug models were run at the
  same `detection_conf=0.2` as the main COCO detector. That threshold is
  tuned for COCO's 80 broad classes; on the single-class forklift model
  (mAP50 ≈ 0.95) it's loose enough to flag static clutter that vaguely
  resembles a forklift silhouette. **Fix**: added dedicated
  `forklift_detection_conf` / `tug_detection_conf` fields to `EngineConfig`
  (`config.py`, default 0.45), used instead of `detection_conf` when calling
  each model's `predict()` in `vision_engine.py`.
- **Duplicate-id root cause**: `_dedup_vehicle_detections`'s IoU-based NMS
  (added in the previous follow-up above) only suppresses a duplicate box
  if it overlaps enough to also share most of its *union* with the other
  box. The forklift model sometimes boxes the same physical forklift once
  around just the body and once stretched up to include the raised mast --
  a big/small pair whose IoU comes out under the 0.5 threshold (union is
  dominated by the larger box) even though the smaller box sits almost
  entirely inside the larger one. **Fix**: added
  `VisionEngine._suppress_contained_boxes`, a second pass after the IoU NMS
  that measures `intersection_area / smaller_box_area` and drops the
  lower-confidence box of any pair at or above
  `vehicle_containment_threshold` (`config.py`, default 0.7). Verified with
  a synthetic reproduction of the screenshot's box pair (IoU ≈ 0.47, passes
  the old NMS unsuppressed; collapses to one box with the new pass), plus
  regression cases confirming two genuinely distinct, non-overlapping
  vehicles are left untouched.

## Follow-up: people rarely detected

Reported directly by the user on branch `improve_detection`: real cameras
were rarely showing a person track at all.

- Ruled out first: shrinking the main detector's input via
  `detection_downscale` (from the earlier FPS follow-up) turned out not to
  be the cause -- a same-frame full-res vs. downscaled comparison on
  `test_warehouse.mp4` (960x540 vs. 640x360) returned identical person
  counts across 102 sampled frames. Still moved the main detector's
  `predict()` call back onto the full, non-downscaled frame anyway (only
  the throttled forklift/tug models keep the downscaled input) -- it's a
  no-cost-to-verify safeguard for footage where resolution loss *would*
  bite (smaller/more distant people than this test clip has), and it no
  longer conflates the detector's own accuracy with the FPS-tuning knob.
- **Actual root cause**: `sv.ByteTrack()` was constructed with defaults.
  Its `det_thresh` (the score a detection needs to *start a new track*) is
  hardcoded to `track_activation_threshold + 0.1` -- 0.35 with the library
  default of 0.25 -- independent of the detector's own `detection_conf`
  (0.2). Any person the detector reported at 0.2-0.35 confidence (routine
  for distant or partially-occluded people) passed the detector's filter
  but could never become a track, and `VisionEngine.process_frame` drops
  every detection with no track id (`if track_id is None: continue`) --
  so those people were silently invisible every single frame, not just
  flickering.
- **Fix**: `vision_engine.py` now constructs
  `sv.ByteTrack(track_activation_threshold=max(0.05, detection_conf - 0.1))`,
  so `det_thresh` lands at the detector's own confidence floor instead of
  0.15 above it -- anything the detector reports is now eligible to be
  tracked. Verified on `test_warehouse.mp4`: replaying the same 100 frames
  through the old (0.25) vs. new (~0.1) threshold picked up 2 additional
  distinct person tracks that the old threshold silently dropped, and the
  full pipeline smoke test went from 2 alert events (40 frames, old
  threshold) to 14 alert events (100 frames, new threshold) with no
  errors.

## Noted but not changed (out of scope for this pass)

- `backend/app/main.py:33-57` (`_add_missing_camera_columns`) hand-rolls
  schema migration via f-string DDL. Values come from a fixed internal
  dict today (not user input), so it's not currently exploitable, but a
  real migration tool (Alembic) would be safer long-term. Left as-is —
  replacing it is a bigger structural change than this pass's scope.
- `backend/app/main.py:100-105` CORS allows all methods/headers (origins are
  still restricted to the two local dev ports). Worth tightening before any
  non-localhost deployment, but left as-is to avoid breaking local dev
  without a deployment target to test against.
- `backend/app/config.py:46` / `camera_manager.py:126` hardcode
  `device="cuda"` with no CPU fallback. Left as-is: this deployment is
  explicitly GPU-based (see the VRAM-sharing work in commit `c28c8b6`), and
  there's no evidence this install ever runs without a GPU.
