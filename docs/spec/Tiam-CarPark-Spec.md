# Tiam – Car Park Security: Full Implementation Spec

> **Audience:** Claude Code, working in the Tiam repo on branch `retail-parking`.
> **Purpose:** turn Tiam (currently: person/vehicle detection + exclusion / speed / stop-required /
> time-window zone rules) into a complete car-park security system for **shopping-mall and hospital
> car parks** (New Zealand first).
> **This document replaces `Parking-Security-Feature-List.md`.** It lives in `docs/spec/`. It is meant to be complete: every
> feature, data change, API, page, setting, hardware item and acceptance check is described here.
> Where a choice had to be made, a **default decision** is written down (marked `DEFAULT:`) so work
> can start without asking. Section 16 lists those decisions so they can be challenged.

---

## 0. How to use this document

1. **Read `CLAUDE.md` and `CHANGELOG.md` first.** Everything here builds on the existing system
   (FastAPI + SQL Server + YOLO + ByteTrack backend, React 19 + Vite + Tailwind frontend, "Night
   Shift" theme). Do not rewrite what exists; extend it.
2. **Grill before building.** Run the `grill-with-docs` skill (Matt Pocock) on this document. It
   should interview the user one question at a time, starting with Section 16 (open decisions),
   then walk through each feature's edge cases. As decisions settle:
   - record domain terms in `CONTEXT.md` (seed it from the glossary in Section 3);
   - record architectural decisions as ADRs in `docs/adr/NNNN-title.md` (e.g. "VLM verification is
     optional and asynchronous", "Vector search uses a local FAISS index, not SQL Server").
   - If the user answers differently from a `DEFAULT:` below, the answer wins; update this spec.
3. **Build in the phase order of Section 14.** Each phase ends with its acceptance checks passing,
   `CLAUDE.md` updated to describe the new behaviour, and a dated `CHANGELOG.md` entry (what / why /
   files / how verified / open follow-ups), in the same style as the existing entries.
4. **Hard rules (from CLAUDE.md, never break):**
   - Never touch branch `main`, database `SecurityCamera` or `data/event_snapshots`. This work uses
     database `RetailParkingMonitor` and `data/retail_*` folders only.
   - No Alembic: every new model column must also be added to `_add_missing_columns()` in
     `main.py`; new tables come from `create_all`.
   - SQL Server rejects cascade cycles and self-referencing cascades: use plain INT columns (no FK)
     where a cycle would appear, and clean up in `crud` by hand, as `restricted_zone_id` does.
   - Never hard-code colours in the frontend; use the theme tokens. Backend box colours
     (`BOX_NORMAL`/`BOX_THREAT`) must stay in sync with `--accent`/`--critical`.
   - Camera worker threads must never block on network calls (VLM, speakers, webhooks, email).
     All such work goes through queues and background workers.
   - The two known security issues in CLAUDE.md (hard-coded Azure key fallback, seeded default
     admin password) must be **flagged to the user, not silently changed**. The new secrets handling
     in Section 6.4 must not repeat these mistakes.

---

## 1. Goal

A self-hosted, on-site video analytics system that:

- works on the site's **existing IP cameras** (plus a few dedicated ANPR / thermal cameras);
- detects the **real problems of mall and hospital car parks** (Section 2) with low false alarms;
- optionally sends each candidate alert to a **Vision-Language Model (VLM)** for a final
  "is this really happening?" check, with the provider and API key set in Settings;
- helps operators **act** (talk-down, dispatch, evidence for Police/insurers), not just watch;
- is **privacy-first** to fit the NZ Privacy Act 2020 and the Biometric Processing Privacy Code
  2025 (no face recognition, no emotion/intent/demographic inference).

**Success metrics (shown on the Analytics page):** false-alarm rate per event type, VLM reject rate,
time from detection to alert, operator time-to-acknowledge, incidents per week per site/zone.

---

## 2. Problems to cover → features

| Problem in car parks | Sites | Feature(s) |
|---|---|---|
| Theft from vehicles, break-ins, door-handle trying, catalytic converter theft | Both | F1 Car prowling, F3 Person down (under car), F7 Occupant mismatch |
| Vehicle theft | Both | F5 ANPR + watchlist, F7 Occupant mismatch, F6 Plate mismatch |
| Cloned / false plates | Both | F6 Plate mismatch |
| Loitering, rough sleeping, after-hours presence | Both | F2 Loitering |
| Assault / aggression, especially on staff walking to cars at night | Hospital (both) | F4 Fight, F11 Virtual escort, F14 Talk-down |
| Medical emergency / fall / person down | Hospital (both) | F3 Person down |
| Hooning, burnouts, boy-racer car meets | Mall | F9 Hooning & car meets |
| Ram-raid staging (vehicle at shopfront / footpath after hours) | Mall | F8 Vehicle rules (after-hours vehicle) |
| Wrong-way driving, speeding, failing to stop | Both | F8 Vehicle rules (existing speed + stop rules kept) |
| Parking in ambulance bay, fire lane, drop-off, disabled bay misuse | Hospital (both) | F8 Restricted parking + allowlist |
| Abandoned vehicles, overstay | Both | F5 ANPR sessions, F8 Abandoned vehicle |
| Vehicle / EV fire | Both | F10 Fire, smoke & thermal |
| Trolley theft | Mall | F12 Trolley boundary (optional) |
| Slow investigations ("find the white ute from last night") | Both | F13 Search & cross-camera journey |
| Operator overload / false alarms | Both | F0 VLM verification, F15 Notifications |
| Evidence for Police / insurers | Both | F16 Evidence pack |
| Privacy compliance | Both | F17 Privacy & audit |

---

## 3. Glossary (seed for `CONTEXT.md`)

| Term | Meaning |
|---|---|
| **Site** | One car park property (e.g. "Westfield Riverside", "Middlemore Staff Lot"). New concept; today the system is single-site. |
| **Camera** | Existing `Camera` row. Gains a `role` (general / anpr_entry / anpr_exit / thermal / ptz). |
| **Zone** | Existing per-camera polygon with rules. Gains new rule kinds (Section 7). |
| **Track** | One object followed by ByteTrack on one camera (`track_id`). |
| **Detector** | A module in `app/analytics/` that reads tracks + history and emits **candidate events**. |
| **Candidate event** | Raw output of a detector before dedupe and verification. |
| **Incident** | A deduped candidate event persisted as an `Event` row (existing `_IncidentTracker` logic). UI calls it "Incident". |
| **Verification** | Optional VLM check of an incident. Produces a **verdict**: `confirmed`, `rejected`, `uncertain`, or `skipped`/`error`. |
| **Gate mode** | Verification setting where a `rejected` incident is not alerted (still stored for audit for N days). |
| **Vehicle session** | One visit of one vehicle: entry → parked bay(s) → exit. Keyed by plate when known, otherwise by vehicle signature. |
| **Vehicle signature** | Plate (if read) + make/colour/type + visual embedding of the vehicle. |
| **Occupant signature** | Short-lived appearance embedding (clothing etc.) of a person who got out of a parked vehicle. Deleted when the vehicle session ends. |
| **Watchlist / Allowlist** | Plate lists: watchlist → alert on sight; allowlist → allowed in restricted bays/zones. |
| **Escort** | A virtual-escort session for a staff member walking to their car. |
| **Deterrence action** | Automatic or operator action on site: speaker message, strobe, siren, PTZ preset. |
| **Evidence pack** | Exported bundle (clips, snapshots, timeline, plates, hashes) for one incident. |
| **Risk score** | Existing 1–10 severity (`risk.score_event`). Red ≥ 8, amber ≥ 5, else green. |

---

## 4. Current system (summary – see CLAUDE.md for detail)

- One `_CameraWorker` thread per enabled camera; `_SharedCapture` keeps the newest frame + arrival
  time; frames resized to `FRAME_SIZE = (960, 540)`; `TARGET_FPS = 18`.
- `VisionEngine.process_frame(frame, ts)`: YOLO (`yolov8s.pt`, CUDA) → class confidence filters →
  vehicle dedup → shadow filter → `sv.ByteTrack` (`lost_track_buffer=90`) → zone rules
  (`exclusion`, `speeding`, `failed_to_stop`, time windows) → annotated frame + events.
- `_IncidentTracker` dedupes into one incident per breach (60 s cooldown, merge by position).
- `crud.create_event` + snapshot JPEG in `data/retail_event_snapshots/{id}.jpg`; alert pushed on
  `alert_queue` → `/ws/alerts`.
- Pages: Live Monitor, Cameras, Zone Types, Zone Studio, Calibration, Fisheye Setup, Coaching
  Workbench (incident review), Incident Search (rule-based natural language), Detection Settings,
  Analytics, Heatmaps, Users, Roles.
- 4-point calibration gives an image → ground-metres homography (`CalibrationConfig.ground_points`).
  **All distance/speed based features below rely on it.**

---

## 5. Target architecture

```
Camera ─► _SharedCapture ─► _CameraWorker
                              │
                              ├─► FrameRing (last ~20 s, 5 fps, JPEG in memory)      [new]
                              │
                              └─► VisionEngine.process_frame
                                     detector (YOLO) → filters → ByteTrack
                                     ├─► PoseRunner (person keypoints, throttled)     [new]
                                     ├─► AttributeRunner (vehicle colour/type, crops)  [new]
                                     ├─► existing zone rules
                                     └─► Analytics detectors (app/analytics/*.py)      [new]
                                            → candidate events
                              ─► _IncidentTracker (existing dedupe)
                              ─► IncidentPipeline (app/incident_pipeline.py)          [new]
                                     1. persist Event + snapshot + clip (from FrameRing)
                                     2. if VLM enabled for this type → VerificationQueue
                                        else → AlertDispatcher
                              ─► VerificationWorker (async, N concurrent)              [new]
                                     builds key frames → VLM provider → verdict JSON
                                     → update Event → AlertDispatcher (or suppress in gate mode)
                              ─► AlertDispatcher                                       [new]
                                     /ws/alerts, notifications (webhook/email/SMS),
                                     deterrence actions (speaker/strobe/PTZ)

Site-level services (one per app, not per camera):                                   [new]
  VehicleSessionService  – joins ANPR entry/exit + parked-vehicle tracks into sessions
  ConvoyMonitor          – site-wide entry-rate / after-hours checks (hooning, car meets)
  EmbeddingIndexer       – stores person/vehicle embeddings for search (FAISS on disk)
  RetentionJob           – deletes old clips, embeddings, sessions per retention settings
```

### 5.1 Detector module contract

Each detector lives in `backend/app/analytics/<name>.py` and implements:

```python
class Detector(Protocol):
    name: str                      # e.g. "car_prowling"
    event_types: list[str]         # event types it can emit
    def update(self, ctx: FrameContext) -> list[CandidateEvent]: ...
    def prune(self, live_track_ids: set[int]) -> None: ...
```

`FrameContext` contains: `camera_id, ts, frame (clean, 960×540), tracks` (id, class, box, ground
point in metres, speed, zone hits, optional pose keypoints, optional attributes),
`calibration`, `zones`, `settings`. Detectors keep their own per-track state and must prune it.
`VisionEngine` holds a list of enabled detectors per camera (built from settings + zones at worker
start, same as zones today). A detector must run in < 2 ms per frame on average (no network, no
heavy models – heavy models are shared runners).

`CandidateEvent` = existing event dict shape (`type`, `zone_id?`, `zone_name`, `track_id?`, plus
type-specific fields) + `key_track_ids`, `bbox_hint`, `severity_hint`. It flows through
`_IncidentTracker` and `risk.score_event` like today.

### 5.2 Shared runners (heavy models)

- **PoseRunner**: `yolo26s-pose.pt` (fallback `yolov8s-pose.pt`) on person crops, only for tracks
  that a detector requests (e.g. inside a car-park zone, or flagged for fall/fight checks), at most
  every `pose_interval_frames` (DEFAULT: 3). Batched per frame.
- **AttributeRunner**: vehicle colour (HSV histogram on the car body crop, mapped to 12 colour
  names) and type (from YOLO class + optional classifier). Runs once when a vehicle track becomes
  stable (≥ 1 s, box area above threshold) and when it parks. Make/model: from the ANPR camera's
  API if available (Section 9), otherwise "unknown" (DEFAULT: no make/model model of our own in
  phase 1–3).
- **EmbeddingRunner**: one image-embedding model (DEFAULT: OpenCLIP ViT-B/32 or SigLIP-base via
  `open_clip`, GPU, FP16) used for person/vehicle re-identification and text search. Runs on the best
  crop of each track (largest, sharpest) once per N seconds.
- **YOLO26 migration:** add Detection Settings field `detector_model` (dropdown of `.pt` files in
  `backend/models/` + `yolov8s.pt`). DEFAULT stays `yolov8s.pt` until YOLO26 is validated on site
  footage. When exporting YOLO26 to TensorRT, verify the end-to-end (NMS-free) head is kept and
  that the existing NMS/containment dedup still behaves.

### 5.3 FrameRing and clips

- Per camera, keep the last `clip_pre_seconds` (DEFAULT 10 s) of clean frames at
  `clip_fps` (DEFAULT 5) as JPEG bytes (≈ 40 KB each → ≈ 2 MB per camera).
- On incident: keep collecting `clip_post_seconds` (DEFAULT 10 s), then write
  `data/retail_event_clips/{event_id}.mp4` (H.264 via OpenCV/FFmpeg, annotated boxes drawn) in a
  background thread. `Event.has_clip = True`.
- The VLM gets **key frames from the ring** (Section 6.3), not the MP4.

---

## 6. F0 – Optional VLM verification (with API key in Settings)

### 6.1 Behaviour

- **Off by default.** The system must be fully useful without any VLM.
- When enabled, each new incident whose event type has verification enabled is queued for
  verification. Camera threads never wait for it.
- Per event type, an admin chooses a **mode**:
  - `off` – no verification;
  - `annotate` – alert is sent immediately; the verdict is added when it arrives (UI updates live
    over `/ws/alerts` with a `verification` message);
  - `gate` – alert is held until the verdict arrives (max `gate_timeout_s`, DEFAULT 8 s). `confirmed`
    or `uncertain` → alert; `rejected` → no alert, event stored with `vlm_verdict=rejected` and
    auto-deleted after `rejected_retention_days` (DEFAULT 7). Timeout or error → alert as
    "unverified" (never lose a real alert because the VLM is down).
- DEFAULT modes: `gate` for car_prowling, loitering, person_down, fight, occupant_mismatch,
  hooning, fire_smoke; `annotate` for everything else; `off` for plate_watchlist (plate reads are
  already specific).
- **Budget guard:** `max_calls_per_hour` (DEFAULT 120) and `max_concurrent` (DEFAULT 2). Above the
  cap, incidents are alerted as "unverified" and a system warning is shown once.

### 6.2 Providers (pluggable)

`backend/app/vlm/` with a `VLMProvider` interface:
`verify(images: list[bytes], prompt: str, schema: dict, timeout_s) -> VerdictResult`.

Implement these providers:

| Provider id | Covers | Notes |
|---|---|---|
| `openai_compatible` | OpenAI, Azure OpenAI, **local vLLM / Ollama / LM Studio / NVIDIA NIM** (all speak the OpenAI chat-completions API) | Base URL + model + API key (key optional for local). Use JSON-schema / JSON mode where supported. |
| `anthropic` | Claude models | Messages API with image blocks; JSON via tool/structured output. |
| `google` | Gemini | `generateContent` with inline images; JSON response schema. |

Use the official Python SDKs where they exist (`openai`, `anthropic`, `google-genai`), add them to
`requirements.txt`. All calls have timeouts, 1 retry with backoff, and full error capture into the
event's `vlm_error`.

DEFAULT local model suggestion (documented in the UI help text): Qwen3-VL 8B or NVIDIA Cosmos
Reason 2 8B served by vLLM/Ollama on the site GPU (needs ≥ 16 GB VRAM; the dev RTX 3050 is too
small, so use a cloud provider for development tests).

### 6.3 Request content

- **Images:** 4–8 key frames from the FrameRing covering `[t-6 s, t+2 s]` around the incident,
  each a crop around the involved tracks (box expanded ×2.5, min 384 px, max 1024 px long side) plus
  one full-frame thumbnail (768 px wide). Boxes drawn with track ids. Faces are **not** blurred for
  the VLM (it needs to see actions) but nothing is retained by us beyond the event clip.
- **Prompt:** per-event-type template stored in DB (editable by admin, with "reset to default").
  Every template:
  - states the site type, camera name, zone name, local time, event type and the detector's reason
    (e.g. "track 27 stopped beside 3 vehicles for 6–14 s each");
  - asks only about **observable actions**, never emotions, intent, health, ethnicity, age or
    gender (NZ Biometric Code rule 10);
  - lists the common false-alarm explanations for that type (e.g. for car_prowling: owner loading
    the boot, parking attendant, cleaner, person looking for their own car, valet);
  - requires the JSON below.
- **Response schema (all providers):**

```json
{
  "verdict": "confirmed | rejected | uncertain",
  "confidence": 0.0,
  "observed_actions": ["short factual phrases"],
  "reason": "one or two sentences, factual, no speculation about identity or intent",
  "severity_suggestion": 1,
  "person_description_for_talkdown": "clothing/colour only, e.g. 'dark hoodie, grey pants' or null"
}
```

- `confidence < vlm_min_confidence` (DEFAULT 0.6) is treated as `uncertain`.

### 6.4 Settings page and secret storage

New admin page **`/admin/ai-verification`** ("AI Verification", nav icon `Sparkles`), `PAGE_KEY`
`ai_verification`:

- Master toggle **Enable AI verification**.
- **Provider** dropdown (Section 6.2), **Base URL** (prefilled per provider, editable), **Model
  name**, **API key** (password input).
- **Test connection** button → `POST /api/vlm/test` sends one built-in test image and shows the
  parsed verdict + latency.
- Timeouts, `max_concurrent`, `max_calls_per_hour`, `gate_timeout_s`, `vlm_min_confidence`,
  `rejected_retention_days`.
- **Per event type table:** mode (off/annotate/gate), prompt template editor, "reset prompt".
- **Usage panel:** calls today, average latency, confirm/reject/uncertain counts, errors.
- Option **"Local only"** – refuse any provider whose base URL is not a private/LAN address (for
  hospitals that forbid sending video off site).

**Secret storage rules (must follow):**
- API keys are encrypted at rest with Fernet (`cryptography`). The encryption key comes from env
  var `TIAM_SECRET_KEY`; `start-server.ps1` / `config.ps1` generate and pass it on install.
  If the env var is missing, the AI Verification page shows "secret key not configured" and refuses
  to save keys. **No hard-coded fallback key, ever.**
- The API never returns a stored key; GET returns `api_key_set: true` and `api_key_last4`.
  Saving with an empty key field keeps the old key; a "Remove key" button deletes it.
- The same `SecretStore` (`app/secrets_store.py`) is used for all other new secrets (webhook tokens,
  SMS gateway key, speaker passwords). Do not change the existing Azure email secret handling
  without asking the user (flag it).

### 6.5 Data

- New table `vlm_settings` (singleton, like `detection_settings`): provider, base_url, model,
  api_key_encrypted, enabled, local_only, timeouts/limits.
- New table `vlm_event_type_settings`: `event_type (unique), mode, prompt_template`.
- New `events` columns: `vlm_status` (none/pending/done/error/skipped), `vlm_verdict`,
  `vlm_confidence`, `vlm_reason`, `vlm_observed` (JSON), `vlm_model`, `vlm_latency_ms`,
  `vlm_error`, `verified_at`.
- New table `vlm_usage` (day, calls, errors, total_latency_ms, by verdict).

### 6.6 UI

- Incident cards (Coaching Workbench, Live Monitor toasts): VLM chip – `✓ Confirmed 0.91`,
  `◐ Uncertain`, `✕ Rejected`, `… Verifying`, `Unverified`.
- Incident detail: "AI reasoning" block (observed actions + reason + model + latency).
- Coaching Workbench filter: verdict.

### 6.7 Acceptance

- With VLM disabled, every feature works and no VLM code path is hit.
- With a fake provider (unit-test double) returning each verdict: annotate/gate behave as
  specified, timeout → "unverified" alert, cap exceeded → "unverified".
- Stored key is never in API responses, logs or `raw_payload`; DB holds ciphertext only.
- Test connection works against at least one real provider.

---

## 7. Zone and rule model changes

Keep the existing rule fields. Add new zone **kinds** as booleans/params on `Zone` and `ZoneType`
(same "default_" convention on ZoneType, all added to `_add_missing_columns`):

| Field | Used by |
|---|---|
| `rule_loitering` + `loiter_seconds` (DEFAULT 120 person / 300 vehicle) | F2 |
| `rule_prowling` (car-park bay area where prowling is checked) | F1 |
| `rule_restricted_parking` + `restricted_max_minutes` (0 = never) + `allowlist_id?` | F8 |
| `rule_one_way` + `direction_vector` (JSON 2 points drawn as an arrow in Zone Studio) | F8 wrong-way |
| `rule_after_hours_vehicle` (shopfront / footpath; uses the time window) | F8 ram-raid staging |
| `rule_trolley_boundary` | F12 |
| `rule_escort_area` (staff parking / walkway for virtual escort) | F11 |
| `is_bay_area` (marks parking bays for sessions, occupancy, prowling) | F1, F5, F7 |
| `is_entry` / `is_exit` (gate / ramp lines for counting and sessions) | F5, F9 |

New seeded system zone types: Parking Bays, Restricted Bay (Ambulance / Fire lane / Drop-off),
Disabled Bays, One-Way Lane, Shopfront After Hours, Staff Parking (Escort), Entry, Exit, Trolley
Boundary, Loitering Watch.

Zone Studio: add the new checkboxes/params, an arrow tool for one-way direction, and a colour/icon
per zone kind on the canvas.

---

## 8. Feature specifications

Each feature: **What**, **Detection logic**, **Event type & risk**, **Config**, **VLM**,
**UI**, **Acceptance**, **Hardware**. Distances/speeds use the active calibration; a camera without
an active calibration shows a warning in Zone Studio for features that need it.

### F1 – Car prowling / break-in (top priority, market gap)

- **What:** a person who goes car to car, stops beside several parked vehicles without getting into
  any, crouches at a door or under a car, or reaches for handles.
- **Logic** (detector `car_prowling`, person tracks inside a `rule_prowling` / `is_bay_area` zone):
  - Keep the set of parked vehicles (vehicle tracks stationary ≥ 30 s, from F5 sessions or a local
    stationary check).
  - A **visit** = person ground point within 1.2 m of a parked vehicle's box footprint for ≥ 3 s.
  - Score rises with: number of distinct vehicles visited in the last 5 min (≥ 3 → strong), long
    visits (≥ 10 s) without the person entering the vehicle, **crouch/low pose** beside a vehicle
    (PoseRunner: hips below knees level or torso height < 50 % of standing height), wrist keypoints
    at handle height near the door edge, glass-break audio (F4 audio, optional), after-hours time
    window.
  - Fire `car_prowling` when the score ≥ threshold (Detection Settings `prowling_sensitivity`,
    DEFAULT medium). Suppress if the person later opens and enters the vehicle they are beside
    (track disappears into the vehicle box and that vehicle starts moving within 2 min).
  - Person **under / lying beside** a vehicle for ≥ 10 s → also `car_prowling` with sub-type
    `under_vehicle` (catalytic converter theft), unless F3 classifies as injured.
- **Risk:** 8 (under_vehicle 9).
- **VLM:** gate mode; prompt lists false-alarm cases (own car, loading, attendant, cleaner, valet,
  child, looking for car with key fob).
- **UI:** trail of visited vehicles drawn on the snapshot (numbered).
- **Acceptance:** replay test clips (Section 13) – staged prowling ≥ 80 % detected; people walking to
  their own car, loading boots, cleaners: false alarms ≤ 1 per camera per day after VLM gate.
- **Hardware:** existing cameras with ≥ 60 px person height at the bays; optional audio.

### F2 – Loitering (person and vehicle)

- **What:** person or vehicle staying in a watched zone longer than allowed (rough sleeping,
  lookouts, vehicle waiting with engine running near the exit).
- **Logic:** time inside `rule_loitering` zone with a re-entry tolerance of 30 s (leaving briefly
  doesn't reset). Vehicle loitering = vehicle not in a bay, moving < 2 km/h, for `loiter_seconds`.
- **Risk:** 5 (after hours via time window: 7).
- **VLM:** gate; false alarms: waiting for pickup, smoking break, staff, delivery driver.

### F3 – Person down / fall

- **What:** someone falls, collapses, or lies still (medical emergency), important for hospitals.
- **Logic:** PoseRunner on persons; **fall** = torso angle change from vertical to near-horizontal
  in < 1.5 s, or box aspect ratio flip (h/w from > 1.5 to < 0.8) plus ground point drop; **down** =
  lying posture and ground point moving < 0.3 m for ≥ `person_down_seconds` (DEFAULT 15). Lying
  next to/under a vehicle → hand to F1 as `under_vehicle` unless the VLM says injured.
- **Risk:** 9.
- **VLM:** gate (short timeout 5 s); prompt must separate: injured/collapsed vs. working on a car vs.
  sitting/resting vs. child playing. Medical-urgent incidents are alerted even if the VLM times out.

### F4 – Fight / aggression (+ optional audio)

- **What:** physical fight, assault, pushing, chasing.
- **Logic:** two or more persons within 1.5 m with high relative limb motion (keypoint velocity of
  wrists/ankles above threshold for ≥ 1 s), rapid approach (closing speed > 3 m/s), one person
  falling during a close interaction. Optional audio: scream/shout/glass-break classification from
  camera audio (Section 9.4).
- **Risk:** 9. **VLM:** gate; describe actions only ("one person strikes another").
- **Acceptance:** staged clips; hugging, kids playing, people running for the bus are rejected after
  VLM.

### F5 – ANPR, vehicle attributes and vehicle sessions

- **What:** read plates at entries/exits (and optionally on patrol cameras), keep an entry/exit log,
  dwell time, watchlist/allowlist alerts, partial-plate search.
- **Two ways to get plates.** DECIDED (2026-11-08, ADR 0002): the first site has no ANPR cameras,
  so **B is built first** and plate reading is **optional per camera** (off by default; every other
  feature works without plates). A is deferred until a site has ANPR cameras.
  - **A. ANPR camera integration:** ingest plate events from the camera's own analytics (Axis
    License Plate Verifier HTTP events, Hikvision ANPR ISAPI events, generic webhook). Gives plate,
    confidence, direction, often make/model/colour, plate crop image. New router
    `POST /api/anpr/ingest/{camera_id}` with a per-camera token.
  - **B. Built-in ANPR pipeline:** plate detector (YOLO trained on plates – dataset task in
    Section 12) on vehicle crops → OCR (DEFAULT `fast-plate-ocr`, alternative PaddleOCR) →
    NZ plate format validation (1–6 alphanumerics; regex + common OCR confusion fixes O/0, I/1,
    B/8) → vote across frames of the same track (≥ 3 reads, majority).
- **Vehicle sessions** (`VehicleSessionService`): entry read creates a session; parked tracks inside
  `is_bay_area` zones are linked to the session by time + vehicle signature (plate if seen on that
  camera, else colour/type + embedding similarity); exit read closes it. Unmatched parked vehicles
  get an anonymous session.
- **Watchlist / allowlist:** tables `plate_lists` (name, kind watchlist/allowlist, colour, alert
  severity) and `plate_list_entries` (plate, note, expires_at, added_by). Fuzzy match (edit distance
  ≤ 1) for watchlist with "partial match" label. Watchlist hit → `plate_watchlist` (risk from list).
- **Overstay:** session longer than site max stay → `overstay` (risk 3, no VLM).
- **Data:** `plate_reads` (camera_id, ts, plate, confidence, direction, make, model, colour, type,
  crop path, track_id, session_id), `vehicle_sessions` (plate?, signature JSON, entry_ts, exit_ts,
  bays JSON, status).
- **UI:** new page **Vehicles** (`/vehicles`): live entry/exit feed, search by plate (partial,
  wildcard `*`), colour, type, time; session detail with timeline across cameras; watchlist/allowlist
  management.
- **Acceptance:** with a dedicated ANPR camera (A): ≥ 95 % plate accuracy at the gate. With B on a
  good angle: ≥ 85 % per vehicle after voting. Sessions open/close correctly on replay.
- **Hardware:** ANPR cameras (Section 11).

### F6 – Plate mismatch (cloned / false plates)

- **What:** same plate seen on a vehicle that doesn't match the plate's known vehicle.
- **Logic:** compare current read's colour/type/make (if available) with (a) the plate's own
  history in our DB (last 90 days, majority values), and (b) optional external vehicle register
  lookup (NZTA/MotorWeb via a pluggable `PlateLookupProvider`; DEFAULT disabled – needs a commercial
  agreement). Mismatch in type or colour family (with ≥ 3 historic sightings) →
  `plate_mismatch`. Same plate at two exits/entries far apart in an impossible time → also
  `plate_mismatch` (sub-type `duplicate_plate`).
- **Risk:** 6. **VLM:** annotate (compare the two vehicle crops: "same vehicle model and colour?").

### F7 – Occupant mismatch ("Car Guard") – user's idea

- **What:** remember who got out of a parked car; when someone gets into the driver side and drives
  away, check they look like one of those people. Groups may come back with fewer people – that's
  fine as long as the driver matches one of the original occupants.
- **Logic** (detector `occupant_match`, cameras covering bays):
  1. When a vehicle becomes parked (session), open an **occupant window** of 3 min.
  2. Person tracks whose first ground point is within 1 m of the vehicle's door sides during the
     window (they "came out of" the car) become **occupants**. Store per occupant: 3–5 best crops →
     EmbeddingRunner vector (clothing/appearance), upper/lower clothing colour, estimated height
     (from pose: ankle-to-head in ground metres via homography, and relative to the vehicle's roof
     height as a cross-check), timestamps. Count = N.
  3. **Return:** a person track ends at the vehicle's driver door area and the vehicle starts moving
     within 3 min → compare that person (and any others who entered) to the occupants:
     appearance similarity ≥ `occupant_match_threshold`, height within ±12 cm (weak cue, only used
     when both heights are reliable).
  4. Mismatch does **not** alert by itself. It adds risk: mismatch + any of (F1 prowling earlier on
     this person, > 20 s at the door before entering, after-hours, no indicator-light flash on
     unlock – see below, vehicle on watchlist) → `occupant_mismatch` incident.
  5. **Unlock flash check:** brightness spike in the vehicle's headlight/indicator regions within 5 s
     before the door opens (simple frame differencing in the front/rear corner areas of the vehicle
     box). Flash seen = strong sign the person has the key → suppress.
  6. Occupant signatures are deleted when the session ends (vehicle leaves) or after 24 h.
- **Car Guard opt-in (DEFAULT on, recommended):** staff (hospital) or customers (mall) register a
  plate in Tiam (`car_guard_registrations`: plate, contact, notify_by sms/email/push, expires).
  For registered plates, a mismatch alone triggers a notification to the owner: "Someone is getting
  into vehicle KMT482 – is this you?" with a snapshot, Yes/No links (No → incident risk 9 to
  operators). Non-registered vehicles use the risk-combination rule above.
- **Risk:** 7 (registered owner says "No": 9).
- **VLM:** gate; prompt compares the "exited" crops vs. the "entering" crop, told to ignore
  carried bags/jackets and to judge clothing/build only.
- **Limits to show in the UI help:** needs a camera with a clear view of the vehicle's doors; clothing
  changes (hospital staff changing into scrubs, new purchases) cause mismatches; IR night video has
  no colour.
- **Acceptance:** replay of ≥ 30 real parking sessions: correct driver match ≥ 85 %; staged "other
  person drives away" detected; false incidents (non-registered) ≤ 1 per camera per week.

### F8 – Vehicle rules

Existing speeding and stop-required stay. Add:

- **Wrong-way** (`rule_one_way`): vehicle velocity direction more than 120° from the zone arrow for
  ≥ 1.5 s and ≥ 3 m travelled → `wrong_way` (risk 6).
- **Restricted parking** (`rule_restricted_parking`): vehicle stationary in zone >
  `restricted_max_minutes` and plate not on the zone's allowlist → `restricted_parking`
  (risk 5; ambulance bay / fire lane preset risk 7). Disabled bays: allowlist = registered permit
  plates (DEFAULT; NZ mobility permits aren't plate-linked, so allowlist is site-managed).
- **Abandoned vehicle:** session open > `abandoned_hours` (DEFAULT 48) or parked outside
  trading hours past closing + 6 h → `abandoned_vehicle` (risk 3).
- **After-hours vehicle at shopfront / footpath** (`rule_after_hours_vehicle` + time window):
  vehicle enters or stops in zone → `after_hours_vehicle` (risk 8, ram-raid staging). Reverse
  approach toward the shopfront line at > 5 km/h → risk 10.
- **VLM:** annotate for all except after_hours_vehicle (gate, short timeout).

### F9 – Hooning, burnouts and car meets

- **What:** burnouts/doughnuts, drifting, racing, groups of cars meeting after hours.
- **Logic:**
  - **Burnout/doughnut:** vehicle track with high yaw/curvature (heading change > 270° within 6 s,
    radius < 8 m) or speed > 2× the car park limit; plus optional **smoke** from F10 near the vehicle.
  - **Convoy / car meet** (`ConvoyMonitor`, site-level): ≥ `convoy_min_vehicles` (DEFAULT 5)
    entries within `convoy_window_min` (DEFAULT 10) outside trading hours, or ≥ 6 vehicles stopped
    close together (< 3 m) with people standing around for ≥ 5 min.
  - On fire: start an **evidence capture** – collect every plate read on site for the next 30 min and
    attach to the incident.
- **Event:** `hooning` (risk 8), `car_meet` (risk 6).
- **VLM:** gate for `hooning` (smoke/tyre marks/circular motion), annotate for car_meet.
- **Why it matters (NZ):** the 2026 anti-social road use law allows vehicle forfeiture/crushing;
  plates + clips are the evidence Police need.

### F10 – Fire, smoke and thermal hotspot

- **Logic:** (a) visual model `fire_smoke.pt` (YOLO trained on fire/smoke, dataset task in
  Section 12) on full frames every `fire_interval_frames` (DEFAULT 10), confirm in ≥ 3 of 5 runs and
  growing area; (b) **thermal cameras** (`camera.role = thermal`, radiometric): read temperature via
  the camera's API/ONVIF or analytics event (DEFAULT: ingest the camera's own temperature-alarm
  event through `POST /api/camera-events/ingest/{camera_id}`), threshold `thermal_alarm_c`
  (DEFAULT 70 °C) and rate of rise.
- **Event:** `fire_smoke` (risk 10), `thermal_hotspot` (risk 8).
- **VLM:** gate with 5 s timeout for visual-only; thermal alarms are never gated.
- **Notifications:** always notify (Section F15) regardless of quiet hours.

### F11 – Virtual escort (hospital staff safe-walk)

- **What:** staff start an escort from a phone page; operators see them followed camera-to-camera to
  their car; alert if someone follows or approaches.
- **Flow:**
  1. Staff open `/escort` (mobile web page, PWA, no app store) – staff log in once (new role
     "Staff" with only the escort page), pick parking area / bay or plate, tap **Start escort**.
  2. Operator console shows an **Escort card**: staff name, destination, live camera auto-switching
     to whichever camera currently sees them.
  3. **Hand-off:** the system picks the person's track on the start camera (the person nearest the
     selected exit door at start time; operator can click to correct), then re-identifies them on
     the next cameras by appearance embedding + expected camera adjacency (camera graph:
     `camera_links` table, drawn in a new "Site map" admin page with travel times).
  4. **Alerts:** another person within 5 m behind for ≥ 15 s matching their path (following),
     person approaching fast (> 2 m/s closing), staff stopped > 60 s before reaching the car, staff
     track lost for > 20 s → `escort_alert` (risk 9) + loud UI alert + optional speaker message.
  5. Ends when the staff's vehicle leaves or staff tap **I'm safe**; max 15 min.
