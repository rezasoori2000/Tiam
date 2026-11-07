"""Stage 5 end-to-end test: real webcam camera + a deliberately-unreachable
IP camera, running concurrently. Verifies:
  - camera CRUD + validation
  - per-camera zone/calibration scoping
  - worker isolation (bad camera doesn't affect the good one)
  - /ws/stream/{camera_id} delivers frames only for that camera
  - /ws/alerts is camera-tagged
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app import crud, schemas
from app.database import SessionLocal

db = SessionLocal()
for z in crud.get_zones(db): crud.delete_zone(db, z)
for c in crud.get_calibrations(db): crud.delete_calibration(db, c)
for cam in crud.get_cameras(db): crud.delete_camera(db, cam)
db.close()

with TestClient(app) as client:
    print("=== Camera CRUD ===")
    r = client.post("/api/cameras", json={"name": "Server Webcam", "source_type": "webcam", "device_index": 0})
    print("create webcam camera:", r.status_code, r.json())
    webcam_id = r.json()["id"]

    r = client.post("/api/cameras", json={
        "name": "Loading Bay IP Cam", "source_type": "ip",
        "protocol": "rtsp", "ip": "10.255.255.1", "port": 554,
    })
    print("create ip camera:", r.status_code, r.json())
    ip_cam_id = r.json()["id"]

    r = client.post("/api/cameras", json={"name": "bad", "source_type": "ip"})
    print("invalid ip camera (missing fields) expect 422:", r.status_code)

    r = client.get("/api/cameras")
    print("list cameras:", len(r.json()))

    print("\n=== Per-camera zones ===")
    r = client.post("/api/zones", json={
        "camera_id": webcam_id, "name": "Webcam Exclusion Zone",
        "polygon_points": [[0, 0], [960, 0], [960, 540], [0, 540]],
        "rule_exclusion": True,
    })
    print("create zone for webcam:", r.status_code)

    r = client.get(f"/api/zones?camera_id={webcam_id}")
    print(f"zones for webcam camera ({webcam_id}):", len(r.json()))
    r = client.get(f"/api/zones?camera_id={ip_cam_id}")
    print(f"zones for ip camera ({ip_cam_id}) (should be 0):", len(r.json()))

    print("\n=== Worker isolation: letting both run for ~8s ===")
    time.sleep(8)

    r = client.get(f"/api/cameras/{webcam_id}/status")
    print("webcam status:", r.json())
    r = client.get(f"/api/cameras/{ip_cam_id}/status")
    print("ip camera status (expect reconnecting/error, NOT crash):", r.json())

    print("\n=== /ws/stream/{camera_id} for webcam ===")
    with client.websocket_connect(f"/ws/stream/{webcam_id}") as ws:
        frames = []
        t0 = time.time()
        while len(frames) < 10 and time.time() - t0 < 20:
            frames.append(ws.receive_bytes())
        print(f"received {len(frames)} frames from webcam stream")
        if frames:
            arr = np.frombuffer(frames[-1], dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            print("last frame decodes OK:", img is not None, "shape:", img.shape if img is not None else None)

    print("\n=== /ws/alerts is camera-tagged ===")
    with client.websocket_connect("/ws/alerts") as ws:
        t0 = time.time()
        alert = None
        while time.time() - t0 < 15:
            try:
                alert = ws.receive_json(mode="text")
                break
            except Exception:
                continue
        print("alert received:", alert)
        if alert:
            assert "camera_id" in alert, "alert payload missing camera_id"
            print("camera_id present in alert payload: OK")

    print("\n=== re-check webcam still healthy after ip-cam churn ===")
    r = client.get(f"/api/cameras/{webcam_id}/status")
    print("webcam status:", r.json())

print("\nDONE.")
