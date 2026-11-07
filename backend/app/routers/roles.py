from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, crud, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/roles", tags=["roles"], dependencies=[Depends(auth.require_admin)]
)


@router.get("", response_model=list[schemas.RoleOut])
def list_roles(db: Session = Depends(get_db)):
    return crud.get_roles(db)


@router.get("/pages", response_model=list[str])
def list_page_keys():
    return schemas.PAGE_KEYS


@router.post("", response_model=schemas.RoleOut, status_code=201)
def create_role(role_in: schemas.RoleCreate, db: Session = Depends(get_db)):
    return crud.create_role(db, role_in)


@router.put("/{role_id}", response_model=schemas.RoleOut)
def update_role(role_id: int, role_in: schemas.RoleUpdate, db: Session = Depends(get_db)):
    role = crud.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="The built-in Admin role cannot be edited")
    return crud.update_role(db, role, role_in)


@router.delete("/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = crud.get_role(db, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="The built-in Admin role cannot be deleted")
    if crud.get_users_by_role(db, role_id):
        raise HTTPException(status_code=400, detail="Cannot delete a role that has users assigned to it")
    crud.delete_role(db, role)
