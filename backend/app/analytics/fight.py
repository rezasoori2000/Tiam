"""Fight / assault (spec F4), video only: zone rule `fight` (+ `fight_min_seconds`).

For two people inside a fight zone and within CLOSE_M of each other:
- **agitation**: hand/foot keypoints moving fast *relative to the person's own body* (so walking or
  running together doesn't count), in body-heights per second; sustained (short gaps allowed) for
  the zone's `fight_min_seconds`;
- **charge**: one rushed at the other (closing speed > CHARGE_MPS in the last second) and they are
  now close with some agitation;
- **fall**: one of them went from upright to lying (box height/width flip) while close.
Any of these emits `fight` every frame while it holds (dedupe -> one incident). Hugs, play-fighting,
children and people running for a bus can look similar: by default fights go to the AI gate.

The pose model only runs when asked (`pose_requests`): persons in a fight zone within PAIR_MAX_M of
another person. Distances and speeds are measured in body heights (box height = PERSON_HEIGHT_M), not
via the camera calibration: it works uncalibrated, in close-ups, and anywhere in a perspective view.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Set, Tuple

import numpy as np

from . import CandidateEvent, FrameContext, TrackView
from .pose import L_ANKLE, L_WRIST, R_ANKLE, R_WRIST, body_height, point

PERSON_HEIGHT_M = 1.7     # body height used to turn box heights into metres
PAIR_MAX_M = 1.5          # ask for poses when the gap between two people is this small
CLOSE_M = 0.8             # a fight needs them this close (box gap)
# Tuned on a real street fight clip (2026-11-08): punches are only a few frames long, so fast samples
# come in bursts up to ~1.2 s apart; calm gesturing next to someone stayed below ~1.0.
LIMB_SPEED_BH = 1.2       # body heights / s, relative to the body's own movement
GAP_TOLERANCE_S = 1.2     # fast samples this far apart still count as one agitated stretch
CHARGE_MPS = 3.0
CHARGE_WINDOW_S = 1.0
FALL_WINDOW_S = 2.0
UPRIGHT_RATIO, LYING_RATIO = 1.5, 0.8  # box height / width
HISTORY_S = 3.0
LIMBS = (L_WRIST, R_WRIST, L_ANKLE, R_ANKLE)


@dataclass
class _Person:
    poses: Deque[Tuple[float, np.ndarray, np.ndarray]] = field(default_factory=deque)  # (ts, kpts, box)
    shape: Deque[Tuple[float, float]] = field(default_factory=deque)  # (ts, box h/w)
    agitation: float = 0.0  # latest limb speed, body heights / s
    hot_ts: Optional[float] = None  # last sample with agitation >= LIMB_SPEED_BH
    peak: float = 0.0


@dataclass
class _Pair:
    since: Optional[float] = None   # start of the current agitated stretch
    last_agitated: Optional[float] = None
    distances: Deque[Tuple[float, float]] = field(default_factory=deque)  # (ts, metres)


class FightDetector:
    name = "fight"
    event_types = ["fight"]
    wants_pose = True

    def __init__(self) -> None:
        self._people: Dict[int, _Person] = {}
        self._pairs: Dict[Tuple[int, int], _Pair] = {}

    # ---------------------------------------------------------------- contract

    @staticmethod
    def _zones(ctx: FrameContext):
        return [z for z in ctx.zones if z.rules.fight and z.rules.is_active_at(ctx.ts)
                and "person" in z.rules.applies_to]

    @staticmethod
    def _distance_m(a: TrackView, b: TrackView) -> float:
        """Gap between the two boxes (0 when they touch) combined with the feet's depth difference, in
        metres scaled by the taller box. Not feet-to-feet: a fighting stance or a punch widens the box
        and moves its centre, so two people at arm's length measured ~2 m apart that way."""
        h = float(max(a.xyxy[3] - a.xyxy[1], b.xyxy[3] - b.xyxy[1], 1.0))  # numpy float32 isn't JSON-serialisable
        gap_x = max(0.0, max(a.xyxy[0], b.xyxy[0]) - min(a.xyxy[2], b.xyxy[2]))
        return float(np.hypot(gap_x, a.point[1] - b.point[1])) / h * PERSON_HEIGHT_M

    def pose_requests(self, ctx: FrameContext) -> Set[int]:
        zones = self._zones(ctx)
        if not zones:
            return set()
        ids = {z.id for z in zones}
        people = [t for t in ctx.tracks if t.kind == "person" and ids.intersection(t.zone_hits)]
        wanted = set()
        for i, a in enumerate(people):
            for b in people[i + 1:]:
                if self._distance_m(a, b) <= PAIR_MAX_M:
                    wanted.update((a.track_id, b.track_id))
        return wanted

    def update(self, ctx: FrameContext) -> List[CandidateEvent]:
        zones = self._zones(ctx)
        if not zones:
            return []
        people = [t for t in ctx.tracks if t.kind == "person"]
        for t in people:
            self._observe(t, ctx.ts)
        events: List[CandidateEvent] = []
        for zone in zones:
            inside = [t for t in people if zone.id in t.zone_hits]
            for i, a in enumerate(inside):
                for b in inside[i + 1:]:
                    ev = self._judge_pair(a, b, zone, ctx)
                    if ev is not None:
                        events.append(ev)
        return events

    def prune(self, live_track_ids: set) -> None:
        self._people = {k: v for k, v in self._people.items() if k in live_track_ids}
        self._pairs = {k: v for k, v in self._pairs.items() if k[0] in live_track_ids and k[1] in live_track_ids}

    # --------------------------------------------------------------- internals

    def _observe(self, t: TrackView, ts: float) -> None:
        p = self._people.setdefault(t.track_id, _Person())
        w = max(1.0, float(t.xyxy[2] - t.xyxy[0]))
        p.shape.append((ts, float(t.xyxy[3] - t.xyxy[1]) / w))
        while p.shape and ts - p.shape[0][0] > HISTORY_S:
            p.shape.popleft()
        p.agitation = 0.0
        if t.keypoints is None:
            return
        box = np.asarray(t.xyxy, dtype=float)
        if p.poses:
            pts, pkp, pbox = p.poses[-1]
            dt = ts - pts
            if 0 < dt <= 1.0:
                # limb motion minus the body's own motion (box centre), so walking/running doesn't count
                body_v = ((box[:2] + box[2:]) - (pbox[:2] + pbox[2:])) / 2 / dt
                bh = body_height(t.keypoints, box)
                speeds = []
                for idx in LIMBS:
                    a, b = point(pkp, idx), point(t.keypoints, idx)
                    if a is not None and b is not None:
                        speeds.append(float(np.linalg.norm((b - a) / dt - body_v)) / bh)
                p.agitation = max(speeds, default=0.0)
                p.peak = max(p.peak, p.agitation)
                if p.agitation >= LIMB_SPEED_BH:
                    p.hot_ts = ts
        p.poses.append((ts, t.keypoints.copy(), box))
        while p.poses and ts - p.poses[0][0] > HISTORY_S:
            p.poses.popleft()

    def _fell(self, track_id: int, ts: float) -> bool:
        shape = self._people[track_id].shape
        recent = [(t, r) for t, r in shape if ts - t <= FALL_WINDOW_S]
        if not recent or recent[-1][1] > LYING_RATIO:
            return False
        return any(r >= UPRIGHT_RATIO for _, r in recent)

    def _judge_pair(self, a: TrackView, b: TrackView, zone, ctx: FrameContext) -> Optional[CandidateEvent]:
        key = (min(a.track_id, b.track_id), max(a.track_id, b.track_id))
        pair = self._pairs.setdefault(key, _Pair())
        dist = self._distance_m(a, b)
        pair.distances.append((ctx.ts, dist))
        while pair.distances and ctx.ts - pair.distances[0][0] > CHARGE_WINDOW_S:
            pair.distances.popleft()
        if dist > CLOSE_M:
            pair.since = pair.last_agitated = None
            return None

        pa, pb = self._people[a.track_id], self._people[b.track_id]
        hot = max((t for t in (pa.hot_ts, pb.hot_ts) if t is not None), default=None)
        if hot is not None and hot != pair.last_agitated and ctx.ts - hot <= GAP_TOLERANCE_S:
            if pair.since is None or pair.last_agitated is None or hot - pair.last_agitated > GAP_TOLERANCE_S:
                pair.since = hot
            pair.last_agitated = hot
        elif pair.last_agitated is not None and ctx.ts - pair.last_agitated > GAP_TOLERANCE_S:
            pair.since = pair.last_agitated = None
        agitated_s = 0.0 if pair.since is None else pair.last_agitated - pair.since

        t0, d0 = pair.distances[0]
        closing = (d0 - dist) / (ctx.ts - t0) if ctx.ts > t0 else 0.0
        fell = next((t.track_id for t in (a, b) if self._fell(t.track_id, ctx.ts)), None)

        subtype = None
        if agitated_s >= zone.rules.fight_min_seconds:
            subtype = "strikes"
        elif closing >= CHARGE_MPS and pair.last_agitated is not None:
            subtype = "charge"
        elif fell is not None and pair.last_agitated is not None:
            subtype = "fall"
        if subtype is None:
            return None
        return {
            "type": "fight", "subtype": subtype, "zone_id": zone.id, "zone_name": zone.name,
            "track_id": key[0], "person_ids": list(key), "key_track_ids": list(key),
            "timestamp": ctx.ts, "point": ((a.point[0] + b.point[0]) / 2, (a.point[1] + b.point[1]) / 2),
            "distance_m": round(dist, 2), "agitated_seconds": round(agitated_s, 1),
            "peak_limb_speed": round(max(pa.peak, pb.peak), 2), "closing_speed_mps": round(max(closing, 0.0), 1),
            "fallen_track_id": fell, "min_seconds": zone.rules.fight_min_seconds,
        }