- **Help points:** `POST /api/camera-events/ingest` also accepts help-point/intercom button events
  → `help_point` incident (risk 8) with the nearest camera.

### F12 – Trolley boundary (optional, mall)

- Custom class `trolley` in the main detector (dataset task). Trolley track crosses out of a
  `rule_trolley_boundary` zone → `trolley_exit` (risk 2, no VLM, no live toast; daily report only).

### F13 – Search and cross-camera journey

- **Extend the existing Incident Search** (`incident_search.parse_query`) to cover the new event
  types and fields (plate, colour, vehicle type, verdict).
- **New "Search" page** (`/search`) with two modes:
  - **Attribute search:** object (person/vehicle), colour(s), vehicle type, plate (partial), time
    range, cameras/zones, event types.
  - **Natural-language search:** text → EmbeddingRunner text embedding → nearest track crops in the
    FAISS index (`data/retail_embeddings/{yyyy-mm-dd}.faiss` + metadata in SQL table
    `track_index`: camera, track_id, start/end ts, class, best crop path, colour, plate?). Results
    as a grid of crops with time/camera; click → play clip from recordings (Section 9.5) or show the
    crop + snapshot.
  - **Similar search:** click any result → "find similar" (image embedding) across cameras.
- **Journey:** select a person/vehicle → ordered list of sightings across cameras (embedding
  similarity + camera adjacency + time), shown on a timeline and the site map.
