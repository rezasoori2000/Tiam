"""AI verification: verdict parsing, gate/annotate/timeout/cap flows, local-only, and the
OpenAI-compatible provider (the local Qwen/Ollama path) against a fake model server on localhost."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np
import pytest

from app.incident_pipeline import PendingVerification
from app.vlm import keyframes
from app.vlm.base import ProviderError, VerdictResult, parse_verdict
from app.vlm.service import Snapshot, VerificationOutcome, VerificationService, build_provider, is_local_url


# ------------------------------------------------------------------ parsing

def test_parse_strict_json_and_clamps():
    r = parse_verdict(json.dumps({"verdict": "Confirmed", "confidence": 1.7, "observed_actions": ["pulls door handle"],
                                  "reason": "x", "severity_suggestion": 42, "person_description_for_talkdown": None}), "m", 5)
    assert (r.verdict, r.confidence, r.severity_suggestion, r.person_description) == ("confirmed", 1.0, 10, None)


def test_parse_json_wrapped_in_prose():
    text = 'Sure! ```json\n{"verdict": "rejected", "confidence": 0.8, "observed_actions": [], "reason": "owner"}\n```'
    assert parse_verdict(text, "m", 1).verdict == "rejected"


@pytest.mark.parametrize("bad", ["no json here", '{"verdict": "maybe", "confidence": 1}', "[1, 2]"])
def test_parse_rejects_garbage(bad):
    with pytest.raises(ProviderError):
        parse_verdict(bad, "m", 1)


# ------------------------------------------------------------------ flows

class Dispatcher:
    def __init__(self):
        self.sent = []

    def dispatch(self, payload):
        self.sent.append(payload)


class FakeVerifier:
    """Stands in for VerificationService: answers synchronously (or never, for timeouts)."""
    def __init__(self, outcome=None, gate_timeout_s=8.0):
        self.outcome, self.snapshot = outcome, Snapshot(gate_timeout_s=gate_timeout_s)

    def submit(self, event_id, camera_id, ev, ts, frames, on_done):
        if self.outcome is not None:
            on_done(self.outcome)


def done(verdict, conf=0.9):
    return VerificationOutcome("done", result=VerdictResult(verdict=verdict, confidence=conf, reason="r"))


def pending(mode, verifier, d):
    return PendingVerification(1, {"type": "car_prowling"}, 100.0, mode, {"event_id": 1}, [], d, verifier, 3)


def test_gate_confirmed_alerts_once_with_verdict():
    d = Dispatcher()
    pending("gate", FakeVerifier(done("confirmed")), d).submit()
    assert [(p["vlm_status"], p.get("vlm_verdict")) for p in d.sent] == [("done", "confirmed")]


def test_gate_rejected_is_not_alerted():
    d = Dispatcher()
    pending("gate", FakeVerifier(done("rejected")), d).submit()
    assert d.sent == []


def test_gate_error_alerts_unverified():
    d = Dispatcher()
    pending("gate", FakeVerifier(VerificationOutcome("error", error="timed out")), d).submit()
    assert [p["vlm_status"] for p in d.sent] == ["unverified"]


def test_gate_timeout_alerts_then_late_verdict_is_an_update():
    d = Dispatcher()
    pv = pending("gate", FakeVerifier(None, gate_timeout_s=0.05), d)
    pv.submit()  # no answer
    time.sleep(0.2)
    assert [p["vlm_status"] for p in d.sent] == ["unverified"]
    pv._on_done(done("confirmed"))  # verdict arrives late
    assert d.sent[-1]["kind"] == "verification" and d.sent[-1]["vlm_verdict"] == "confirmed"
    assert len(d.sent) == 2


def test_annotate_alerts_immediately_then_updates():
    d = Dispatcher()
    pv = pending("annotate", FakeVerifier(None), d)
    assert [p["vlm_status"] for p in d.sent] == ["pending"]
    pv._on_done(done("rejected"))
    assert d.sent[-1] == {"kind": "verification", "event_id": 1, "vlm_status": "done",
                          "vlm_verdict": "rejected", "vlm_confidence": 0.9, "vlm_reason": "r"}


def test_frames_collected_until_post_window():
    d = Dispatcher()
    pv = pending("annotate", FakeVerifier(None), d)
    assert not pv.add_frame((101.0, b"", []))
    assert pv.add_frame((100.0 + keyframes.POST_S, b"", []))
    assert len(pv.frames) == 2


def test_hourly_cap_skips_and_still_answers(monkeypatch):
    svc = VerificationService(session_factory=lambda: None)
    svc._snap = Snapshot(enabled=True, max_calls_per_hour=2, modes={"exclusion": "gate"})
    monkeypatch.setattr(svc, "_record", lambda *a: None)
    svc._executor = type("E", (), {"submit": lambda self, *a: None})()
    got = []
    for _ in range(3):
        svc.submit(1, 1, {"type": "exclusion"}, 0.0, [], got.append)
    assert [o.status for o in got] == ["skipped"]  # third call over the cap
    assert svc.mode_for("exclusion") == "gate" and svc.mode_for("speeding") == "annotate"
    svc._snap.enabled = False
    assert svc.mode_for("exclusion") == "off"


def test_parallel_records_count_every_call_and_never_lose_the_verdict(tmp_path):
    """Regression: parallel verifications creating today's usage row hit a duplicate key, and the same
    transaction rolled back the event's verdict (event stuck 'pending')."""
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import models
    from app.database import Base

    # a file DB: one connection per thread, like SQL Server (in-memory SQLite shares one connection)
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine, tables=[models.Event.__table__, models.VlmUsage.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as db:
        import datetime
        for i in range(1, 9):
            db.add(models.Event(id=i, zone_name="z", policy_type="p", risk_score=5, raw_payload={},
                                timestamp=datetime.datetime.now(), vlm_status="pending"))
        db.commit()
    svc = VerificationService(session_factory=Session)
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: svc._record(i, done("confirmed")), range(1, 9)))
    with Session() as db:
        assert {e.vlm_status for e in db.query(models.Event)} == {"done"}
        usage = db.query(models.VlmUsage).one()
        assert (usage.calls, usage.confirmed) == (8, 8)


