"""Password hashing (stdlib PBKDF2, no extra dependency) and a DB-backed
bearer-token session used to gate every API route behind login."""
import datetime
import hashlib
import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import models
from .database import get_db

PBKDF2_ITERATIONS = 260_000
MIN_PASSWORD_LENGTH = 10
# The only endpoints a user who must change their password can call.
PASSWORD_CHANGE_ALLOWED_PATHS = {"/api/auth/me", "/api/auth/change-password"}


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, password_hash)


def create_session(db: Session, user: models.User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(models.UserSession(token=token, user_id=user.id, created_at=datetime.datetime.now()))
    db.commit()
    return token


def delete_session(db: Session, token: str) -> None:
    session = db.get(models.UserSession, token)
    if session is not None:
        db.delete(session)
        db.commit()


def get_user_from_token(db: Session, token: str | None) -> models.User | None:
    """Same session-token lookup `get_current_user` does, but usable outside
    a Request -- e.g. by WebSocket routes, which can't set an Authorization
    header and pass the token as a query param instead."""
    if not token:
        return None
    session = db.get(models.UserSession, token)
    if session is None:
        return None
    return db.get(models.User, session.user_id)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth_header.removeprefix("Bearer ")
    user = get_user_from_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        raise HTTPException(status_code=403, detail="password_change_required")
    return user


def require_admin(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)) -> models.User:
    role = db.get(models.Role, user.role_id)
    if role is None or not role.is_system:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
