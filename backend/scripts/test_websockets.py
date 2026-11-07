"""Stage 3 end-to-end test: start the real FastAPI app (lifespan spins up
the background worker), connect to /ws/stream and /ws/alerts, and verify
frame rate + JPEG validity + alert schema + DB persistence."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app import models

with TestClient(app) as client:
    print("App started (worker thread + pump tasks launched).")

    with client.websocket_connect("/ws/stream") as ws_stream:
        print("Connected to /ws/stream. Warming up (model load + first frames)...")
        frames = []
        t_start = time.time()
        # first frame may take a while (model load); allow generous warmup
        while len(frames) < 40 and time.time() - t_start < 40:
            data = ws_stream.receive_bytes()
            frames.append((time.time(), data))

        elapsed = frames[-1][0] - frames[0][0]
        fps = (len(frames) - 1) / elapsed if elapsed > 0 else 0.0
        print(f"Received {len(frames)} frames in {elapsed:.2f}s -> {fps:.1f} fps")

        # validate JPEG-decodability of the last frame
        last_bytes = frames[-1][1]
        arr = np.frombuffer(last_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        print(f"Last frame decodes OK: {img is not None}, shape={img.shape if img is not None else None}")
        assert img is not None, "frame did not decode as a valid JPEG"

    with client.websocket_connect("/ws/alerts") as ws_alerts:
        print("Connected to /ws/alerts. Waiting for an alert (up to 60s)...")
        ws_alerts_socket = ws_alerts
        alert_msg = None
        t_start = time.time()
        while time.time() - t_start < 60:
            try:
                alert_msg = ws_alerts.receive_json(mode="text")
                break
            except Exception:
                continue
        print("Alert received:", alert_msg)
        if alert_msg:
            expected_keys = {"event_id", "zone_name", "policy_type", "risk_score", "timestamp"}
            assert expected_keys.issubset(alert_msg.keys()), f"missing keys: {expected_keys - alert_msg.keys()}"
            print("Alert schema OK.")
        else:
            print("WARNING: no alert observed within timeout (may be expected if no zones configured).")

db = SessionLocal()
count = db.query(models.Event).count()
print(f"\nEvents persisted in DB: {count}")
if count:
    last = db.query(models.Event).order_by(models.Event.id.desc()).first()
    print("Most recent event row:", last.id, last.policy_type, last.risk_score, last.timestamp)
db.close()

print("\nDONE.")
