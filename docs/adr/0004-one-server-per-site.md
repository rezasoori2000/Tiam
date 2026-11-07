# 0004 – One Tiam server per site

**Status:** accepted (2026-11-08)

## Context
A central server for several car parks would need camera streams to leave each site. The first
client is a hospital, where footage leaving the site network is sensitive.

## Decision
Each site runs its own Tiam server (detection, storage, UI). A `sites` table still exists (one
default row) so a server can later group cameras by site, but cross-site aggregation is out of scope.

## Consequences
- Video stays on the site network (apart from optional VLM calls, ADR 0001).
- Upgrades and monitoring are per server (existing `update-release.ps1` flow).
