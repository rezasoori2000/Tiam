# 0005 – Privacy baseline and retention defaults

**Status:** accepted (2026-11-08)

## Decision
- Build to the **NZ Privacy Act 2020 and the Biometric Processing Privacy Code 2025**: no face
  recognition; no emotion, intent, health, age, gender or ethnicity inference; re-identification
  only by short-lived clothing/appearance embeddings.
- Whether a hospital's car-park footage also falls under the Health Information Privacy Code is
  **for the client's legal advisers to confirm before go-live**; Tiam does not decide it.
- Default retention (editable in Settings; incidents on legal hold are never deleted):
  snapshots/clips 30 days, plate reads 90 days, VLM-rejected incidents 7 days, embeddings
  30 days, audit log 2 years.
- Audio, if enabled, is classified only and never stored.
