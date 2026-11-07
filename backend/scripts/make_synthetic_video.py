"""Generates a short synthetic clip with a moving person-like blob and a
COCO-real reference frame, purely so the pipeline can be smoke-tested before
a real test_warehouse.mp4 is available. This does NOT validate detection
accuracy -- only that the code path runs end-to-end without exceptions.
"""
from pathlib import Path

import cv2
import numpy as np

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "synthetic_smoke.mp4"


def main() -> None:
    w, h = 640, 640
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(OUT_PATH), fourcc, 20.0, (w, h))

    for i in range(60):
        frame = np.full((h, w, 3), (60, 60, 60), dtype=np.uint8)
        x = 50 + i * 8
        cv2.rectangle(frame, (x, 300), (x + 40, 420), (0, 140, 255), -1)  # torso
        cv2.circle(frame, (x + 20, 280), 18, (210, 190, 170), -1)  # head
        writer.write(frame)

    writer.release()
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
