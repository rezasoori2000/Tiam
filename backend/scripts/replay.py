"""Replay harness (spec 13): run a video through the real detection pipeline + incident dedupe and
score the incidents against a ground-truth YAML.

    python scripts/replay.py data/retail_test_clips/<name>.yaml [--realtime]
    python scripts/replay.py --make-demo        # writes demo_bus.mp4 + demo_bus.yaml, then run it

Scenario YAML (lives beside the video in data/retail_test_clips/, not in git; see docs/test_clips.md):

    video: demo_bus.mp4            # relative to the YAML file
    tolerance_s: 2                 # an incident counts if it starts within [start - tol, end + tol]
    calibration: {meters_per_pixel: 0.02}          # optional
    zones:                                          # polygons in the 960x540 frame
      - name: Whole frame
        polygon: [[0, 0], [960, 0], [960, 540], [0, 540]]
        rules: {exclusion: true, applies_to: [person]}   # any config.ZoneRules field
    ground_truth:
      - {type: exclusion, start: 5, end: 10}

Video time (frame index / fps) is used as the timestamp, so results don't depend on GPU speed.
"""
import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

FRAME_SIZE = (960, 540)


def evaluate(incidents, ground_truth, tolerance_s=2.0):
    """incidents: [(type, t)], ground_truth: [{type, start, end}].
    Returns {type: {"tp", "fp", "gt", "recalled", "precision", "recall"}}.
    An incident is a true positive if it falls inside a ground-truth interval of its type (± tolerance);
    a ground-truth interval is recalled if at least one incident falls inside it."""
    stats = defaultdict(lambda: {"tp": 0, "fp": 0, "gt": 0, "recalled": 0})
    recalled = set()
    for etype, t in incidents:
        hits = [
            i for i, g in enumerate(ground_truth)
            if g["type"] == etype and g["start"] - tolerance_s <= t <= g["end"] + tolerance_s
        ]
        stats[etype]["tp" if hits else "fp"] += 1
        recalled.update(hits)
    for i, g in enumerate(ground_truth):
        stats[g["type"]]["gt"] += 1
        stats[g["type"]]["recalled"] += int(i in recalled)
    for s in stats.values():
        found = s["tp"] + s["fp"]
        s["precision"] = s["tp"] / found if found else None
        s["recall"] = s["recalled"] / s["gt"] if s["gt"] else None
    return dict(stats)


def run(scenario_path: Path, realtime: bool = False, min_obs: int = 3, window: int = 6):
    """Returns ([(event type, video time s)], frames processed)."""
    import cv2
    import yaml

    from app.camera_manager import _IncidentTracker
    from app.config import CalibrationConfig, EngineConfig, Zone, ZoneRules
    from app.vision_engine import VisionEngine

    sc = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    zones = [
        Zone(id=str(i + 1), name=z["name"], polygon=z["polygon"], rules=ZoneRules(**z.get("rules", {})))
        for i, z in enumerate(sc.get("zones", []))
    ]
    engine = VisionEngine(EngineConfig(
        zones=zones, calibration=CalibrationConfig(**sc.get("calibration", {})), frame_size=FRAME_SIZE,
    ))
    tracker = _IncidentTracker(min_observations=min_obs, window_frames=window)
    cap = cv2.VideoCapture(str(scenario_path.parent / sc["video"]))
    if not cap.isOpened():
        raise SystemExit(f"can't open video {sc['video']!r}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    incidents, n = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = n / fps
        _, events = engine.process_frame(frame, ts=1_000_000.0 + t)  # fixed epoch offset; only differences matter
        tracker.start_frame()
        for ev in events:
            if tracker.observe(ev, 1_000_000.0 + t):
                incidents.append((ev["type"], round(t, 2)))
        tracker.prune(1_000_000.0 + t)
        n += 1
        if realtime:
            time.sleep(1 / fps)
    cap.release()
    return incidents, n


def make_demo(out_dir: Path) -> Path:
    """15 s synthetic clip: empty street 0-5 s, ultralytics' bus.jpg (people) 5-10 s, empty again."""
    import cv2
    import numpy as np
    import ultralytics

    people = cv2.resize(cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg")), FRAME_SIZE)
    empty = np.full_like(people, 90)
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out_dir / "demo_bus.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, FRAME_SIZE)
    for i in range(150):
        writer.write(people if 50 <= i < 100 else empty)
    writer.release()
    yaml_path = out_dir / "demo_bus.yaml"
    yaml_path.write_text(
        "video: demo_bus.mp4\ntolerance_s: 2\nzones:\n"
        "  - name: Whole frame\n    polygon: [[0, 0], [960, 0], [960, 540], [0, 540]]\n"
        "    rules: {exclusion: true, applies_to: [person]}\n"
        "ground_truth:\n  - {type: exclusion, start: 5, end: 10}\n",
        encoding="utf-8",
    )
    return yaml_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", nargs="?", type=Path)
    ap.add_argument("--realtime", action="store_true", help="play at the video's own speed")
    ap.add_argument("--make-demo", action="store_true", help="write the synthetic demo clip and run it")
    args = ap.parse_args()
    if args.make_demo:
        args.scenario = make_demo(BACKEND / "data" / "retail_test_clips")
    if args.scenario is None:
        ap.error("give a scenario YAML or --make-demo")

    import yaml

    sc = yaml.safe_load(args.scenario.read_text(encoding="utf-8"))
    t0 = time.time()
    incidents, frames = run(args.scenario, realtime=args.realtime)
    stats = evaluate(incidents, sc.get("ground_truth", []), sc.get("tolerance_s", 2.0))
    print(f"{args.scenario.name}: {frames} frames in {time.time() - t0:.1f}s, {len(incidents)} incidents")
    print(f"{'event type':<22}{'incidents':>10}{'TP':>5}{'FP':>5}{'GT':>5}{'precision':>11}{'recall':>8}")
    fmt = lambda v: "-" if v is None else f"{v:.0%}"  # noqa: E731
    for etype, s in sorted(stats.items()):
        print(f"{etype:<22}{s['tp'] + s['fp']:>10}{s['tp']:>5}{s['fp']:>5}{s['gt']:>5}"
              f"{fmt(s['precision']):>11}{fmt(s['recall']):>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