- **DEFAULT store:** FAISS (`faiss-cpu`) files per day + SQL metadata; retention 30 days.
- **Optional VLM:** if enabled, "Ask" box sends the top 10 results + question to the VLM for
  re-ranking/answering ("which of these is carrying a crowbar?").

### F14 – Deterrence (talk-down, strobe, siren, PTZ)

- **Devices:** new table `devices` (type speaker/strobe/siren/ptz/relay, protocol, address,
  credentials via SecretStore, linked cameras/zones). Protocols (DEFAULT order): HTTP API of the
  device (Axis audio / VAPIX, generic URL with template), ONVIF (PTZ presets, relay outputs), SIP
  call (speakers that support it, phase 4).
- **Messages:** pre-recorded audio files and **TTS** (offline Piper TTS, NZ English voice) –
  templates like "Attention: you are being recorded. Security has been notified." with optional
  `{description}` filled from the VLM's `person_description_for_talkdown` (only clothing/colour).
- **Deterrence policies** (`deterrence_policies`): per event type + zone + time window, a staged
  sequence, e.g. `0 s: recorded warning` → `20 s if still present: TTS with description` →
  `40 s: strobe + siren` → `60 s: escalate to operator / notify`. Each step can require VLM
  `confirmed` first. "Still present" = the detector still sees the track in the zone.
