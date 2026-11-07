# Test clips

Videos and their ground-truth YAML live in `backend/data/retail_test_clips/` (git-ignored: footage
can show people and plates). Each clip is scored with:

    cd backend
    venv\Scripts\python scripts\replay.py data\retail_test_clips\<name>.yaml

YAML format: see the docstring at the top of `backend/scripts/replay.py`. A `source_type="file"`
camera (Cameras page → "Video File (test)") plays the same files through the live system.

| Clip | What it shows | Ground truth | Source |
|---|---|---|---|
| `demo_bus.mp4` | Synthetic: empty frame 0-5 s, Ultralytics' `bus.jpg` (people + bus) 5-10 s, empty 10-15 s | exclusion 5-10 s | `replay.py --make-demo` |

Phase acceptance (spec section 14) must be measured on **real site footage** (decided 2026-11-08);
add each recorded or staged clip here with what it contains and where it came from.
