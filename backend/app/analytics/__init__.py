"""Detector module contract (spec 5.1).

A detector reads the current frame's tracks (plus its own per-track memory) and emits candidate
events. Each one lives in `app/analytics/<name>.py`. Rules:
- no network calls and no heavy models inside `update` (aim < 2 ms per frame); heavy models are
  shared runners that fill `TrackView` fields;
- keep per-track state small and drop it in `prune`.

A candidate event is a plain dict in the existing event shape (`type`, `zone_id?`, `zone_name`,
`track_id?`, `timestamp`, `point`, type-specific fields) plus optional `key_track_ids`
(tracks drawn as threats), `bbox_hint` and `severity_hint`. It then goes through the same
`_IncidentTracker` dedupe and `risk.score_event` as the built-in zone rules.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

import numpy as np

from ..config import CalibrationConfig, Zone

CandidateEvent = Dict[str, Any]


@dataclass
class TrackView:
    """Read-only view of one track for detectors (built from VisionEngine's _TrackInfo)."""
    track_id: int
    class_name: str
    kind: str  # "person" | "vehicle"
    xyxy: np.ndarray
    point: Tuple[float, float]  # ground point, image px (CalibrationConfig maps it to metres)
    speed_kmh: Optional[float]
    zone_hits: List[str]
    confidence: Optional[float] = None
    keypoints: Optional[np.ndarray] = None  # filled by the pose runner (phase 3)
    attributes: Dict[str, Any] = field(default_factory=dict)  # filled by the attribute runner


@dataclass
class FrameContext:
    camera_id: Optional[int]
    ts: float
    frame: np.ndarray  # clean frame, FRAME_SIZE
    tracks: List[TrackView]
    calibration: CalibrationConfig
    zones: List[Zone]


class Detector(Protocol):
    name: str
    event_types: List[str]

    def update(self, ctx: FrameContext) -> List[CandidateEvent]: ...

    def prune(self, live_track_ids: set) -> None: ...


def default_detectors() -> List["Detector"]:
    """Fresh detector instances for one camera (each keeps its own per-track state). Detectors
    check their own zone rules, so with no matching zones they cost almost nothing."""
    from .car_prowling import CarProwlingDetector

    return [CarProwlingDetector()]
