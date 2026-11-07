from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("", response_model=list[schemas.SiteOut])
def list_sites(db: Session = Depends(get_db)):
    return crud.get_sites(db)


@router.put("/{site_id}", response_model=schemas.SiteOut, dependencies=[Depends(auth.require_admin)])
def update_site(site_id: int, data: schemas.SiteUpdate, db: Session = Depends(get_db)):
    site = crud.get_site(db, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return crud.update_site(db, site, data)
