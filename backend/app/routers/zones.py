from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import camera_manager, crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/zones", tags=["zones"])


@router.get("", response_model=list[schemas.ZoneOut])
def list_zones(camera_id: Optional[int] = None, db: Session = Depends(get_db)):
    return crud.get_zones(db, camera_id=camera_id)


@router.post("", response_model=schemas.ZoneOut, status_code=201)
def create_zone(zone_in: schemas.ZoneCreate, db: Session = Depends(get_db)):
    try:
        zone = crud.create_zone(db, zone_in)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    camera_manager.on_camera_changed(db, zone.camera_id)
    return zone


@router.get("/{zone_id}", response_model=schemas.ZoneOut)
def get_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = crud.get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone


@router.put("/{zone_id}", response_model=schemas.ZoneOut)
def update_zone(zone_id: int, zone_in: schemas.ZoneUpdate, db: Session = Depends(get_db)):
    zone = crud.get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    zone = crud.update_zone(db, zone, zone_in)
    camera_manager.on_camera_changed(db, zone.camera_id)
    return zone


@router.delete("/{zone_id}", status_code=204)
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = crud.get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    camera_id = zone.camera_id
    crud.delete_zone(db, zone)
    camera_manager.on_camera_changed(db, camera_id)
