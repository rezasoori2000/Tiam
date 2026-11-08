"""AI verification service (spec F0, ADR 0001): settings snapshot, provider, worker pool, hourly cap,
usage counters and the DB update of each verified incident. Nothing here runs on a camera thread.

Per event type the admin picks: off (alert goes straight to the dashboard), annotate (alert now,
verdict added when it arrives) or gate (alert held until the verdict; rejected -> no alert). The
flow per incident lives in incident_pipeline.PendingVerification; this module only does the call.
"""
import datetime
import ipaddress
import logging
import socket
import threading
import time
import urllib.parse
import zoneinfo
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional

from sqlalchemy import select

from .. import models, secrets_store
from . import keyframes, prompts
from .base import ProviderError, VerdictResult, VLMProvider

logger = logging.getLogger(__name__)

# Defaults agreed 2026-11-08 (grilling Q31): car_prowling is gated (many false alarms), speeding is off
# (the measured speed is already precise and frames can't show speed).
DEFAULT_MODES = {"car_prowling": "gate", "exclusion": "annotate", "failed_to_stop": "annotate", "speeding": "off",
                 "fight": "gate"}  # fight: chosen 2026-11-08
EVENT_TYPE_LABELS = {
    "car_prowling": "Car prowling", "exclusion": "Exclusion zone breach",
    "failed_to_stop": "Failed to stop", "speeding": "Speeding", "fight": "Fight / assault",
}


@dataclass
class Snapshot:
    enabled: bool = False
    provider: str = "anthropic"
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    key_error: Optional[str] = None
    local_only: bool = False
    timeout_s: float = 20.0
    max_concurrent: int = 2
    max_calls_per_hour: int = 120
    gate_timeout_s: float = 8.0
    min_confidence: float = 0.6
    rejected_retention_days: int = 7
    modes: Dict[str, str] = field(default_factory=dict)
    templates: Dict[str, str] = field(default_factory=dict)


def is_local_url(url: Optional[str]) -> bool:
    """True if the URL's host is this machine or a private-network address (for "Local only")."""
    if not url:
        return False
    host = urllib.parse.urlparse(url).hostname or ""
    if host == "localhost" or host.endswith((".localhost", ".local", ".lan")):
        return True
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(ai[4][0]) for ai in socket.getaddrinfo(host, None)]
        except OSError:
            return False
    return bool(addrs) and all(a.is_private or a.is_loopback or a.is_link_local for a in addrs)


def effective_base_url(snap: Snapshot) -> Optional[str]:
    return snap.base_url or None  # None = the provider's public cloud endpoint


def build_provider(snap: Snapshot) -> VLMProvider:
    if snap.local_only and not is_local_url(effective_base_url(snap)):
        raise ProviderError("Local only is on, but the provider's address isn't on the local network")
    if snap.key_error:
        raise ProviderError(snap.key_error)
    if snap.provider == "anthropic":
        if not snap.api_key:
            raise ProviderError("no API key stored")
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(snap.api_key, snap.model or "", snap.timeout_s, snap.base_url or "")
    if snap.provider == "openai_compatible":
        from .openai_provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(snap.api_key or "", snap.model or "", snap.timeout_s, snap.base_url or "")
    if snap.provider == "google":
        from .google_provider import GoogleProvider
        return GoogleProvider(snap.api_key or "", snap.model or "", snap.timeout_s, snap.base_url or "")
    raise ProviderError(f"unknown provider {snap.provider!r}")


def get_settings(db) -> models.VlmSettings:
    row = db.get(models.VlmSettings, 1)
    if row is None:
        row = models.VlmSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def load_snapshot(db) -> Snapshot:
    row = get_settings(db)
    snap = Snapshot(
        enabled=row.enabled, provider=row.provider, base_url=row.base_url, model=row.model,
        local_only=row.local_only, timeout_s=row.timeout_s, max_concurrent=row.max_concurrent,
        max_calls_per_hour=row.max_calls_per_hour, gate_timeout_s=row.gate_timeout_s,
        min_confidence=row.min_confidence, rejected_retention_days=row.rejected_retention_days,
        modes=dict(DEFAULT_MODES),
    )
    if row.api_key_encrypted:
        try:
            snap.api_key = secrets_store.decrypt(row.api_key_encrypted)
        except secrets_store.SecretKeyMissing:
            snap.key_error = "TIAM_SECRET_KEY is not set on the server: the stored API key can't be read"
        except secrets_store.InvalidToken:
            snap.key_error = "stored API key can't be decrypted (TIAM_SECRET_KEY changed?) - enter it again"
    for et in db.scalars(select(models.VlmEventTypeSetting)):
        snap.modes[et.event_type] = et.mode
        if et.prompt_template:
            snap.templates[et.event_type] = et.prompt_template
    return snap


