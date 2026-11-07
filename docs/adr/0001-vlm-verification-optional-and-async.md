# 0001 – AI (VLM) verification is optional, asynchronous and provider-pluggable

**Status:** accepted (2026-11-08)

## Context
Detectors produce false alarms (people at their own car, cleaners, staff). A vision-language model
can look at key frames and confirm or reject an incident, but it is slow (seconds), may be
unavailable, costs money per call, and sends images to a third party when cloud-hosted.

## Decision
- Verification is **off by default**; every feature must work without it.
- It never runs on a camera thread: incidents go to a queue, a background worker calls the VLM.
- Per event type: `off`, `annotate` (alert now, add verdict later) or `gate` (hold the alert until
  the verdict, max ~8 s). On timeout, error or budget cap the alert goes out as "unverified" – a
  real alert is never lost because the VLM is down.
- Providers behind one interface: `anthropic`, `openai_compatible` (OpenAI, Azure, local vLLM /
  Ollama / NIM), `google`. **Development and testing use Anthropic (Claude)**, because the dev RTX
  3050 can't host a VLM.
- API keys are encrypted at rest (Fernet, key from env var `TIAM_SECRET_KEY`, no fallback) and never
  returned by the API.

- **Cloud or local is an admin setting, not a code change**: the AI Verification page switches
  between a cloud provider and a local OpenAI-compatible server (vLLM/Ollama on a site GPU), and
  "Local only" refuses any non-LAN base URL. **Cloud (Claude) is used for now**; the hospital's
  production choice can be made later without code changes.

## Consequences
- Extra moving parts (queue, worker, usage counters) but no coupling to a single vendor.