- **Operator buttons:** Talk-down (pick message or type text → TTS), Strobe, Siren, PTZ preset,
  Live mic (push-to-talk via browser `getUserMedia` → backend → speaker; phase 4).
- **Audit:** every action logged (who/what/when).
- **Acceptance:** with a real IP speaker on the LAN, policy plays within 2 s of the trigger.

### F15 – Notifications and escalation

- Today alerts only go to `/ws/alerts`. Add `notification_rules`: event types + min risk + sites/
  zones + time windows (quiet hours) → channels:
  - **Webhook** (JSON POST, HMAC signature) – for monitoring centres / Teams / Slack;
  - **Email** (existing Azure email service);
  - **SMS** (pluggable provider; DEFAULT generic HTTP SMS gateway template);
  - **Browser push** for the operator PWA.
- Escalation: if an incident with risk ≥ 8 isn't acknowledged in N minutes → next channel.
- Incident **acknowledge** action and `acknowledged_by/at` columns (operator accountability).

### F16 – Evidence pack

- Button in incident detail → `POST /api/events/{id}/evidence-pack` → ZIP:
  clip MP4, snapshots, plate crops, timeline (JSON + PDF summary), VLM reasoning, operator comments,
  deterrence/audit log, SHA-256 of every file + manifest signed with a site key.
