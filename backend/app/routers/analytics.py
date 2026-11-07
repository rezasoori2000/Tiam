from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import analytics
from ..database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/breaches-by-day")
def breaches_by_day(days: int = 30, db: Session = Depends(get_db)):
    return analytics.breaches_by_day(db, days=days)


@router.get("/risk-by-policy")
def risk_by_policy(db: Session = Depends(get_db)):
    return analytics.risk_by_policy(db)


@router.get("/camera-leaderboard")
def camera_leaderboard(db: Session = Depends(get_db)):
    return analytics.camera_leaderboard(db)
