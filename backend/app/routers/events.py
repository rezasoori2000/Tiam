from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import camera_manager, clips, crud, email_service, schemas
from ..database import get_db

router = APIRouter(prefix="/api/events", tags=["events"])


def delete_events_and_snapshots(db: Session, ids: list[int]) -> int:
    """Dismissing an event deletes it outright -- row, comments and snapshot
    JPEG -- so dismissed noise doesn't pile up in the DB or on disk."""
    deleted = crud.delete_events(db, ids)
    for event_id in deleted:
        camera_manager.event_snapshot_path(event_id).unlink(missing_ok=True)
        camera_manager.event_snapshot_path(event_id, zones=False).unlink(missing_ok=True)
        clips.delete_clip(event_id)
    return len(deleted)


@router.get("", response_model=list[schemas.EventOut])
def list_events(
    status: Optional[schemas.EventStatus] = None,
    camera_id: Optional[int] = None,
    min_risk: Optional[int] = Query(None, ge=1, le=10),
    max_risk: Optional[int] = Query(None, ge=1, le=10),
    limit: int = 200,
    offset: int = 0,
    verdict: Optional[str] = Query(None, pattern="^(all|confirmed|rejected|uncertain|unverified|none)$"),
    db: Session = Depends(get_db),
):
    return crud.get_events(
        db, status=status, camera_id=camera_id, min_risk=min_risk, max_risk=max_risk,
        limit=limit, offset=offset, verdict=verdict,
    )


@router.post("/bulk-status")
def bulk_update_events(update: schemas.EventBulkUpdate, db: Session = Depends(get_db)):
    if update.status == "dismissed":
        return {"updated": delete_events_and_snapshots(db, update.ids)}
    updated = crud.bulk_update_event_status(db, update.ids, update.status)
    return {"updated": updated}


@router.get("/{event_id}", response_model=schemas.EventOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = crud.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.patch("/{event_id}", response_model=schemas.EventOut)
def update_event(event_id: int, update: schemas.EventUpdate, db: Session = Depends(get_db)):
    event = crud.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if update.status == "dismissed":
        out = schemas.EventOut.model_validate(event)
        delete_events_and_snapshots(db, [event_id])
        return out
    return crud.update_event(db, event, update.status, update.risk_score)


@router.get("/{event_id}/snapshot")
def get_event_snapshot(event_id: int, zones: bool = True, db: Session = Depends(get_db)):
    event = crud.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    path = camera_manager.event_snapshot_path(event_id, zones)
    if not path.exists():
        path = camera_manager.event_snapshot_path(event_id)  # older event: no zone-less copy
    if not event.has_snapshot or not path.exists():
        raise HTTPException(status_code=404, detail="No snapshot recorded for this event")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{event_id}/clip")
def get_event_clip(event_id: int, db: Session = Depends(get_db)):
    """Raw H.264 clip (ADR 0008); boxes come from /clip-overlay."""
    event = crud.get_event(db, event_id)
    path = clips.clip_path(event_id)
    if event is None or not event.has_clip or not path.exists():
        raise HTTPException(status_code=404, detail="No clip recorded for this event")
    return FileResponse(path, media_type="video/mp4")


@router.get("/{event_id}/clip-overlay")
def get_event_clip_overlay(event_id: int, db: Session = Depends(get_db)):
    event = crud.get_event(db, event_id)
    path = clips.overlay_path(event_id)
    if event is None or not event.has_clip or not path.exists():
        raise HTTPException(status_code=404, detail="No clip recorded for this event")
    return FileResponse(path, media_type="application/json")


@router.post("/{event_id}/email", status_code=204)
def email_event_snapshot(
    event_id: int, body: schemas.EventEmailRequest, db: Session = Depends(get_db)
):
    event = crud.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    path = camera_manager.event_snapshot_path(event_id)
    if not event.has_snapshot or not path.exists():
        raise HTTPException(status_code=404, detail="No snapshot recorded for this event")
    try:
        email_service.send_incident_email(
            to_address=body.to_address,
            subject=body.subject,
            body=body.body,
            attachment_bytes=path.read_bytes(),
            attachment_name=f"incident-{event_id}.jpg",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send email: {exc}") from exc


@router.get("/{event_id}/comments", response_model=list[schemas.EventCommentOut])
def list_comments(event_id: int, db: Session = Depends(get_db)):
    event = crud.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return crud.get_comments(db, event_id)


@router.post("/{event_id}/comments", response_model=schemas.EventCommentOut, status_code=201)
def add_comment(event_id: int, comment_in: schemas.EventCommentCreate, db: Session = Depends(get_db)):
    event = crud.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return crud.create_comment(db, event_id, comment_in.text)
