from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crud, incident_search, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("/search", response_model=list[schemas.EventOut])
def search_incidents(q: str, limit: int = 100, db: Session = Depends(get_db)):
    """Phase 1 incident search: parses `q` into rule type / camera / date
    range / speed-or-distance threshold (see incident_search.py) and filters
    the existing Event table accordingly -- no LLM, no vector DB."""
    cameras = crud.get_cameras(db)
    filters = incident_search.parse_query(q, cameras)

    stmt = select(models.Event).where(models.Event.status != "dismissed")
    if filters.policy_prefix:
        stmt = stmt.where(models.Event.policy_type.like(f"{filters.policy_prefix}%"))
    if filters.camera_id is not None:
        stmt = stmt.where(models.Event.camera_id == filters.camera_id)
    if filters.date_from is not None:
        stmt = stmt.where(models.Event.timestamp >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(models.Event.timestamp <= filters.date_to)
    stmt = stmt.order_by(models.Event.timestamp.desc())

    # speed_kmh lives inside raw_payload (JSON), not a real column -- cheaper
    # to filter in Python over a bounded fetch than to fight SQL Server's JSON querying.
    needs_payload_filter = filters.min_speed_kmh is not None
    rows = list(db.scalars(stmt.limit(1000 if needs_payload_filter else limit)))

    if filters.min_speed_kmh is not None:
        rows = [r for r in rows if (r.raw_payload.get("speed_kmh") or 0) >= filters.min_speed_kmh]

    return rows[:limit]
