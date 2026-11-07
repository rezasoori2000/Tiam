from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, crud, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/users", tags=["users"], dependencies=[Depends(auth.require_admin)]
)


@router.get("", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    return crud.get_users(db)


@router.post("", response_model=schemas.UserOut, status_code=201)
def create_user(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    if crud.get_user_by_username(db, user_in.username) is not None:
        raise HTTPException(status_code=400, detail="Username already exists")
    if crud.get_role(db, user_in.role_id) is None:
        raise HTTPException(status_code=400, detail="Role not found")
    return crud.create_user(db, user_in)


@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, user_in: schemas.UserUpdate, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user_in.role_id is not None and crud.get_role(db, user_in.role_id) is None:
        raise HTTPException(status_code=400, detail="Role not found")
    return crud.update_user(db, user, user_in)


@router.post("/{user_id}/reset-password", response_model=schemas.UserOut)
def reset_password(
    user_id: int, body: schemas.PasswordResetRequest, db: Session = Depends(get_db)
):
    user = crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return crud.reset_password(db, user, body.new_password)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_system:
        raise HTTPException(status_code=400, detail="The built-in admin user cannot be deleted")
    crud.delete_user(db, user)
