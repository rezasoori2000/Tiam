from app.camera_manager import _IncidentTracker


def ev(track_id, point=(100.0, 100.0)):
    return {"type": "exclusion", "zone_id": "1", "zone_name": "z", "track_id": track_id, "point": point}


def test_one_incident_per_ongoing_breach():
    t = _IncidentTracker(min_observations=3, window_frames=6)
    fired = []
    for i in range(20):
        t.start_frame()
        fired.append(t.observe(ev(5), 100.0 + i * 0.1))
    assert fired.count(True) == 1 and fired.index(True) == 2  # confirmed on the 3rd observation


def test_new_track_id_nearby_merges_into_open_incident():
    t = _IncidentTracker(min_observations=1, window_frames=1)
    t.start_frame()
    assert t.observe(ev(5), 100.0)
    t.start_frame()
    assert not t.observe(ev(6, (110.0, 100.0)), 102.0)  # same spot, re-acquired with a new id