# ------------------------------------------------------------------ local only

def test_is_local_url():
    assert is_local_url("http://localhost:11434/v1")
    assert is_local_url("http://192.168.1.20:8000/v1")
    assert is_local_url("http://10.0.0.5/v1")
    assert not is_local_url("https://8.8.8.8/v1")
    assert not is_local_url(None)


def test_local_only_refuses_cloud_provider():
    with pytest.raises(ProviderError, match="Local only"):
        build_provider(Snapshot(provider="anthropic", api_key="k", local_only=True))


# ------------------------------------------------------------------ keyframes

def test_keyframes_crops_and_thumbnail():
    frame = np.full((540, 960, 3), 80, np.uint8)
    ok, jpeg = cv2.imencode(".jpg", frame)
    boxes = [{"id": 7, "cls": "person", "xyxy": [400, 200, 430, 300]}, {"id": 2, "cls": "car", "xyxy": [10, 10, 100, 60]}]
    items = [(100.0 + i * 0.2, jpeg.tobytes(), boxes) for i in range(-40, 15)]
    imgs = keyframes.build(items, 100.0, [7])
    assert 2 <= len(imgs) <= keyframes.MAX_CROPS + 1
    decoded = [cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR) for b in imgs]
    assert max(decoded[0].shape[:2]) >= keyframes.CROP_MIN  # small crop upscaled
    assert decoded[-1].shape[1] == keyframes.THUMB_W


# ------------------------------------------------------------------ local model server

class _FakeOllama(BaseHTTPRequestHandler):
    last_body = None

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeOllama.last_body = body
        answer = {"verdict": "confirmed", "confidence": 0.82, "observed_actions": ["tries a door handle"],
                  "reason": "person pulls the handle of a second car", "severity_suggestion": 8,
                  "person_description_for_talkdown": "dark hoodie"}
        reply = {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                 "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": json.dumps(answer)}}]}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_openai_compatible_provider_against_local_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        snap = Snapshot(provider="openai_compatible", model="qwen3-vl:8b", local_only=True,
                        base_url=f"http://127.0.0.1:{server.server_port}/v1")
        r = build_provider(snap).verify([b"\xff\xd8fakejpeg"], "system text", "is this prowling?")
    finally:
        server.shutdown()
    assert (r.verdict, r.confidence, r.person_description, r.model) == ("confirmed", 0.82, "dark hoodie", "qwen3-vl:8b")
    body = _FakeOllama.last_body
    assert body["messages"][0] == {"role": "system", "content": "system text"}
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert body["response_format"]["type"] == "json_schema"
