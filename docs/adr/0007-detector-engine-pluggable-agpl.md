# 0007 – Keep Ultralytics for now; make the detector engine pluggable

**Status:** accepted (2026-11-08)

## Context
Detection, tracking input and the planned pose model use `ultralytics` (YOLOv8 / YOLO26), whose
code and weights are AGPL-3.0. Selling or installing Tiam at a client site would require either
releasing Tiam's source under AGPL or buying an Ultralytics commercial licence. Replacing the
engine (Apache/MIT models such as RT-DETR, D-FINE, YOLOX, RTMPose) is real engineering work and
needs accuracy re-validation.

## Decision
- Keep Ultralytics during development; **decide licence vs. replacement before the first sale**
  (with legal advice – this ADR is not legal advice).
- In phase 1, put the detector (and later pose) behind a small engine interface selected by the
  Detection Settings `detector_model` field, so swapping to a non-AGPL engine does not touch the
  rest of the pipeline.

## Consequences
- No licence cost now; a known commercial blocker stays open until the first sale.
- The plate detector choice (ADR 0002) avoids adding more AGPL weights.
