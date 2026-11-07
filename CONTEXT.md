# Tiam – Domain Context

Shared vocabulary for the car-park security system (branch `retail-parking`). Decisions that shaped
these terms are in `docs/adr/`. The full feature spec is `docs/spec/Tiam-CarPark-Spec.md`.

## Product

- **Tiam** – self-hosted video analytics for car parks. **First client: a hospital car park**
  (New Zealand). Shopping-mall car parks are the second target.
- **Site** – one car park property. One Tiam server per site (ADR 0004).

## Terms

| Term | Meaning |
|---|---|
| **Camera** | A video source. Gains a `role`: general / anpr_entry / anpr_exit / thermal / ptz. |
| **Zone** | Polygon drawn on one camera with rules (exclusion, speed limit, stop required, time window, plus the new kinds in the spec, Section 7). |
| **Track** | One object followed by ByteTrack on one camera (`track_id`). |
| **Detector** | A module in `backend/app/analytics/` that reads tracks and emits candidate events. |
| **Candidate event** | Raw detector output, before dedupe and verification. |
| **Incident** | A deduped candidate event stored as an `Event` row. The UI calls these "Incidents" (the old "Coaching Workbench" page is renamed "Incidents"). |
| **Incident status** | Stored as `to_review` / `coached`; shown in the UI as **Open** / **Resolved**. |
| **Verification** | Optional AI (VLM) check of an incident. Verdict: `confirmed`, `rejected`, `uncertain`, `skipped`, `error` (ADR 0001). |
| **Gate mode / Annotate mode** | Gate: alert is held until the verdict (rejected → no alert). Annotate: alert at once, verdict added later. |
| **Plate read** | A licence plate read from video by Tiam's own ANPR pipeline (ADR 0002). Optional per camera. |
| **Vehicle session** | One visit of one vehicle: entry → parked → exit. Keyed by plate when read, otherwise by vehicle signature. |
| **Vehicle signature** | Plate (if read) + colour/type + visual embedding. |
| **Occupant signature** | Short-lived appearance embedding of a person who got out of a parked vehicle. Deleted when the session ends or after 24 h. |
| **Car Guard** | Opt-in: a registered plate owner is asked "Is this you?" when someone who doesn't match the occupants drives the car away. |
| **Watchlist / Allowlist** | Plate lists: alert on sight / allowed in restricted bays. |
| **Escort** | Virtual-escort session for a staff member walking to their car. |
| **Deterrence action** | Speaker message, strobe, siren or PTZ preset triggered on site. |
| **Evidence pack** | Exported ZIP (clip, snapshots, plates, timeline, hashes) for one incident. |
| **After hours** | The site's night window (hospital default 20:00–06:00); many rules are stricter or only active then. Zones can override. |
| **Operator** | Person in the 24/7 security control room who watches the console and acknowledges incidents. |
| **Acknowledge / escalation** | An operator acknowledges an incident; risk ≥ 8 not acknowledged within 2 min escalates by SMS to the security supervisor. |
| **Risk score** | 1–10 severity of an incident. Red ≥ 8, amber ≥ 5, else green. |
| **Retention** | How long each kind of data is kept before the nightly job deletes it (ADR 0005). |

## Hard boundaries

- The factory system (`main` branch, DB `SecurityCamera`, `data/event_snapshots`) is in production
  and must never be touched by this work.
- No face recognition; no emotion, intent, health, age, gender or ethnicity inference.
