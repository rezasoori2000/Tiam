# 0008 – Event clips are stored raw; boxes go in a JSON sidecar

**Status:** accepted (2026-11-08)

## Context
Each incident gets a ~20 s clip (10 s before, 10 s after, 5 fps). Police and insurers prefer
untouched footage as evidence, while operators want to see the detection boxes.

## Decision
Write the clip **without** drawn boxes (`data/retail_event_clips/{event_id}.mp4`) and the per-frame
track boxes/labels to `{event_id}.json` beside it. The UI draws the overlay on playback; the
evidence pack can export both the raw clip and an annotated render.

## Consequences
- Evidence stays unaltered; overlay can be restyled or corrected later.
- The frontend needs a small canvas overlay player instead of a plain `<video>`.