- Option **blur bystanders**: blur all faces (face detector, e.g. YuNet/SCRFD, detection only, no
  recognition) and all plates except the involved vehicles.
- Export logged in the audit log with reason ("Police request #…").

### F17 – Privacy, retention and audit (NZ)

- **No face recognition, no emotion/intent/demographic inference.** Re-identification uses
  clothing/appearance embeddings that are short-lived (occupants: until session end; search index:
  `embedding_retention_days`, DEFAULT 30).
- **Retention settings:** snapshots/clips (DEFAULT 30 days), plate reads (DEFAULT 90 days), rejected
  VLM events (7), embeddings (30), audit log (2 years). `RetentionJob` runs nightly. Incidents marked
  **Legal hold** are never auto-deleted.
- **Audit log** table `audit_log` (user, action, target, reason, ts, ip): searches, plate lookups,
  exports, deterrence actions, settings changes, viewing incidents with plates. Admin page to view
  and export it.
- **Blur in UI** (setting, DEFAULT on for non-admin roles): faces blurred in Search results and
  exported material.
- **Site privacy pack:** generate signage text and a Privacy Impact Assessment template (markdown)
  from the enabled features (Settings → Privacy).
- **Audio:** classification only, audio is never recorded or stored (Crimes Act interception risk).
  Disabled by default.

