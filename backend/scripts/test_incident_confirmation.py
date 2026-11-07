"""Manual sanity checks for _IncidentTracker's multi-frame confirmation gate
(DetectionSettings.confirmation_min_observations/confirmation_window_frames).

No pytest in this repo -- run directly: `python scripts/test_incident_confirmation.py`.
Each check prints PASS/FAIL; a non-zero exit code means something failed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.camera_manager import _IncidentTracker

failures = []


def check(name: bool, label: str) -> None:
    status = "PASS" if name else "FAIL"
    print(f"[{status}] {label}")
    if not name:
        failures.append(label)


def make_event(track_id: int, ts: float, zone_id: int = 1, point=(100.0, 100.0)) -> dict:
    return {
        "type": "exclusion", "zone_id": zone_id, "zone_name": "Zone A",
        "track_id": track_id, "timestamp": ts, "point": point,
    }


# 1. Transient detection (seen once, then gone) is never saved.
t = _IncidentTracker(min_observations=3, window_frames=6)
persisted = False
t.start_frame()
persisted |= t.observe(make_event(1, 1000.0), now=1000.0)
check(not persisted, "transient one-frame detection is not persisted")

# 2. Stable detection (N consecutive hits) is saved exactly once, even as it
#    keeps firing afterwards.
t = _IncidentTracker(min_observations=3, window_frames=6)
confirmations = 0
base = 2000.0
for i in range(10):
    t.start_frame()
    if t.observe(make_event(5, base + i), now=base + i):
        confirmations += 1
check(confirmations == 1, f"stable detection confirmed exactly once (got {confirmations})")

# 3. A track that drops out before reaching N, then returns as a NEW track_id
#    far away, is treated as a fresh (not merged) incident and still requires
#    its own N observations -- i.e. dropping out doesn't let partial counts
#    leak into an unrelated later breach.
t = _IncidentTracker(min_observations=3, window_frames=6)
t.start_frame(); c1 = t.observe(make_event(7, 3000.0, point=(100.0, 100.0)), now=3000.0)
t.start_frame(); c2 = t.observe(make_event(7, 3001.0, point=(100.0, 100.0)), now=3001.0)
# track 7 vanishes (never reaches 3 observations) -- simulate cooldown expiry
t.prune(now=3001.0 + 61.0)
t.start_frame(); c3 = t.observe(make_event(8, 3200.0, point=(900.0, 900.0)), now=3200.0)
t.start_frame(); c4 = t.observe(make_event(8, 3201.0, point=(900.0, 900.0)), now=3201.0)
check(not any([c1, c2, c3, c4]), "dropped-out track discarded; new unrelated track still unconfirmed at 2 hits")

# 3b. ...but a track that returns under a new id NEAR where it was last seen
#     (occlusion re-acquire) is merged into the same incident and its earlier
#     observations still count.
t = _IncidentTracker(min_observations=3, window_frames=6)
t.start_frame(); t.observe(make_event(10, 4000.0, point=(100.0, 100.0)), now=4000.0)
t.start_frame(); t.observe(make_event(10, 4001.0, point=(100.0, 100.0)), now=4001.0)
t.start_frame()
confirmed_on_reacquire = t.observe(make_event(11, 4002.0, point=(105.0, 101.0)), now=4002.0)
check(confirmed_on_reacquire, "occlusion re-acquire (new track_id, nearby point) continues the same incident's count")

# 4. N=1 behaves like the old "log on first sighting" behavior.
t = _IncidentTracker(min_observations=1, window_frames=1)
t.start_frame()
check(t.observe(make_event(20, 5000.0), now=5000.0), "N=1 confirms on the very first observation")

# 5. Per-camera isolation: two independent _IncidentTracker instances (one
#    per _CameraWorker) never share state even for the same track_id/zone_id.
tracker_a = _IncidentTracker(min_observations=3, window_frames=6)
tracker_b = _IncidentTracker(min_observations=3, window_frames=6)
for i in range(2):
    tracker_a.start_frame()
    tracker_a.observe(make_event(1, 6000.0 + i), now=6000.0 + i)
tracker_b.start_frame()
confirmed_b = tracker_b.observe(make_event(1, 6000.0), now=6000.0)
check(not confirmed_b, "a second camera's tracker starts fresh (no cross-camera state leakage)")

# 6. The persisted event's timestamp is the first-observed time, not the
#    confirmation frame's time.
t = _IncidentTracker(min_observations=3, window_frames=6)
first_ts = 7000.0
ev = None
for i in range(3):
    t.start_frame()
    ev = make_event(30, first_ts + i)
    confirmed = t.observe(ev, now=first_ts + i)
check(confirmed and ev["timestamp"] == first_ts, "confirmed event's timestamp is rewritten to the first-observed time")

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All checks passed.")
