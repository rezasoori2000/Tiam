"""What happens to a confirmed incident (spec 5): persist -> snapshot -> clip -> route the alert.

`IncidentPipeline.handle_frame` is called by the camera worker with the events that survived
`_IncidentTracker` dedupe. Routing is the hook for phase 2's VLM verification: today every
incident goes straight to the `AlertDispatcher`.
"""
import logging
from typing import Callable, List, Optional

import cv2
import numpy as np

from . import clips, crud

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Single place alerts leave the pipeline. Phase 1: the /ws/alerts broadcast (via the worker's
    thread-safe push). Later: notifications, escalation, deterrence (spec F14/F15)."""

    def __init__(self, push: Callable[[dict], None]):
        self._push = push

    def dispatch(self, payload: dict) -> None:
        self._push(payload)


class IncidentPipeline:
    def __init__(
        self, camera_id: int, dispatcher: AlertDispatcher, recorder: Optional[clips.ClipRecorder],
        snapshot_path: Callable[..., "object"], jpeg_quality: int,
    ):
        self.camera_id = camera_id
        self.dispatcher = dispatcher
        self.recorder = recorder
        self._snapshot_path = snapshot_path
        self._jpeg_quality = jpeg_quality

    def handle_frame(
        self, db, events: List[dict], annotated: np.ndarray, stream_jpeg: Optional[bytes],
        draw_zones: Callable[[np.ndarray], None], ring: Optional[clips.FrameRing], ts: float,
    ) -> list:
        """Persists each new incident of this frame and routes its alert. Returns the Event rows."""
        rows = []
        snapshot_jpeg: Optional[bytes] = None
        for ev in events:
            ev["camera_id"] = self.camera_id
            row = crud.create_event(db, ev)
            rows.append(row)
            if snapshot_jpeg is None:
                # The annotated frame plus zone outlines (the live stream leaves them out) is the
                # incident snapshot. Encoded once per frame, however many incidents it raised.
                with_zones = annotated.copy()
                draw_zones(with_zones)
                ok, encoded = cv2.imencode(".jpg", with_zones, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
                snapshot_jpeg = encoded.tobytes() if ok else b""
            if snapshot_jpeg:
                self._snapshot_path(row.id).write_bytes(snapshot_jpeg)
                if stream_jpeg:  # same image minus the zones
                    self._snapshot_path(row.id, zones=False).write_bytes(stream_jpeg)
                crud.mark_event_has_snapshot(db, row)
            if self.recorder is not None and ring is not None:
                self.recorder.start(row.id, ring, ts)
            self._route(row)
        return rows

    def _route(self, row) -> None:
        # Phase 2: if AI verification is enabled for row.event_type, queue it here instead
        # (annotate: dispatch now and update later; gate: dispatch after the verdict).
        self.dispatcher.dispatch(crud.to_alert_payload(row))
