"""Stage 2 end-to-end test: seed zones/calibration via the CRUD layer (as the
API would), then have VisionEngine load that config with refresh_from_db()
and run it against the real test_warehouse.mp4.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crud, schemas
from app.config import CalibrationConfig, EngineConfig
from app.database import Base, SessionLocal, engine as db_engine
from app.vision_engine import VisionEngine

BASE_DIR = Path(__file__).resolve().parent.parent
VIDEO_PATH = BASE_DIR / "data" / "test_warehouse.mp4"
OUTPUT_PATH = BASE_DIR / "output" / "stage2_output.mp4"


def seed_db(db) -> None:
    for existing in crud.get_zones(db):
        crud.delete_zone(db, existing)
    for existing in crud.get_calibrations(db):
        crud.delete_calibration(db, existing)

    crud.create_zone(db, schemas.ZoneCreate(
        name="Pallet Rack Exclusion",
        polygon_points=[[806, 108], [936, 108], [936, 213], [806, 213]],
        rule_exclusion=True,
    ))

    cal = crud.create_calibration(db, schemas.CalibrationCreate(
        name="floor-reference-line",
        # 130px spans an assumed 2m reference mark on the warehouse floor.
        line_points=[[400, 500], [530, 500]],
        real_world_meters=2.0,
    ))
    crud.activate_calibration(db, cal)


def main() -> None:
    Base.metadata.create_all(bind=db_engine)
    db = SessionLocal()
    seed_db(db)

    config = EngineConfig(
        zones=[],  # will be populated by refresh_from_db
        calibration=CalibrationConfig(),
        detector_model_path="yolov8s.pt",
        detection_conf=0.2,
        device="cuda",
        frame_size=(960, 540),
    )
    engine = VisionEngine(config)
    engine.refresh_from_db(db)

    print(f"Loaded {len(engine.config.zones)} zones from DB:")
    for z in engine.config.zones:
        print(f"  - {z.name} (id={z.id}) rules={z.rules}")
    print(f"Calibration: meters_per_pixel={engine.config.calibration.meters_per_pixel:.5f}")

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    frame_count = 0
    event_count = 0
    for _, events in engine.run_on_video(str(VIDEO_PATH), output_path=str(OUTPUT_PATH)):
        frame_count += 1
        for ev in events:
            event_count += 1
            print(f"  [frame {frame_count}] {ev}")

    print(f"\nProcessed {frame_count} frames, {event_count} alert events.")
    print(f"Output written to {OUTPUT_PATH}")
    db.close()


if __name__ == "__main__":
    main()