@dataclass
class VerificationOutcome:
    status: str  # done | error | skipped
    result: Optional[VerdictResult] = None
    error: Optional[str] = None

    @property
    def verdict(self) -> Optional[str]:
        return self.result.verdict if self.result else None


class VerificationService:
    def __init__(self, session_factory: Optional[Callable] = None):
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._snap = Snapshot()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._workers = 0
        self._calls: Deque[float] = deque()
        self._usage_lock = threading.Lock()
        self.pending = 0

    # ----------------------------------------------------------------- settings

    def _session(self):
        if self._session_factory is None:
            from ..database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory()

    def reload(self) -> None:
        db = self._session()
        try:
            snap = load_snapshot(db)
        finally:
            db.close()
        with self._lock:
            self._snap = snap
            if self._executor is None or self._workers != snap.max_concurrent:
                old = self._executor
                self._executor = ThreadPoolExecutor(max_workers=snap.max_concurrent, thread_name_prefix="vlm")
                self._workers = snap.max_concurrent
                if old is not None:
                    old.shutdown(wait=False)

    @property
    def snapshot(self) -> Snapshot:
        return self._snap

    def mode_for(self, event_type: Optional[str]) -> str:
        snap = self._snap
        if not snap.enabled or not event_type:
            return "off"
        return snap.modes.get(event_type, "annotate")

    # -------------------------------------------------------------------- calls

    def _take_budget(self) -> bool:
        now = time.time()
        with self._lock:
            while self._calls and now - self._calls[0] > 3600:
                self._calls.popleft()
            if len(self._calls) >= self._snap.max_calls_per_hour:
                return False
            self._calls.append(now)
            self.pending += 1
            return True

    def submit(self, event_id: int, camera_id: Optional[int], ev: dict, incident_ts: float,
               frames: list, on_done: Callable[[VerificationOutcome], None]) -> None:
        """Queues one verification; on_done runs on a worker thread when finished."""
        if not self._take_budget():
            outcome = VerificationOutcome("skipped", error="hourly AI verification cap reached")
            self._record(event_id, outcome)
            on_done(outcome)
            return
        self._executor.submit(self._run, event_id, camera_id, ev, incident_ts, frames, on_done)

    def _run(self, event_id, camera_id, ev, incident_ts, frames, on_done) -> None:
        try:
            outcome = self._verify(camera_id, ev, incident_ts, frames)
        except Exception as exc:  # pragma: no cover - never let a worker die silently
            logger.exception("AI verification of event %s crashed", event_id)
            outcome = VerificationOutcome("error", error=f"internal error: {type(exc).__name__}")
        finally:
            with self._lock:
                self.pending -= 1
        try:
            self._record(event_id, outcome)
        finally:
            on_done(outcome)

    def _verify(self, camera_id, ev, incident_ts, frames) -> VerificationOutcome:
        snap = self._snap
        key_ids = ev.get("key_track_ids") or [ev.get("track_id")]
        images = keyframes.build(frames, incident_ts, key_ids)
        if not images:
            return VerificationOutcome("error", error="no frames available for this incident")
        try:
            provider = build_provider(snap)
            system, prompt = self._prompt(camera_id, ev, incident_ts)
            result = provider.verify(images, system, prompt)
        except ProviderError as exc:
            return VerificationOutcome("error", error=str(exc))
        if result.confidence < snap.min_confidence:
            result.verdict = "uncertain"  # spec 6.3: low confidence counts as uncertain
        return VerificationOutcome("done", result=result)

    def _prompt(self, camera_id, ev, incident_ts):
        db = self._session()
        try:
            from .. import crud
            site = crud.get_default_site(db)
            camera = crud.get_camera(db, camera_id) if camera_id else None
            try:
                tz = zoneinfo.ZoneInfo(site.timezone)
            except Exception:
                tz = None
            local = datetime.datetime.fromtimestamp(incident_ts, tz).strftime("%a %d %b %H:%M")
            values = dict(site_type=site.site_type, camera=camera.name if camera else "?",
                          zone=ev.get("zone_name") or "-", local_time=local,
                          event_type=ev.get("type"), reason=prompts.detector_reason(ev))
        finally:
            db.close()
        etype = ev.get("type") or ""
        template = self._snap.templates.get(etype) or prompts.default_template(etype)
        return prompts.SYSTEM, prompts.render(template, **values)

    # ------------------------------------------------------------------- record

    def _record(self, event_id: int, outcome: VerificationOutcome) -> None:
        """Saves the verdict on the event, then bumps today's usage counters. Two separate
        transactions: a usage-counter problem must never leave the event stuck at "pending"."""
        db = self._session()
        try:
            row = db.get(models.Event, event_id)
            if row is not None:
                row.vlm_status = outcome.status
                row.vlm_error = outcome.error
                if outcome.result is not None:
                    r = outcome.result
                    row.vlm_verdict, row.vlm_confidence, row.vlm_reason = r.verdict, r.confidence, r.reason
                    row.vlm_observed, row.vlm_model, row.vlm_latency_ms = r.observed_actions, r.model, r.latency_ms
                row.verified_at = datetime.datetime.now()
                db.commit()
        except Exception:  # pragma: no cover - logged; the alert itself is already handled by the caller
            db.rollback()
            logger.exception("Saving AI verdict for event %s failed", event_id)
        finally:
            db.close()
        self._bump_usage(outcome)

    def _bump_usage(self, outcome: VerificationOutcome) -> None:
        # Verifications finish in parallel: two of them creating today's row at once used to hit a
        # duplicate-key error. Serialise inside the process; retry once if the DB still reports one.
        from sqlalchemy.exc import IntegrityError

        day = datetime.date.today().isoformat()
        with self._usage_lock:
            for attempt in range(2):
                db = self._session()
                try:
                    usage = db.get(models.VlmUsage, day)
                    if usage is None:
                        usage = models.VlmUsage(day=day, calls=0, errors=0, skipped=0, total_latency_ms=0,
                                                confirmed=0, rejected=0, uncertain=0)
                        db.add(usage)
                    if outcome.status == "skipped":
                        usage.skipped += 1
                    else:
                        usage.calls += 1
                        if outcome.status == "error":
                            usage.errors += 1
                        else:
                            usage.total_latency_ms += outcome.result.latency_ms
                            setattr(usage, outcome.result.verdict, getattr(usage, outcome.result.verdict) + 1)
                    db.commit()
                    return
                except IntegrityError:
                    db.rollback()
                    if attempt:
                        logger.exception("AI usage counter update failed")
                except Exception:  # pragma: no cover
                    db.rollback()
                    logger.exception("AI usage counter update failed")
                    return
                finally:
                    db.close()

    # --------------------------------------------------------------------- misc

    def test(self) -> dict:
        """Settings-page "Test connection": one built-in image, real provider call."""
        import cv2
        import ultralytics
        from pathlib import Path

        snap = self._snap
        img = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
        img = cv2.resize(img, (768, int(img.shape[0] * 768 / img.shape[1])))
        ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        prompt = ("CONNECTION TEST. Site: test. Detector: person near a bus.\n"
                  "Is at least one person visible standing near a bus? Answer with the JSON.")
        t0 = time.time()
        try:
            result = build_provider(snap).verify([jpeg.tobytes()], prompts.SYSTEM, prompt)
        except ProviderError as exc:
            return {"ok": False, "error": str(exc), "latency_ms": int((time.time() - t0) * 1000)}
        return {"ok": True, "verdict": result.verdict, "confidence": result.confidence, "reason": result.reason,
                "observed_actions": result.observed_actions, "model": result.model, "latency_ms": result.latency_ms}

    def fail_orphaned_pending(self) -> int:
        """At startup: an incident left 'pending' lost its verification when the server stopped.
        Mark it unverified so it doesn't show "Verifying" forever (its alert already went out, or
        - for gate mode - this was a crash; the incident itself is kept)."""
        from sqlalchemy import update

        db = self._session()
        try:
            n = db.execute(update(models.Event).where(models.Event.vlm_status == "pending").values(
                vlm_status="error", vlm_error="server restarted before the AI answered")).rowcount
            db.commit()
            return n or 0
        finally:
            db.close()

    def purge_rejected(self) -> int:
        """Deletes AI-rejected incidents older than rejected_retention_days (row, snapshot, clip)."""
        from ..routers.events import delete_events_and_snapshots

        cutoff = datetime.datetime.now() - datetime.timedelta(days=self._snap.rejected_retention_days)
        db = self._session()
        try:
            ids = list(db.scalars(select(models.Event.id).where(
                models.Event.vlm_verdict == "rejected", models.Event.timestamp < cutoff)))
            return delete_events_and_snapshots(db, ids) if ids else 0
        finally:
            db.close()


service = VerificationService()
