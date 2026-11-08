"""Car prowling (spec F1): a person going car to car, lingering or crouching beside parked vehicles.

Zone rule `prowling` (+ `prowling_min_vehicles`): only people whose ground point is inside such a
zone are judged. Per person, within the last WINDOW_S:
- a **visit** = standing within VISIT_RADIUS_M of a parked vehicle's footprint for >= MIN_VISIT_S;
  a vehicle is **parked** once it stayed within PARK_DRIFT_M of one spot for PARK_MIN_S;
- score = distinct vehicles visited + 0.5 per visit >= LONG_VISIT_S + 1 per visit spent crouching
  (box height < CROUCH_RATIO of the person's recent standing height for >= CROUCH_MIN_S).
While the score is >= the zone's `prowling_min_vehicles`, a `car_prowling` event is emitted every
frame; `_IncidentTracker` turns that into one incident. Walking to your own car or loading the boot
scores ~1-1.5, so it doesn't fire at the default threshold of 3.

Distances use the camera's calibration (uncalibrated cameras use the 0.02 m/px placeholder, so
radii are only rough). Vehicles re-acquired under a new track id are merged by position.
shortcut: crouch = box-height drop, not pose keypoints; switch to the PoseRunner (spec 5.2) in phase 3.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from . import CandidateEvent, FrameContext, TrackView

PARK_DRIFT_M = 1.0
PARK_MIN_S = 30.0
VISIT_RADIUS_M = 1.2
MIN_VISIT_S = 3.0
LONG_VISIT_S = 10.0
WINDOW_S = 300.0
CROUCH_RATIO = 0.6
CROUCH_MIN_S = 2.0
HEIGHT_WINDOW_S = 10.0
SAME_VEHICLE_M = 2.0  # two vehicle ids parked this close are the same car (tracker re-id)
FOOTPRINT_BAND = 0.4  # bottom fraction of a vehicle box that approximates its footprint on the ground
# A prowler crouching between cars is often hidden for a moment and comes back under a NEW track id.
# A new person track that appears near where a person was lost inherits their visits, if it's within
# REID_BASE_M + REID_SPEED_MPS * gap (walking pace) and the gap is <= REID_MAX_GAP_S.
REID_BASE_M = 2.0
REID_SPEED_MPS = 2.0
REID_MAX_GAP_S = 30.0

Point = Tuple[float, float]


@dataclass
class _Parked:
    anchor: Point
    since: float


@dataclass
class _Visit:
    vehicle_id: int
    vehicle_point: Point
    start: float
    last: float
    crouch_s: float = 0.0

    @property
    def seconds(self) -> float:
        return self.last - self.start


@dataclass
class _Person:
    heights: Deque[Tuple[float, float]] = field(default_factory=deque)  # (ts, box height px)
    current: Optional[_Visit] = None
    visits: List[_Visit] = field(default_factory=list)  # finished visits >= MIN_VISIT_S
    last_ts: Optional[float] = None
    last_point: Optional[Point] = None


def _footprint_point(box, p: Point) -> Point:
    """Closest point to `p` on the bottom band of a vehicle box (its approximate ground footprint)."""
    x1, y1, x2, y2 = (float(v) for v in box)
    top = y2 - (y2 - y1) * FOOTPRINT_BAND
    return min(max(p[0], x1), x2), min(max(p[1], top), y2)


class CarProwlingDetector:
    name = "car_prowling"
    event_types = ["car_prowling"]

    def __init__(self) -> None:
        self._vehicles: Dict[int, _Parked] = {}
        self._people: Dict[int, _Person] = {}

    # ------------------------------------------------------------------ contract

    def update(self, ctx: FrameContext) -> List[CandidateEvent]:
        if not any(z.rules.prowling for z in ctx.zones):
            return []  # zones only change on worker restart, so no state is needed on such cameras
        parked = self._update_vehicles(ctx)  # keep parked timers running even outside active hours
        zones = [z for z in ctx.zones if z.rules.prowling and z.rules.is_active_at(ctx.ts)]
        if not zones:
            return []
        events: List[CandidateEvent] = []
        for t in ctx.tracks:
            if t.kind != "person":
                continue
            person = self._people.get(t.track_id)
            if person is None:
                person = self._people[t.track_id] = self._reidentify(t, ctx)
            self._update_person(person, t, parked, ctx)
            for zone in zones:
                if zone.id not in t.zone_hits or "person" not in zone.rules.applies_to:
                    continue
                score, details = self._score(person, ctx.calibration)
                if score >= zone.rules.prowling_min_vehicles:
                    events.append({
                        "type": "car_prowling", "zone_id": zone.id, "zone_name": zone.name,
                        "track_id": t.track_id, "timestamp": ctx.ts, "point": t.point,
                        "score": round(score, 1), "threshold": zone.rules.prowling_min_vehicles,
                        **details, "key_track_ids": [t.track_id],
                    })
        return events

    def prune(self, live_track_ids: set) -> None:
        self._vehicles = {k: v for k, v in self._vehicles.items() if k in live_track_ids}
        self._people = {k: v for k, v in self._people.items() if k in live_track_ids}

    # ------------------------------------------------------------------ internals

    def _update_vehicles(self, ctx: FrameContext) -> List[TrackView]:
        """Updates each vehicle's parked timer; returns the vehicles parked right now."""
        parked = []
        for t in ctx.tracks:
            if t.kind != "vehicle":
                continue
            state = self._vehicles.get(t.track_id)
            if state is None or ctx.calibration.distance_m(state.anchor, t.point) > PARK_DRIFT_M:
                self._vehicles[t.track_id] = state = _Parked(anchor=t.point, since=ctx.ts)
            if ctx.ts - state.since >= PARK_MIN_S:
                parked.append(t)
        return parked

    def _reidentify(self, t: TrackView, ctx: FrameContext) -> _Person:
        """State for a new person track: the closest recently-lost person within walking reach, or fresh."""
        live = {x.track_id for x in ctx.tracks}
        best_id, best_d = None, None
        for pid, p in self._people.items():
            if pid in live or p.last_ts is None or p.last_point is None:
                continue
            gap = ctx.ts - p.last_ts
            if gap > REID_MAX_GAP_S:
                continue
            d = ctx.calibration.distance_m(p.last_point, t.point)
            if d <= REID_BASE_M + REID_SPEED_MPS * gap and (best_d is None or d < best_d):
                best_id, best_d = pid, d
        if best_id is None:
            return _Person()
        person = self._people.pop(best_id)
        self._close_visit(person)
        person.heights.clear()  # box size may differ after re-acquisition
        return person

    def _update_person(self, person: _Person, t: TrackView, parked: List[TrackView], ctx: FrameContext) -> None:
        dt = 0.0 if person.last_ts is None else max(0.0, ctx.ts - person.last_ts)
        person.last_ts = ctx.ts
        person.last_point = t.point
        height = float(t.xyxy[3] - t.xyxy[1])
        person.heights.append((ctx.ts, height))
        while person.heights and ctx.ts - person.heights[0][0] > HEIGHT_WINDOW_S:
            person.heights.popleft()
        crouching = height < CROUCH_RATIO * max(h for _, h in person.heights)

        nearest, nearest_d = None, VISIT_RADIUS_M
        for v in parked:
            d = ctx.calibration.distance_m(t.point, _footprint_point(v.xyxy, t.point))
            if d <= nearest_d:
                nearest, nearest_d = v, d

        cur = person.current
        same = (
            cur is not None and nearest is not None
            and (cur.vehicle_id == nearest.track_id
                 or ctx.calibration.distance_m(cur.vehicle_point, nearest.point) <= SAME_VEHICLE_M)
        )
        if same:
            cur.last = ctx.ts
            if crouching:
                cur.crouch_s += dt
        else:
            self._close_visit(person)
            if nearest is not None:
                person.current = _Visit(nearest.track_id, nearest.point, ctx.ts, ctx.ts)
        person.visits = [v for v in person.visits if ctx.ts - v.last <= WINDOW_S]

    @staticmethod
    def _close_visit(person: _Person) -> None:
        if person.current is not None and person.current.seconds >= MIN_VISIT_S:
            person.visits.append(person.current)
        person.current = None

    @staticmethod
    def _score(person: _Person, calibration) -> Tuple[float, dict]:
        visits = list(person.visits)
        if person.current is not None and person.current.seconds >= MIN_VISIT_S:
            visits.append(person.current)
        distinct: List[Point] = []
        for v in visits:  # vehicles re-acquired under a new id are merged by position
            if all(calibration.distance_m(v.vehicle_point, p) > SAME_VEHICLE_M for p in distinct):
                distinct.append(v.vehicle_point)
        long_visits = sum(1 for v in visits if v.seconds >= LONG_VISIT_S)
        crouch_visits = sum(1 for v in visits if v.crouch_s >= CROUCH_MIN_S)
        score = len(distinct) + 0.5 * long_visits + 1.0 * crouch_visits
        return score, {
            "vehicles_visited": len(distinct),
            "long_visits": long_visits,
            "crouch_visits": crouch_visits,
            "visits": [
                {"vehicle_track_id": v.vehicle_id, "seconds": round(v.seconds, 1), "crouch_seconds": round(v.crouch_s, 1)}
                for v in visits
            ],
        }