---

## 9. Platform changes

### 9.1 Multi-site

- New table `sites` (name, type mall/hospital/other, timezone DEFAULT `Pacific/Auckland`,
  trading_hours JSON, max_stay_hours). `cameras.site_id` (plain INT). Default site created on
  upgrade; all existing cameras assigned to it. Site selector in the top bar; all lists filter by
  site. DEFAULT: single server per site, multi-site in one UI only if cameras share a server.

### 9.2 Camera roles and sources

- `cameras.role`: general / anpr_entry / anpr_exit / thermal / ptz (DEFAULT general).
- New `source_type = "file"` (video file path, loops) for testing and demos – **required for the
  replay test harness** (Section 13).
- Sub-stream support: optional `detect_stream_path` (low-res for detection) vs `stream_path`
  (high-res for snapshots/clips/ANPR crops).

### 9.3 Event model changes (`events`)

Add: `event_type` (machine type string, e.g. `car_prowling`; `policy_type` stays the human label),
`site_id`, `has_clip`, `severity_reason`, `session_id?`, `plate?`, `acknowledged_by?`,
`acknowledged_at?`, `legal_hold`, all `vlm_*` columns (Section 6.5). Keep `status` values but
DECIDED relabel in UI: `to_review` → "Open", `coached` → "Resolved" (factory wording); store
unchanged for compatibility. The "Coaching Workbench" page is renamed **"Incidents"**.

