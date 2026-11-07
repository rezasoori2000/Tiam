# 0002 – Plate reading uses Tiam's own pipeline on ordinary cameras, and is optional

**Status:** accepted (2026-11-08)

## Context
The first site has no ANPR cameras. Dedicated ANPR cameras read plates far more reliably (IR,
fast shutter, on-camera OCR), but none are available.

## Decision
- Build the **built-in ANPR pipeline first** (spec F5 option B): plate detector on vehicle crops →
  OCR → NZ plate format check and OCR-confusion fixes → vote across frames of one track.
- Plate reading is **optional per camera** (a camera setting, off by default) and the whole
  feature can be switched off; every other feature must work without plates (vehicle sessions fall
  back to colour/type/embedding signatures).
- Ingesting plate events from ANPR cameras (spec F5 option A) is deferred until a site has such
  cameras.

## Models (grilling round 3)
No usable NZ-university plate model or dataset exists (only a 2013 Waikato thesis and a 2014
Auckland report, no weights or data). Start with:
- OCR: `fast-plate-ocr` global model (MIT) – NZ coverage unverified, test on site footage;
- detector: `open-image-models` YOLOv9 plate detector (code MIT, **weights licence unknown – ask the
  author before commercial use**; otherwise train our own on CC BY 4.0 / public-domain plate sets);
- save every plate crop read on site (90-day retention) to fine-tune on NZ plates later.
Avoid non-commercial datasets (GlobalPlates, TrainingData: CC BY-NC-ND).

## Consequences
- Accuracy depends on camera placement (plate ≥ ~130 px wide, ≤ 30° off-axis); most existing
  cameras will only read plates at entry/exit ramps.
- Needs a plate detector and OCR model suited to NZ plates, and GPU time per vehicle.
