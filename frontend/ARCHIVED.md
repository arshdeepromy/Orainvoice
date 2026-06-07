# ⚠️ ARCHIVED — `frontend/` is no longer the active web app

**Status: ARCHIVED / FROZEN as of 2026-06-05. Do not develop here.**

The active web SPA is now **`frontend-v2/`** (the redesign). All new web
frontend work — features, bug fixes, styling, dependency bumps — must happen in
`frontend-v2/`, not in this directory.

## Why

`frontend-v2/` is the React 18+ redesign built against the OraInvoice design
system. It is the live frontend behind the local dev gateway (served under
`/new/`, with `/` redirecting there). This legacy `frontend/` was the previous
production SPA (v1.13.0 era) and is retained only for reference and for the
production deployments that have not yet cut over.

## Rules

- ❌ **No further development** in `frontend/` — no new features, no refactors.
- ❌ Do not add this folder to new specs as a build target. Specs targeting the
  web UI must target `frontend-v2/`.
- ✅ Critical production-only hotfixes for environments still serving this build
  may be applied here **only** with an explicit note in the commit and
  `docs/ISSUE_TRACKER.md`, and must be mirrored into `frontend-v2/`.
- ✅ Read-only reference (porting logic into `frontend-v2/`) is fine.

## Where things moved

| Old (`frontend/`) | New (`frontend-v2/`) |
|---|---|
| `src/pages/...` | `src/pages/...` (ported, redesigned) |
| `src/components/...` | `src/components/...` + `src/components/ui/` design system |
| Served at `/` | Served at `/new/` (root redirects to it in local dev) |

## How the new app runs in local dev

See `docker-compose.dev-v2.yml` (header comment) and
`.kiro/steering/frontend-redesign.md`. In short:

```
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  -f docker-compose.frontend-v2.yml \
  -f docker-compose.dev-v2.yml \
  up -d --remove-orphans postgres redis app mobile frontend-v2 nginx
```

Then open http://localhost/ (redirects to http://localhost/new/).