### 9.4 Audio (optional)

- If a camera has audio (RTSP AAC/G.711), an `AudioRunner` decodes it and runs a small sound
  classifier (DEFAULT YAMNet via TensorFlow Lite or PANNs CNN14 via ONNX) for scream, shout,
  glass break, car alarm, siren. Output feeds F1/F4 as evidence and can raise `audio_alert`
  (risk 6, gate). Never store audio.

### 9.5 Recording

- Tiam is **not** an NVR. DEFAULT: event clips only (F5.3). Optional integration later with the
  site's NVR/VMS (Milestone/Genetec/Hikvision) via a `RecorderLink` that opens playback at a
  timestamp. Out of scope for phases 1–4.

### 9.6 Performance budget

- Target: dev laptop RTX 3050 → 4–6 cameras with pose + embeddings; site server with RTX 4070 Ti
  / RTX 4000 Ada class → 16–24 cameras; VLM on a separate GPU or cloud.
- Add a **System** page (`/admin/system`): per-camera processed fps, detector ms, queue lengths,
  GPU memory/utilisation (`nvidia-smi` / `pynvml`), VLM queue, disk usage of `data/retail_*`.

---

## 10. API summary (new)

| Router | Prefix | Endpoints |
|---|---|---|
| `vlm.py` | `/api/vlm` | `GET/PUT /settings`, `DELETE /settings/api-key`, `POST /test`, `GET/PUT /event-types`, `GET /usage` (admin) |
| `anpr.py` | `/api/anpr` | `POST /ingest/{camera_id}` (device token), `GET /reads`, `GET /sessions`, `GET /sessions/{id}` |
| `plate_lists.py` | `/api/plate-lists` | CRUD lists + entries, CSV import/export |
| `car_guard.py` | `/api/car-guard` | register / list / delete, `GET /confirm/{token}?answer=yes|no` (no login, signed token) |
| `escort.py` | `/api/escort` | `POST /start`, `POST /{id}/end`, `POST /{id}/attach-track`, `GET /active`; WS `/ws/escort/{id}` |
| `devices.py` | `/api/devices` | CRUD, `POST /{id}/test`, `POST /{id}/action` (play/tts/strobe/siren/ptz) |
| `deterrence.py` | `/api/deterrence-policies` | CRUD |
| `notifications.py` | `/api/notification-rules` | CRUD, `POST /test` |
| `search.py` | `/api/search` | `POST /attributes`, `POST /text`, `POST /similar`, `GET /journey` |
| `camera_events.py` | `/api/camera-events` | `POST /ingest/{camera_id}` (thermal, help point, relay inputs) |
| `sites.py` | `/api/sites` | CRUD, `camera-links` CRUD |
| `privacy.py` | `/api/privacy` | retention settings, audit log query/export, privacy pack generation |
| `events.py` (extend) | `/api/events` | `POST /{id}/acknowledge`, `POST /{id}/legal-hold`, `POST /{id}/evidence-pack`, `GET /{id}/clip` |
| `system.py` | `/api/system` | health/perf metrics |

All new routers require login; admin-only where they change settings. Device/ingest endpoints use
per-device tokens (stored hashed). Add the new `PAGE_KEYS` and Role defaults: **Operator** (live,
incidents, vehicles, search, escort console, deterrence), **Staff** (escort page only),
**Admin**.

---

## 11. Hardware

| Item | Spec | For |
|---|---|---|
| Existing CCTV cameras | 1080p+, H.264/H.265 RTSP, sub-stream; person ≥ 60 px tall in bay areas | F1–F4, F7–F13 |
| **ANPR cameras** at each entry/exit/ramp | IR 850 nm, shutter ≤ 1/1000 s, plate ≥ 130 px wide (single row), ≤ 30° off-axis, WDR off; on-camera ANPR preferred (Axis License Plate Verifier, Hikvision ANPR, Hanwha) | F5, F6, F9 |
| **Server GPU** per site | Dev: RTX 3050 (current). Production: RTX 4070 Ti/4080 or RTX 4000/6000 Ada (16–48 GB); 32–64 GB RAM; NVMe 2 TB for 30-day clips | All |
| Optional local VLM GPU | ≥ 16 GB VRAM for an 8B VLM (24 GB+ recommended), or NVIDIA Jetson Thor / DGX Spark class | F0 local |
| Edge option | NVIDIA Jetson Orin NX 16 GB (≈ 8–16 cams detection) for remote car parks / trailers | Remote sites |
| **IP horn speakers + strobes** | Network (PoE), HTTP API or SIP, ≥ 110 dB, IP66 | F14 |
| **Thermal cameras** (radiometric) | Low-mounted near EV chargers and ramps, temperature alarm events | F10 |
| PTZ (optional) | ONVIF presets, auto-tracking | F1, F11 |
| Help points | Video intercom with relay/HTTP event | F11 |
| Audio (optional) | Camera mic or audio sensor | F4 |
| Solar + 4G trailer (optional) | 2–4 AI cameras, PTZ, speaker, light, Jetson | Hoon hotspots, overflow parking |
| Network / power | PoE switches, UPS for server + switches, VLAN for cameras | All |

Note for public hospital clients: check procurement rules on camera brands (some buyers exclude
certain manufacturers).

---

## 12. Models and datasets

| Model | Source | Task |
|---|---|---|
| Main detector | `yolov8s.pt` (now) → YOLO26s/m after site validation | person, car, truck, bus, motorcycle (+ bicycle) |
| Pose | `yolo26s-pose.pt` / `yolov8s-pose.pt` | F3, F4, F1, F7 height |
| Plate detector | Fine-tune YOLO on NZ plates (public plate datasets + own ANPR crops) | F5-B |
| OCR | `fast-plate-ocr` (or PaddleOCR) | F5-B |
| Fire/smoke | Fine-tune YOLO on public fire/smoke datasets + car park negatives (headlights, brake lights, exhaust in cold weather, orange cars) | F10 |
| Trolley | Fine-tune main detector with a `trolley` class | F12 |
| Embeddings | OpenCLIP / SigLIP (pretrained) | F7, F11, F13 |
| Face detector (blur only) | YuNet or SCRFD | F16, F17 |
| Audio classifier | YAMNet / PANNs | F4 |

- Add `scripts/build_dataset_from_clips.py`: extract frames from recorded site clips, auto-label
  with the current model or YOLOE-26 (open-vocabulary text prompts), output YOLO format + preview
  images for manual review (same flow as the earlier forklift dataset script).
