from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import camera_manager, crud, fisheye, schemas
from ..database import get_db

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("", response_model=list[schemas.CameraOut])
def list_cameras(db: Session = Depends(get_db)):
    return crud.get_cameras(db)


@router.post("", response_model=schemas.CameraOut, status_code=201)
def create_camera(camera_in: schemas.CameraCreate, db: Session = Depends(get_db)):
    camera = crud.create_camera(db, camera_in)
    camera_manager.on_camera_changed(db, camera.id)
    return camera


@router.get("/{camera_id}", response_model=schemas.CameraOut)
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


@router.put("/{camera_id}", response_model=schemas.CameraOut)
def update_camera(camera_id: int, camera_in: schemas.CameraUpdate, db: Session = Depends(get_db)):
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera_in.restricted_zone_id is not None:
        zone = crud.get_zone(db, camera_in.restricted_zone_id)
        if zone is None or zone.camera_id != camera_id:
            raise HTTPException(
                status_code=400, detail="restricted_zone_id must be a zone belonging to this camera"
            )
    camera = crud.update_camera(db, camera, camera_in)
    camera_manager.on_camera_changed(db, camera.id)
    return camera


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    # Stop the live worker only after the DB delete actually succeeds --
    # otherwise a failed delete (e.g. FK violation) leaves the camera row
    # alive but its worker torn down with nothing to restart it.
    for deleted_id in crud.delete_camera(db, camera):
        camera_manager.on_camera_removed(deleted_id)


def _get_fisheye_camera(db: Session, camera_id: int):
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if camera.source_type != "fisheye":
        raise HTTPException(status_code=400, detail="Camera is not a fisheye camera")
    return camera


@router.get("/{camera_id}/fisheye-views", response_model=list[schemas.CameraOut])
def list_fisheye_views(camera_id: int, db: Session = Depends(get_db)):
    _get_fisheye_camera(db, camera_id)
    return crud.get_fisheye_views(db, camera_id)


@router.put("/{camera_id}/fisheye-views", response_model=list[schemas.CameraOut])
def save_fisheye_views(camera_id: int, body: schemas.FisheyeViewsIn, db: Session = Depends(get_db)):
    """Replaces this fisheye camera's set of virtual views (each becomes
    its own camera with its own zones/calibration/detection)."""
    parent = _get_fisheye_camera(db, camera_id)
    had_views = bool(crud.get_fisheye_views(db, camera_id))
    views, deleted_ids = crud.save_fisheye_views(db, parent, body.views)
    for deleted_id in deleted_ids:
        camera_manager.on_camera_removed(deleted_id)
    if views and not had_views and parent.is_enabled:
        # The views now cover the whole lens -- also detecting on the
        # parent's single de-warped image would raise every alert twice.
        parent.is_enabled = False
        db.commit()
        camera_manager.on_camera_changed(db, parent.id)
    for view in views:
        camera_manager.on_camera_changed(db, view.id)
    return views


@router.post("/{camera_id}/fisheye/detect-circle")
def detect_fisheye_circle(camera_id: int, db: Session = Depends(get_db)):
    """Finds the lens circle in the latest raw frame. Doesn't save it --
    the Fisheye Setup page shows it for the user to confirm and save."""
    _get_fisheye_camera(db, camera_id)
    frame = camera_manager.get_latest_fisheye_raw_frame(camera_id)
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available yet for this camera")
    circle = fisheye.detect_lens_circle(frame)
    if circle is None:
        raise HTTPException(status_code=422, detail="Couldn't find the lens circle in the current frame")
    cx, cy, rx, ry = circle
    return {"fisheye_center_x": cx, "fisheye_center_y": cy, "fisheye_radius_x": rx, "fisheye_radius_y": ry}


@router.get("/{camera_id}/status")
def camera_status(camera_id: int, db: Session = Depends(get_db)):
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera_manager.get_status(camera_id)


@router.post("/{camera_id}/restart")
def restart_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    camera_manager.restart_camera(db, camera_id)
    return camera_manager.get_status(camera_id)
