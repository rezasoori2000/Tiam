import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "replay", Path(__file__).resolve().parent.parent / "scripts" / "replay.py"
)
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_precision_and_recall():
    gt = [{"type": "loitering", "start": 10, "end": 20}, {"type": "loitering", "start": 50, "end": 60}]
    stats = replay.evaluate([("loitering", 12), ("loitering", 21.5), ("loitering", 35)], gt, tolerance_s=2)
    s = stats["loitering"]
    assert (s["tp"], s["fp"], s["recalled"], s["gt"]) == (2, 1, 1, 2)
    assert s["recall"] == 0.5


def test_type_must_match():
    stats = replay.evaluate([("speeding", 12)], [{"type": "exclusion", "start": 10, "end": 20}])
    assert stats["speeding"]["fp"] == 1 and stats["exclusion"]["recall"] == 0