- Keep a **hard-negatives** folder per site (shadows, reflections, cleaners, attendants, people
  loading boots) and include it in every retrain.
- Model files live in `backend/models/`; release build must include whichever are enabled
  (update `build-release.ps1`; remember `update-release.ps1` now copies `models/`).

---

## 13. Testing

There is no test suite today. Add one, minimal but real:

- **`backend/tests/` with pytest** (add to requirements): unit tests for each detector using
  synthetic `FrameContext` sequences (like the existing scratch tests), VLM providers with a fake
  HTTP server, secret store, plate normalisation/fuzzy match, session joining, retention job.
- **Replay harness** `scripts/replay.py`: runs a video file (`source_type=file`) through the full
  pipeline at real time or faster, with a YAML **ground-truth** file (`clips/<name>.yaml`: event type,
  start/end seconds). Prints precision/recall per event type. Store test clips outside git
  (`data/test_clips/`), list them in `docs/test_clips.md`.
- Keep `scripts/verify_logic.py` passing and extend it.
- Frontend: keep `tsc -b` clean; check each new page in Chrome with no console errors (as done in
  CHANGELOG entries).
- Each phase's acceptance checks (Section 14) must be run and recorded in CHANGELOG.

---

## 14. Phased delivery plan

| Phase | Scope | Exit criteria |
|---|---|---|
| **1 – Foundations** | Detector module contract, FrameRing + clips, `event_type` column, IncidentPipeline + AlertDispatcher, `source_type=file`, replay harness + pytest, sites (single default), System page, SecretStore, detector model selector | Existing rules still work through the new pipeline; replay harness runs; clips saved |
| **2 – AI verification** | F0 complete (providers, settings page, API key, modes, usage), VLM chips in UI | Section 6.7 acceptance |
| **3 – Core threats** | PoseRunner, F1 Car prowling, F2 Loitering, F3 Person down, F8 Vehicle rules, F15 Notifications + acknowledge | Replay precision/recall targets met on test clips |
| **4 – Escort** | F11 Virtual escort + camera links / site map (hospital priority; staff self-login deferred) | F11 flow works across 2+ cameras on replay |
| **5 – Vehicles** | F5 ANPR (built-in B, optional per camera; A deferred), sessions, watchlist/allowlist, Vehicles page, F6 Plate mismatch | Section F5/F6 acceptance |
| **6 – Response** | F14 Deterrence (speakers/strobes/TTS/policies), F16 Evidence pack, F17 Privacy & audit & retention | Real speaker test; export verified; retention job tested |
| **7 – Search** | EmbeddingRunner, FAISS index, F13 Search page + journey | Text search finds staged targets in top 10 |
| **8 – Advanced** | F7 Occupant mismatch + Car Guard, F9 Hooning & car meets, F4 Fight (+ audio), F10 Fire/thermal, F12 Trolley | Each feature's acceptance section |

Phase order changed in grilling round 2 (2026-11-08): hospital first, so Virtual escort moved up.
Round 2 also decided: VLM cloud/local is an admin setting (cloud for now); start ANPR from
pretrained open models and fine-tune on site crops later; SMS = generic HTTP template + Twilio
adapter, email via existing Azure service; test with public footage until site footage exists,
but phase acceptance only on real site footage.

---

## 15. Non-goals (do not build)

- Face recognition or any identification of people by biometrics.
- Emotion, intent, health, age, gender or ethnicity inference.
- Child/pet-left-in-vehicle detection (unreliable through glass, high liability).
- Gunshot detection (low value in NZ).
- Full NVR/recording replacement.
- Parking payment/enforcement billing (only overstay/restricted alerts).

---

## 16. Decisions to confirm (start the grilling here)

**Grilling round 1 answers (2026-11-08)** – recorded in `CONTEXT.md` and `docs/adr/0001-0006`:
first site is a **hospital** car park; **the whole system (all 7 phases)** is in scope;
development VLM = **Anthropic (Claude)**; **no ANPR cameras – built-in plate reading on ordinary
cameras, optional per camera** (ADR 0002); items 4, 5, 6 (pending first site's hardware), 7, 8, 9,
10, 11, 13, 14 accepted as defaulted below; item 15: **fix both security issues on
`retail-parking` in phase 1** (ADR 0006).

**Round 3 (2026-11-08):** escort is started from the **operator console** for now; staff
self-login (item 12) is deferred. Ultralytics (AGPL) is kept during development; licence vs.
replacement is decided before the first sale, and phase 1 makes the detector engine pluggable
(ADR 0007). Plate models: `fast-plate-ocr` + `open-image-models` detector, pending its weights
licence (ADR 0002). Security fixes (ADR 0006) done. This spec lives in `docs/spec/`.

**Round 4 (2026-11-08):** clips are stored raw with a JSON box overlay (ADR 0008, overrides 5.3's
"annotated boxes drawn"); `TIAM_SECRET_KEY` comes only from the environment – `install.ps1`
generates it into `config.ps1`, and CLAUDE.md gets a one-line dev command to create it (no file
fallback); hospital default **after-hours window 20:00–06:00** (site setting, zones can override);
operating model = **24/7 security control room**: alerts go to the operator console first, and an
incident with risk ≥ 8 not acknowledged within **2 minutes** escalates by SMS to the security
supervisor (F15 defaults).

Each has a default already applied in this spec. Confirm or change:

1. **VLM default provider for development** – cloud (OpenAI-compatible / Anthropic / Gemini) since
   the RTX 3050 can't host a VLM? DEFAULT: yes, any of the three; production may be local.
2. **Gate vs annotate per event type** – defaults in 6.1 OK?
3. **ANPR approach** – buy ANPR cameras with on-camera reading (A) vs. build our own (B) first?
   DEFAULT: support both, A first.
4. **External plate lookup (NZTA/MotorWeb)** for F6 – needed now? DEFAULT: off, DB history only.
5. **Car Guard opt-in** for F7 – staff/customer registration with SMS confirmation? DEFAULT: yes.
6. **SMS provider** – which gateway? DEFAULT: generic HTTP template.
7. **Speaker brand/protocol** on the first site? DEFAULT: Axis HTTP audio + generic HTTP.
8. **Search store** – FAISS files vs SQL Server 2025 vector type (if the production SQL Server
   supports it). DEFAULT: FAISS.
9. **Retention periods** in F17 – OK for the first clients?
10. **Multi-site** – one server per site vs. central server for several sites? DEFAULT: one per site.
11. **Rename statuses** "to_review/coached" → "Open/Resolved" in the UI only? DEFAULT: yes, UI only.
12. **Staff escort login** – app accounts per staff member vs. a shared kiosk link with name entry?
    DEFAULT: individual accounts with a "Staff" role.
13. **YOLO26** – when to switch the default detector? DEFAULT: after a replay comparison on site clips
    shows equal or better recall at equal fps.
14. **Hospital legal check** – does the hospital fall under the Health Information Privacy Code for
    car-park footage? DEFAULT: treat as general Privacy Act + Biometric Code; get legal advice
    before go-live.
15. **Security issues in CLAUDE.md** (hard-coded Azure key fallback, default admin password) – fix
    now as part of phase 1? DEFAULT: ask the user; do not change silently.
