from typing import Optional

import cv2
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import camera_manager, crud, fisheye
from ..database import get_db

router = APIRouter(prefix="/api/camera", tags=["camera-feed"])


@router.get("/snapshot")
def get_snapshot(camera_id: int, db: Session = Depends(get_db)):
    """Returns the most recent frame from this camera's live worker (no new
    capture connection is opened -- avoids contending with the worker's own
    open device handle)."""
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    jpeg_bytes = camera_manager.get_latest_snapshot(camera_id)
    if jpeg_bytes is None:
        raise HTTPException(
            status_code=503, detail="No frame available yet for this camera"
        )
    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.get("/snapshot-raw")
def get_raw_fisheye_snapshot(camera_id: int, db: Session = Depends(get_db)):
    """Returns the most recent RAW (still circular, not de-warped) frame for
    a fisheye camera -- used by the Fisheye Setup page so the user can pick
    the circle's center/radius against the actual undistorted capture."""
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.source_type != "fisheye":
        raise HTTPException(status_code=400, detail="Camera is not a fisheye camera")
    jpeg_bytes = camera_manager.get_latest_fisheye_raw_snapshot(camera_id)
    if jpeg_bytes is None:
        raise HTTPException(
            status_code=503, detail="No frame available yet for this camera"
        )
    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.get("/fisheye-view-preview")
def get_fisheye_view_preview(
    camera_id: int,
    direction: float = 0.0,
    tilt: float = Query(fisheye.DEFAULT_VIEW_TILT, ge=0, le=89),
    fov: float = Query(fisheye.DEFAULT_VIEW_FOV, ge=20, le=150),
    # Lens circle to use (ratios) -- lets the page preview an unsaved
    # circle. Omitted = the camera's saved calibration, else auto-detect.
    cx: Optional[float] = None,
    cy: Optional[float] = None,
    rx: Optional[float] = None,
    ry: Optional[float] = None,
    db: Session = Depends(get_db),
):
    """Renders one virtual camera view from the latest raw fisheye frame,
    for the view editor on the Fisheye Setup page."""
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.source_type != "fisheye":
        raise HTTPException(status_code=400, detail="Camera is not a fisheye camera")
    frame = camera_manager.get_latest_fisheye_raw_frame(camera_id)
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available yet for this camera")

    if None not in (cx, cy, rx, ry):
        circle = (cx, cy, rx, ry)
    elif camera.fisheye_center_x is not None and camera.fisheye_radius_x:
        circle = (
            camera.fisheye_center_x, camera.fisheye_center_y,
            camera.fisheye_radius_x, camera.fisheye_radius_y or camera.fisheye_radius_x,
        )
    else:
        circle = fisheye.detect_lens_circle(frame)
        if circle is None:
            raise HTTPException(status_code=422, detail="Couldn't find the lens circle -- mark it manually")

    src_h, src_w = frame.shape[:2]
    maps = fisheye.build_view_maps(src_w, src_h, circle, direction, tilt, fov, 640, 360)
    ok, jpeg = cv2.imencode(".jpg", fisheye.render_view(frame, maps), [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode preview")
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")
