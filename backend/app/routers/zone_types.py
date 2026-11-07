from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/zone-types", tags=["zone-types"])


@router.get("", response_model=list[schemas.ZoneTypeOut])
def list_zone_types(db: Session = Depends(get_db)):
    return crud.get_zone_types(db)


@router.post("", response_model=schemas.ZoneTypeOut, status_code=201)
def create_zone_type(zt_in: schemas.ZoneTypeCreate, db: Session = Depends(get_db)):
    return crud.create_zone_type(db, zt_in)


@router.get("/{zone_type_id}", response_model=schemas.ZoneTypeOut)
def get_zone_type(zone_type_id: int, db: Session = Depends(get_db)):
    zone_type = crud.get_zone_type(db, zone_type_id)
    if zone_type is None:
        raise HTTPException(status_code=404, detail="Zone type not found")
    return zone_type


@router.put("/{zone_type_id}", response_model=schemas.ZoneTypeOut)
def update_zone_type(
    zone_type_id: int, zt_in: schemas.ZoneTypeUpdate, db: Session = Depends(get_db)
):
    zone_type = crud.get_zone_type(db, zone_type_id)
    if zone_type is None:
        raise HTTPException(status_code=404, detail="Zone type not found")
    return crud.update_zone_type(db, zone_type, zt_in)


@router.delete("/{zone_type_id}", status_code=204)
def delete_zone_type(zone_type_id: int, db: Session = Depends(get_db)):
    zone_type = crud.get_zone_type(db, zone_type_id)
    if zone_type is None:
        raise HTTPException(status_code=404, detail="Zone type not found")
    if zone_type.is_system:
        raise HTTPException(status_code=400, detail="Built-in zone types cannot be deleted")
    crud.delete_zone_type(db, zone_type)
