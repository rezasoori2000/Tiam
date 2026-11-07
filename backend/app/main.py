import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import auth, camera_manager, crud
from .database import Base, SessionLocal, engine, get_db
from .routers import (
    analytics,
    auth as auth_router,
    calibration,
    camera_feed,
    cameras,
    detection_settings,
    events,
    heatmap as heatmap_router,
    incidents,
    roles,
    sites,
    system,
    users,
    zone_types,
    zones,
)
from .ws_manager import alerts_manager

BASE_DIR = Path(__file__).resolve().parent.parent

Base.metadata.create_all(bind=engine)


def _add_missing_columns(table: str, new_columns: dict) -> None:
    """`create_all` only creates missing tables, not missing columns on a
    table that already exists -- patch in newly-added columns here so
    existing databases pick them up without a full migration tool."""
    with engine.begin() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = :table"
                ),
                {"table": table},
            )
        }
        for column, ddl_type in new_columns.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD {column} {ddl_type}"))


_add_missing_columns(
    "cameras",
    {
        "stream_path": "NVARCHAR(MAX) NULL",
        "username": "NVARCHAR(MAX) NULL",
        "password": "NVARCHAR(MAX) NULL",
        "fisheye_center_x": "FLOAT NULL",
        "fisheye_center_y": "FLOAT NULL",
        "fisheye_radius_x": "FLOAT NULL",
        "fisheye_radius_y": "FLOAT NULL",
        "fisheye_inner_radius": "FLOAT NULL",
        "restricted_zone_id": "INT NULL",
        "fisheye_parent_id": "INT NULL",
        "view_direction_deg": "FLOAT NULL",
        "view_tilt_deg": "FLOAT NULL",
        "view_fov_deg": "FLOAT NULL",
        "site_id": "INT NULL",
    },
)
_add_missing_columns(
    "zone_types",
    {
        "time_restriction_enabled": "BIT NOT NULL DEFAULT 0",
        "default_from_time": "NVARCHAR(5) NULL",
        "default_to_time": "NVARCHAR(5) NULL",
        "rule_stop_required": "BIT NOT NULL DEFAULT 0",
        "default_stop_min_seconds": "FLOAT NOT NULL DEFAULT 1.0",
    },
)
_add_missing_columns(
    "zones",
    {
        "time_restriction_enabled": "BIT NOT NULL DEFAULT 0",
        "from_time": "NVARCHAR(5) NULL",
        "to_time": "NVARCHAR(5) NULL",
        "rule_stop_required": "BIT NOT NULL DEFAULT 0",
        "stop_min_seconds": "FLOAT NOT NULL DEFAULT 1.0",
    },
)
_add_missing_columns(
    "detection_settings",
    {
        "confirmation_min_observations": "INT NOT NULL DEFAULT 3",
        "confirmation_window_frames": "INT NOT NULL DEFAULT 6",
        "detector_imgsz": "INT NOT NULL DEFAULT 960",
        "detector_model": "NVARCHAR(255) NOT NULL DEFAULT 'yolov8s.pt'",
        "ignore_person_shadows": "BIT NOT NULL DEFAULT 1",
    },
)

_add_missing_columns("calibrations", {"real_world_width_m": "FLOAT NULL"})
_add_missing_columns("users", {"must_change_password": "BIT NOT NULL DEFAULT 0"})
_add_missing_columns("events", {"event_type": "NVARCHAR(64) NULL", "has_clip": "BIT NOT NULL DEFAULT 0"})

with SessionLocal() as _db:
    crud.seed_default_zone_types(_db)
    crud.seed_default_admin(_db)
    crud.seed_default_site(_db)


async def _pump_alerts(alert_queue: asyncio.Queue) -> None:
    while True:
        payload = await alert_queue.get()
        await alerts_manager.broadcast_json(payload)


async def _drain_until_disconnect(websocket: WebSocket) -> None:
    """Blocks until the client disconnects. We don't expect inbound
    messages on these feeds; receive() (rather than receive_text/bytes)
    returns the raw ASGI disconnect message instead of raising, so we check
    the type explicitly and break -- calling receive() again afterwards is
    invalid and raises RuntimeError."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    alert_queue: asyncio.Queue = asyncio.Queue()

    db = SessionLocal()
    camera_manager.start_all(loop, alert_queue, db)
    db.close()

    alert_task = asyncio.create_task(_pump_alerts(alert_queue))
    try:
        yield
    finally:
        alert_task.cancel()
        camera_manager.stop_all()


app = FastAPI(title="Security Camera Config API", lifespan=lifespan)
# Extra origins (comma-separated) for a frontend hosted somewhere other than
# the backend itself -- not needed for the release build, which serves the
# SPA from this same origin (see the SPA fallback route at the bottom).
_extra_cors_origins = [
    o.strip() for o in os.environ.get("SECURITYCAM_CORS_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", *_extra_cors_origins],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router.router)

_login_required = [Depends(auth.get_current_user)]
app.include_router(cameras.router, dependencies=_login_required)
app.include_router(camera_feed.router, dependencies=_login_required)
app.include_router(zone_types.router, dependencies=_login_required)
app.include_router(zones.router, dependencies=_login_required)
app.include_router(calibration.router, dependencies=_login_required)
app.include_router(events.router, dependencies=_login_required)
app.include_router(incidents.router, dependencies=_login_required)
app.include_router(analytics.router, dependencies=_login_required)
app.include_router(heatmap_router.router, dependencies=_login_required)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(detection_settings.router)
app.include_router(sites.router, dependencies=_login_required)
app.include_router(system.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/stream/{camera_id}")
async def ws_stream(
    websocket: WebSocket, camera_id: int, token: Optional[str] = None,
    db: Session = Depends(get_db),
):
    user = auth.get_user_from_token(db, token)
    if user is None or user.must_change_password:
        await websocket.close(code=1008)
        return
    manager = camera_manager.get_stream_manager(camera_id)
    await manager.connect(websocket)
    await _drain_until_disconnect(websocket)
    manager.disconnect(websocket)


@app.websocket("/ws/alerts")
async def ws_alerts(
    websocket: WebSocket, token: Optional[str] = None, db: Session = Depends(get_db),
):
    user = auth.get_user_from_token(db, token)
    if user is None or user.must_change_password:
        await websocket.close(code=1008)
        return
    await alerts_manager.connect(websocket)
    await _drain_until_disconnect(websocket)
    alerts_manager.disconnect(websocket)


# Release build: the built frontend (frontend/dist) is copied to
# backend/static by build-release.ps1, and served from here so the whole app
# is one process on one port with no CORS. Registered last so every /api and
# /ws route above wins; any other path serves a real file if one exists,
# otherwise index.html so client-side routes (/admin/cameras etc.) survive a
# browser refresh. Absent in dev, where Vite serves the frontend instead.
FRONTEND_DIR = (BASE_DIR / "static").resolve()
if (FRONTEND_DIR / "index.html").is_file():

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404)
        candidate = (FRONTEND_DIR / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIR in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")
