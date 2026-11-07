"""Stage 1 standalone smoke test for VisionEngine.

Usage:
    python scripts/test_vision_engine.py                # auto-picks a source
    python scripts/test_vision_engine.py --source webcam
    python scripts/test_vision_engine.py --source data/test_warehouse.mp4
    python scripts/test_vision_engine.py --display       # show a live window
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import CalibrationConfig, EngineConfig, Zone, ZoneRules
from app.vision_engine import VisionEngine

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VIDEO = BASE_DIR / "data" / "test_warehouse.mp4"
SYNTHETIC_VIDEO = BASE_DIR / "data" / "synthetic_smoke.mp4"
OUTPUT_PATH = BASE_DIR / "output" / "annotated_output.mp4"


# test_warehouse.mp4 is native 1920x1080 (16:9). We resize to 960x540 instead
# of a hard 640x640 square to avoid distorting the aspect ratio -- zone
# polygons below are defined in this 960x540 space.
FRAME_SIZE = (960, 540)

# Estimated from the user-drawn hazard-zone screenshot (red box over the
# right-hand pallet racks, roughly x:84-97%, y:20-40% of frame) -- approximate
# until confirmed against the annotated output.
PALLET_RACK_ZONE = [[806, 108], [936, 108], [936, 213], [806, 213]]


def build_config() -> EngineConfig:
    exclusion_zone = Zone(
        id="pallet_rack",
        name="Pallet Rack Exclusion",
        polygon=PALLET_RACK_ZONE,
        rules=ZoneRules(exclusion=True, applies_to=["person"]),
        color_bgr=(0, 0, 255),
    )
    speed_zone = Zone(
        id="speed_lane",
        name="Speed Lane (10km/h limit)",
        polygon=[[0, 0], [FRAME_SIZE[0], 0], [FRAME_SIZE[0], FRAME_SIZE[1]], [0, FRAME_SIZE[1]]],
        rules=ZoneRules(speed_limit_kmh=10.0, applies_to=["vehicle", "person"]),
        color_bgr=(0, 200, 255),
    )
    return EngineConfig(
        zones=[exclusion_zone, speed_zone],
        calibration=CalibrationConfig(meters_per_pixel=0.02),
        detector_model_path="yolov8s.pt",
        device="cuda",
        frame_size=FRAME_SIZE,
    )


def pick_source(requested: str):
    if requested == "webcam":
        return 0
    if requested:
        return requested
    if DEFAULT_VIDEO.exists():
        return str(DEFAULT_VIDEO)
    print(
        f"No {DEFAULT_VIDEO.name} found in data/. Generating a synthetic smoke-test "
        "clip instead (validates the pipeline runs, not detection accuracy)."
    )
    from make_synthetic_video import main as make_synthetic  # noqa: E402
    make_synthetic()
    return str(SYNTHETIC_VIDEO)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="")
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0, help="0 = no limit")
    parser.add_argument(
        "--snapshot-sec", type=float, default=None,
        help="save an annotated snapshot .jpg near this timestamp (seconds)",
    )
    args = parser.parse_args()

    config = build_config()
    print(f"Device: {config.device}")

    engine = VisionEngine(config)
    source = pick_source(args.source)
    print(f"Source: {source}")

    OUTPUT_PATH.parent.mkdir(exist_ok=True)

    import cv2
    source_fps = 20.0
    if isinstance(source, str):
        probe = cv2.VideoCapture(source)
        source_fps = probe.get(cv2.CAP_PROP_FPS) or 20.0
        probe.release()
    snapshot_frame = (
        round(args.snapshot_sec * source_fps) if args.snapshot_sec is not None else None
    )

    frame_count = 0
    event_count = 0
    start = time.time()
    for annotated, events in engine.run_on_video(
        source, display=args.display, output_path=str(OUTPUT_PATH)
    ):
        frame_count += 1
        for ev in events:
            event_count += 1
            print(f"  [frame {frame_count}] {ev}")
        if snapshot_frame is not None and frame_count == snapshot_frame:
            snap_path = OUTPUT_PATH.parent / f"snapshot_{args.snapshot_sec:.0f}s.jpg"
            cv2.imwrite(str(snap_path), annotated)
            print(f"  Saved snapshot near t={args.snapshot_sec}s -> {snap_path}")
        if args.max_frames and frame_count >= args.max_frames:
            break

    elapsed = time.time() - start
    fps = frame_count / elapsed if elapsed > 0 else 0.0
    print(
        f"\nProcessed {frame_count} frames in {elapsed:.1f}s ({fps:.1f} fps), "
        f"{event_count} alert events. Output written to {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
