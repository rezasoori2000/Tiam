# 0006 – Fix the inherited security issues on `retail-parking` in phase 1

**Status:** accepted (2026-11-08)

## Context
Inherited from the factory code: a hard-coded fallback Azure Communication Services key in
`settings.py`, and a seeded default admin password in `crud.seed_default_admin`.

## Decision
On the `retail-parking` branch only (never `main`), in phase 1:
- the Azure connection string comes only from an environment variable, with no default;
- the seeded admin gets a **random one-time password** (printed once to the server log; no password
  in source) and must change it at first login; the backend refuses every other call until then.
The user rotates the exposed Azure key in the Azure portal, because it remains in git history.

## Consequences
The factory system on `main` keeps both issues until its owner fixes them separately.
