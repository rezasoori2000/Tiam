"""Shared grid definition for 'hot zone' heatmaps: where a class of object
(usage) or a type of rule violation (violations) has been seen over time,
per camera. Rather than storing every raw per-frame position (unbounded
growth), each camera worker buckets positions into this coarse grid and
periodically flushes accumulated counts to the `heatmap_cells` table --
see camera_manager._CameraWorker._flush_heatmap.

Both the writer (camera_manager) and the reader (routers/heatmap.py) import
these constants/helpers so the grid mapping can never drift between them.
"""
GRID_COLS = 40
GRID_ROWS = 25

VIOLATION_METRIC_PREFIX = "violation:"

# Usage Heatmap pseudo-class: every tracked object class summed together
# (i.e. every metric that isn't a "violation:..." one). Never stored itself.
USAGE_ALL = "all"


def grid_cell(x: float, y: float, frame_w: int, frame_h: int) -> tuple[int, int]:
    """Maps a pixel position in a frame_w x frame_h frame to a (row, col)
    in the fixed GRID_ROWS x GRID_COLS grid."""
    col = min(max(int(x / frame_w * GRID_COLS), 0), GRID_COLS - 1)
    row = min(max(int(y / frame_h * GRID_ROWS), 0), GRID_ROWS - 1)
    return row, col


def violation_metric(event_type: str) -> str:
    return f"{VIOLATION_METRIC_PREFIX}{event_type}"
