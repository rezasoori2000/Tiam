from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import camera_manager, crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/calibration", tags=["calibration"])


@router.get("", response_model=list[schemas.CalibrationOut])
def list_calibrations(camera_id: Optional[int] = None, db: Session = Depends(get_db)):
    return crud.get_calibrations(db, camera_id=camera_id)


@router.post("", response_model=schemas.CalibrationOut, status_code=201)
def create_calibration(cal_in: schemas.CalibrationCreate, db: Session = Depends(get_db)):
    return crud.create_calibration(db, cal_in)


@router.get("/active", response_model=schemas.CalibrationOut)
def get_active_calibration(camera_id: int, db: Session = Depends(get_db)):
    calibration = crud.get_active_calibration(db, camera_id=camera_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="No active calibration set for this camera")
    return calibration


@router.get("/{cal_id}", response_model=schemas.CalibrationOut)
def get_calibration(cal_id: int, db: Session = Depends(get_db)):
    calibration = crud.get_calibration(db, cal_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    return calibration


@router.put("/{cal_id}", response_model=schemas.CalibrationOut)
def update_calibration(
    cal_id: int, cal_in: schemas.CalibrationUpdate, db: Session = Depends(get_db)
):
    calibration = crud.get_calibration(db, cal_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    calibration = crud.update_calibration(db, calibration, cal_in)
    camera_manager.on_camera_changed(db, calibration.camera_id)
    return calibration


@router.post("/{cal_id}/activate", response_model=schemas.CalibrationOut)
def activate_calibration(cal_id: int, db: Session = Depends(get_db)):
    calibration = crud.get_calibration(db, cal_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    calibration = crud.activate_calibration(db, calibration)
    camera_manager.on_camera_changed(db, calibration.camera_id)
    return calibration


@router.delete("/{cal_id}", status_code=204)
def delete_calibration(cal_id: int, db: Session = Depends(get_db)):
    calibration = crud.get_calibration(db, cal_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    camera_id = calibration.camera_id
    crud.delete_calibration(db, calibration)
    camera_manager.on_camera_changed(db, camera_id)
