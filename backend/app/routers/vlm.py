"""AI verification settings (admin). The API key is write-only: responses carry api_key_set + last 4."""
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import auth, models, schemas, secrets_store
from ..database import get_db
from ..vlm import prompts
from ..vlm.service import DEFAULT_MODES, EVENT_TYPE_LABELS, Snapshot, get_settings, is_local_url, service

router = APIRouter(prefix="/api/vlm", tags=["ai-verification"], dependencies=[Depends(auth.require_admin)])


def _out(row: models.VlmSettings) -> schemas.VlmSettingsOut:
    return schemas.VlmSettingsOut(
        enabled=row.enabled, provider=row.provider, base_url=row.base_url, model=row.model,
        api_key_set=bool(row.api_key_encrypted), api_key_last4=row.api_key_last4 or None,
        local_only=row.local_only, timeout_s=row.timeout_s, max_concurrent=row.max_concurrent,
        max_calls_per_hour=row.max_calls_per_hour, gate_timeout_s=row.gate_timeout_s,
        min_confidence=row.min_confidence, rejected_retention_days=row.rejected_retention_days,
        secret_key_configured=secrets_store.available(),
    )


@router.get("/settings", response_model=schemas.VlmSettingsOut)
def read_settings(db: Session = Depends(get_db)):
    return _out(get_settings(db))


@router.put("/settings", response_model=schemas.VlmSettingsOut)
def update_settings(data: schemas.VlmSettingsUpdate, db: Session = Depends(get_db)):
    row = get_settings(db)
    changes = data.model_dump(exclude_unset=True)
    api_key = (changes.pop("api_key", None) or "").strip()
    for field, value in changes.items():
        setattr(row, field, value)
    if api_key:
        if not secrets_store.available():
            raise HTTPException(400, "TIAM_SECRET_KEY is not set on the server, so API keys can't be stored safely")
        row.api_key_encrypted = secrets_store.encrypt(api_key)
        row.api_key_last4 = secrets_store.last4(api_key)
    if row.local_only and not is_local_url(row.base_url):
        raise HTTPException(400, "Local only is on: set a base URL on this network (e.g. http://localhost:11434/v1 for Ollama)")
    if row.enabled and row.provider in ("anthropic", "google") and not row.api_key_encrypted:
        raise HTTPException(400, "This provider needs an API key before AI verification can be enabled")
    db.commit()
    service.reload()
    return _out(row)


@router.delete("/settings/api-key", response_model=schemas.VlmSettingsOut)
def remove_api_key(db: Session = Depends(get_db)):
    row = get_settings(db)
    row.api_key_encrypted = None
    row.api_key_last4 = None
    if row.provider in ("anthropic", "google"):
        row.enabled = False  # can't verify without a key
    db.commit()
    service.reload()
    return _out(row)


@router.get("/event-types", response_model=list[schemas.VlmEventTypeOut])
def list_event_types(db: Session = Depends(get_db)):
    saved = {r.event_type: r for r in db.scalars(select(models.VlmEventTypeSetting))}
    out = []
    for et in sorted(set(DEFAULT_MODES) | set(saved)):
        row = saved.get(et)
        out.append(schemas.VlmEventTypeOut(
            event_type=et, label=EVENT_TYPE_LABELS.get(et, et.replace("_", " ").title()),
            mode=row.mode if row else DEFAULT_MODES.get(et, "annotate"),
            prompt_template=(row.prompt_template if row and row.prompt_template else prompts.default_template(et)),
            is_default_prompt=not (row and row.prompt_template),
        ))
    return out


@router.put("/event-types", response_model=list[schemas.VlmEventTypeOut])
def update_event_types(items: list[schemas.VlmEventTypeUpdate], db: Session = Depends(get_db)):
    saved = {r.event_type: r for r in db.scalars(select(models.VlmEventTypeSetting))}
    for item in items:
        template = (item.prompt_template or "").strip() or None
        if template == prompts.default_template(item.event_type).strip():
            template = None  # unchanged default: keep following future default improvements
        row = saved.get(item.event_type)
        if row is None:
            row = models.VlmEventTypeSetting(event_type=item.event_type, mode=item.mode)
            db.add(row)
        row.mode, row.prompt_template = item.mode, template
    db.commit()
    service.reload()
    return list_event_types(db)


@router.get("/usage")
def usage(db: Session = Depends(get_db)):
    since = (datetime.date.today() - datetime.timedelta(days=6)).isoformat()
    rows = list(db.scalars(select(models.VlmUsage).where(models.VlmUsage.day >= since).order_by(models.VlmUsage.day)))
    days = [{
        "day": r.day, "calls": r.calls, "errors": r.errors, "skipped": r.skipped,
        "avg_latency_ms": round(r.total_latency_ms / max(1, r.calls - r.errors)),
        "confirmed": r.confirmed, "rejected": r.rejected, "uncertain": r.uncertain,
    } for r in rows]
    return {"days": days, "queue": service.pending, "today": next((d for d in days if d["day"] == datetime.date.today().isoformat()), None)}


@router.post("/test")
async def test_connection():
    """One real call with a built-in image, using the SAVED settings (save first)."""
    return await run_in_threadpool(service.test)
