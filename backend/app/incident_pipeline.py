"""What happens to a confirmed incident (spec 5): persist -> snapshot -> clip -> route the alert.

`IncidentPipeline.handle_frame` is called by the camera worker with the events that survived
`_IncidentTracker` dedupe. `_route` decides, per event type, whether the alert goes straight to the
dashboard (AI verification off) or through the AI verifier first (annotate / gate, app/vlm).
"""
import logging
import threading
from typing import Callable, List, Optional

import cv2
import numpy as np

from . import clips, crud
from .vlm import keyframes
from .vlm.service import VerificationOutcome, VerificationService, service as default_verifier

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Single place alerts leave the pipeline. Phase 1: the /ws/alerts broadcast (via the worker's
    thread-safe push). Later: notifications, escalation, deterrence (spec F14/F15)."""

    def __init__(self, push: Callable[[dict], None]):
        self._push = push

    def dispatch(self, payload: dict) -> None:
        self._push(payload)


def _with_vlm(payload: dict, status: str, outcome: Optional[VerificationOutcome] = None) -> dict:
    out = dict(payload, vlm_status=status)
    if outcome is not None and outcome.result is not None:
        out.update(vlm_verdict=outcome.result.verdict, vlm_confidence=outcome.result.confidence,
                   vlm_reason=outcome.result.reason)
    return out


class PendingVerification:
    """One incident going through AI verification. Collects frames until POST_S after the incident,
    then submits; makes sure the alert is dispatched at most once (gate timer vs verdict race)."""

    def __init__(self, event_id: int, ev: dict, ts: float, mode: str, payload: dict, frames: list,
                 dispatcher: AlertDispatcher, verifier: VerificationService, camera_id: int):
        self.event_id, self.ev, self.ts, self.mode = event_id, ev, ts, mode
        self.payload, self.frames = payload, frames
        self._dispatcher, self._verifier, self._camera_id = dispatcher, verifier, camera_id
        self._lock = threading.Lock()
        self._alerted = False  # the alert (or its suppression) has been decided
        self._timer: Optional[threading.Timer] = None
        if mode == "annotate":
            self._alert(_with_vlm(payload, "pending"))
        else:  # gate: hold the alert, but never longer than gate_timeout_s
            self._timer = threading.Timer(verifier.snapshot.gate_timeout_s, self._gate_timeout)
            self._timer.daemon = True
            self._timer.start()

    def add_frame(self, item) -> bool:
        """Returns True once enough post-incident frames are in (then submit())."""
        if item is not None and (not self.frames or item[0] > self.frames[-1][0]):
            self.frames.append(item)
        return item is not None and item[0] >= self.ts + keyframes.POST_S

    def submit(self) -> None:
        self._verifier.submit(self.event_id, self._camera_id, self.ev, self.ts, self.frames, self._on_done)

    def _alert(self, payload: dict) -> None:
        self._alerted = True
        self._dispatcher.dispatch(payload)

    def _gate_timeout(self) -> None:
        with self._lock:
            if not self._alerted:
                self._alert(_with_vlm(self.payload, "unverified"))  # never lose a real alert

    def _on_done(self, outcome: VerificationOutcome) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            status = outcome.status if outcome.status == "done" else "unverified"
            if not self._alerted:
                self._alerted = True
                if outcome.verdict == "rejected":
                    return  # gate: AI says false alarm -> stored, not alerted (auto-deleted later)
                self._dispatcher.dispatch(_with_vlm(self.payload, status, outcome))
            else:  # alert already out (annotate, or gate timed out): send the verdict as an update
                update = _with_vlm({"kind": "verification", "event_id": self.event_id}, status, outcome)
                self._dispatcher.dispatch(update)


class IncidentPipeline:
    def __init__(
        self, camera_id: int, dispatcher: AlertDispatcher, recorder: Optional[clips.ClipRecorder],
        snapshot_path: Callable[..., "object"], jpeg_quality: int,
        verifier: Optional[VerificationService] = None,
    ):
        self.camera_id = camera_id
        self.dispatcher = dispatcher
        self.recorder = recorder
        self._snapshot_path = snapshot_path
        self._jpeg_quality = jpeg_quality
        self.verifier = verifier or default_verifier
        self._collecting: List[PendingVerification] = []

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
            self._route(db, row, ev, ring, ts)
        return rows

    def _route(self, db, row, ev: dict, ring: Optional[clips.FrameRing], ts: float) -> None:
        mode = self.verifier.mode_for(row.event_type)
        if mode == "off" or ring is None:
            self.dispatcher.dispatch(crud.to_alert_payload(row))  # straight to the dashboard
            return
        row.vlm_status = "pending"
        db.commit()
        payload = crud.to_alert_payload(row)
        self._collecting.append(PendingVerification(
            row.id, ev, ts, mode, payload, ring.items(), self.dispatcher, self.verifier, self.camera_id,
        ))

    def on_frame(self, item) -> None:
        """Camera thread, every frame: hand finished frame collections to the verifier."""
        if not self._collecting:
            return
        still = []
        for p in self._collecting:
            if p.add_frame(item):
                p.submit()
            else:
                still.append(p)
        self._collecting = still

    def flush(self) -> None:
        """Worker stopping: verify with the frames collected so far."""
        for p in self._collecting:
            p.submit()
        self._collecting = []
