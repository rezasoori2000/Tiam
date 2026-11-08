from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, heatmap
from ..database import get_db

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])

# Usage Heatmap: object classes the dropdown offers. Keys must match the
# class_name a track is stored under -- see vision_engine.VisionEngine
# (COCO "person"/"truck" names).
USAGE_METRICS = {
    "person": "Human",
    "car": "Car",
    "truck": "Truck",
    heatmap.USAGE_ALL: "Show all",
}

# Violations Heatmap: rule-violation types the dropdown offers. Keys must
# match vision_engine._apply_rules's event "type" values.
VIOLATION_METRICS = {
    "exclusion": "Exclusion Zone Breach",
    "speeding": "Speed Limit Exceeded",
    "failed_to_stop": "Failed to Stop",
    "car_prowling": "Car Prowling",
}


@router.get("/usage-options")
def usage_options():
    return [{"value": k, "label": v} for k, v in USAGE_METRICS.items()]


@router.get("/violation-options")
def violation_options():
    return [{"value": k, "label": v} for k, v in VIOLATION_METRICS.items()]


def _grid_response(db: Session, camera_id: int, metric: str, start_date: str, end_date: str) -> dict:
    camera = crud.get_camera(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    grid = crud.get_heatmap_grid(db, camera_id, metric, start_date, end_date)
    max_count = max((count for row in grid for count in row), default=0)
    return {"rows": heatmap.GRID_ROWS, "cols": heatmap.GRID_COLS, "grid": grid, "max_count": max_count}


@router.get("/usage")
def usage_heatmap(
    camera_id: int, class_name: str, start_date: str, end_date: str,
    db: Session = Depends(get_db),
):
    if class_name not in USAGE_METRICS:
        raise HTTPException(status_code=400, detail=f"Unknown class_name '{class_name}'")
    return _grid_response(db, camera_id, class_name, start_date, end_date)


@router.get("/violations")
def violations_heatmap(
    camera_id: int, violation_type: str, start_date: str, end_date: str,
    db: Session = Depends(get_db),
):
    if violation_type not in VIOLATION_METRICS:
        raise HTTPException(status_code=400, detail=f"Unknown violation_type '{violation_type}'")
    return _grid_response(db, camera_id, heatmap.violation_metric(violation_type), start_date, end_date)
