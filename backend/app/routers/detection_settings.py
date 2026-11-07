from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, camera_manager, crud, detection_engine, schemas
from ..database import get_db

router = APIRouter(
    prefix="/api/detection-settings", tags=["detection-settings"],
    dependencies=[Depends(auth.require_admin)],
)


@router.get("", response_model=schemas.DetectionSettingsOut)
def get_detection_settings(db: Session = Depends(get_db)):
    return crud.get_detection_settings(db)


@router.get("/models")
def list_detector_models():
    return detection_engine.available_models()


@router.put("", response_model=schemas.DetectionSettingsOut)
def update_detection_settings(
    data: schemas.DetectionSettingsUpdate, db: Session = Depends(get_db)
):
    settings = crud.get_detection_settings(db)
    merged_update = data.model_dump(exclude_unset=True)
    min_observations = merged_update.get(
        "confirmation_min_observations", settings.confirmation_min_observations
    )
    window_frames = merged_update.get(
        "confirmation_window_frames", settings.confirmation_window_frames
    )
    model = merged_update.get("detector_model")
    if model is not None and model not in detection_engine.available_models():
        raise HTTPException(400, f"unknown detector model {model!r}")
    if min_observations > window_frames:
        raise HTTPException(
            400,
            "confirmation_min_observations must be <= confirmation_window_frames",
        )
    settings = crud.update_detection_settings(db, settings, data)
    # These knobs are read once when a camera's VisionEngine is built (no
    # hot-reload, same as zones/calibration) -- restart every worker so the
    # change actually takes effect.
    camera_manager.restart_all(db)
    return settings
