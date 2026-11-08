from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import auth, crud, schemas
from ..database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.LoginResponse)
def login(credentials: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, credentials.username)
    if user is None or not auth.verify_password(
        credentials.password, user.password_hash, user.password_salt
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = auth.create_session(db, user)
    role = crud.get_role(db, user.role_id)
    return schemas.LoginResponse(token=token, user=user, role=role)


@router.post("/change-password", status_code=204)
def change_password(
    body: schemas.PasswordChangeRequest, user=Depends(auth.get_current_user), db: Session = Depends(get_db)
):
    if not auth.verify_password(body.current_password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"New password must be at least {auth.MIN_PASSWORD_LENGTH} characters")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    user.password_hash, user.password_salt = auth.hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    crud.INITIAL_ADMIN_PASSWORD_FILE.unlink(missing_ok=True)  # one-time password no longer valid


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        auth.delete_session(db, auth_header.removeprefix("Bearer "))


@router.get("/me", response_model=schemas.MeResponse)
def me(user=Depends(auth.get_current_user), db: Session = Depends(get_db)):
    role = crud.get_role(db, user.role_id)
    return schemas.MeResponse(user=user, role=role)
