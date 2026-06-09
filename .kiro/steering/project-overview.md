---
inclusion: always
---

# OraInvoice — Project Overview

OraInvoice is a multi-tenant SaaS invoicing and business management platform built for trade businesses (automotive, electrical, plumbing, construction, etc.). It supports multi-org, multi-branch, role-based access, and trade-family gating.

## Tech Stack

- Backend: Python 3.11, FastAPI, SQLAlchemy (async), Alembic migrations, PostgreSQL 16 with RLS
- Frontend: React 18+, TypeScript, Vite, Tailwind CSS, Headless UI. The active web app is **`frontend-v2/`** (the redesign). `frontend/` is **archived** (see `frontend/ARCHIVED.md`) — no further development.
- Infrastructure: Docker Compose, Nginx reverse proxy, Redis 7 (caching/rate limiting)
- Auth: JWT + Firebase tokens, MFA (TOTP, SMS, Passkeys, backup codes)
- Payments: Stripe integration (subscriptions, payment methods)
- SMS: Connexus SMS provider integration
- Accounting: Xero API integration with webhooks and auto-sync
- PDF: WeasyPrint for invoice/report generation

## Repository Structure

- `app/` — FastAPI backend (modules pattern: auth, admin, billing, customers, invoices, inventory, etc.)
- `app/core/` — Database, encryption, branch context, module registry
- `app/modules/` — Feature modules (each has router.py, service.py, models.py, schemas.py)
- `frontend-v2/` — **ACTIVE** React SPA redesign (Vite, pages/, components/, contexts/, hooks/, api/). Served live in local dev under `/new/` (root redirects there) via `docker-compose.dev-v2.yml` + `nginx/nginx.dev-v2.conf`.
- `frontend/` — **ARCHIVED** legacy React SPA (v1.13.0 era). Reference only; do not develop here (`frontend/ARCHIVED.md`).
- `alembic/versions/` — Database migrations (currently at revision 0182)
- `tests/` — pytest tests, property-based tests (Hypothesis), e2e tests (Playwright)
- `scripts/` — Utility scripts (seeding, deployment, checks)
- `docs/` — Issue tracker, security audits, implementation plans
- `.kiro/specs/` — Feature specifications (requirements, design, tasks)
- `.kiro/steering/` — Steering rules for code quality and patterns

## Deployment Environments

| Environment | Location | Compose Files | Project Name | Port | DB Port | HA Role |
|---|---|---|---|---|---|---|
| DEV (primary) | Local Ubuntu | docker-compose.yml + docker-compose.dev.yml | invoicing | 80 | 5434 | Primary (paired with Dev Standby on Pi) |
| Prod Standby | Local Ubuntu | docker-compose.standby-prod.yml | invoicing-standby-prod | 8082 | 5435 | Standby (paired with PROD on Pi) |
| PROD (primary) | Raspberry Pi (192.168.1.90) | docker-compose.yml + docker-compose.pi.yml | invoicing | 8999 | 5432 | Primary (paired with Prod Standby on local) |
| Dev Standby | Raspberry Pi (192.168.1.90) | docker-compose.ha-standby.yml | invoicing-standby | 8081 | 5433 | Standby (paired with DEV on local) |

## Deployment Process (Pi Prod)

1. Make changes locally, commit and push to GitHub (arshdeepromy/Orainvoice, main branch)
2. Pull code on Pi via git: `ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && git pull origin main"`
3. Backend changes: `ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app"`
4. Frontend-v2 changes (served via nginx-v2 on port 8998 — the ACTIVE frontend behind Cloudflare):
   ```
   ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml -f docker-compose.pi-v2.yml up -d --build --force-recreate frontend-v2-build nginx-v2"
   ```
5. After app rebuild, restart nginx to clear stale upstream connections:
   ```
   ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml restart nginx"
   ```
6. The docker entrypoint runs `alembic upgrade head` automatically on app start
7. The legacy `frontend/` (old SPA) is ARCHIVED and stopped — do NOT start `invoicing-frontend-1`
8. Pi uses git for code sync (GitHub remote). Pi-specific files (.env.pi, docker-compose.pi.yml) are committed and preserved.

### Full Pi Prod Redeploy Command (backend + frontend-v2):
```bash
ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && \
  git pull origin main && \
  docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app && \
  docker compose -f docker-compose.yml -f docker-compose.pi.yml -f docker-compose.pi-v2.yml up -d --build --force-recreate frontend-v2-build nginx-v2 && \
  docker compose -f docker-compose.yml -f docker-compose.pi.yml restart nginx"
```

### Important Notes:
- `one.oraflows.co.nz` routes through Cloudflare Tunnel → `localhost:8998` (nginx-v2, frontend-v2 build)
- The old `invoicing-frontend-1` container is STOPPED — do not restart it
- After app rebuild, always restart nginx to prevent 502/504 from stale connections
- Pi Dev Standby uses `docker-compose.ha-standby.yml` (project: invoicing-standby, port 8081)

## Key Patterns & Rules

- All API responses wrap arrays in objects: `{ items: [...], total: N }` — never bare arrays
- Frontend must use `?.` and `?? []` / `?? 0` on all API data (see #[[file:.kiro/steering/safe-api-consumption.md]])
- After `db.flush()`, always `await db.refresh(obj)` before returning ORM objects for Pydantic serialization (prevents MissingGreenlet)
- Trade families gate features per business type (see #[[file:.kiro/steering/trade-family-gating-for-new-features.md]])
- All bugs are logged in #[[file:docs/ISSUE_TRACKER.md]] (currently up to ISSUE-106)
- Database migrations must be idempotent where possible (use IF NOT EXISTS for CREATE TABLE)
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in services
- Integration API keys (Stripe, CarJam, Xero, SMS) are stored encrypted in the DB, configured via Global Admin GUI — never read from `.env` for API calls (see #[[file:.kiro/steering/integration-credentials-architecture.md]])

## Current State (as of 2026-05-26)

- Alembic: revision 0194 (head) on Dev, Prod Standby (local), Pi Dev Standby. Pi PROD primary still at 0192 pending the next maintenance window.
- 132+ tables in the database
- 106 issues tracked and resolved (ISSUE-133 added 2026-05-26 for QR partial payment regression-fixes)
- Pi PROD has 7 orgs, 611 customers, 72 invoices, 48 payments, 148 line items, 9 users (real production data — handle with care)
- HA replication configured between Pi primary and local standby nodes
- Xero accounting integration with webhooks deployed
- Branch management, claims, scheduling, stock transfers all implemented
- Customer creation only requires First Name (all other fields optional per user feedback)
- COF (Certificate of Fitness) expiry support deployed alongside WOF
- Kiosk vehicle check-in multi-step flow deployed (rego → vehicle summary → customer details)
- QR partial payment flow shipped (May 2026 cut-over commit `9403258`)
- App version: 1.13.0
