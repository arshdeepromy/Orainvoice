---
inclusion: always
---

# OraInvoice — Project Overview

OraInvoice is a multi-tenant SaaS invoicing and business management platform built for trade businesses (automotive, electrical, plumbing, construction, etc.). It supports multi-org, multi-branch, role-based access, and trade-family gating.

## Tech Stack

- Backend: Python 3.11, FastAPI, SQLAlchemy (async), Alembic migrations, PostgreSQL 16 with RLS
- Frontend: React 18, TypeScript, Vite 6, Tailwind CSS, Headless UI
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
- `frontend/` — React SPA (Vite, pages/, components/, contexts/, hooks/, api/)
- `alembic/versions/` — Database migrations (currently at revision 0139)
- `tests/` — pytest tests, property-based tests (Hypothesis), e2e tests (Playwright)
- `scripts/` — Utility scripts (seeding, deployment, checks)
- `docs/` — Issue tracker, security audits, implementation plans
- `.kiro/specs/` — Feature specifications (requirements, design, tasks)
- `.kiro/steering/` — Steering rules for code quality and patterns

## Deployment Environments

| Environment | Location | Compose Files | Port | DB Port |
|---|---|---|---|---|
| Dev (local) | Windows desktop | docker-compose.yml + docker-compose.dev.yml | 80 | 5434 |
| HA Standby (local) | Windows desktop | docker-compose.ha-standby.yml (project: invoicing-standby) | 8081 | 5433 |
| Standby Prod (local) | Windows desktop | docker-compose.standby-prod.yml (project: invoicing-standby-prod) | 8082 | 5435 |
| Production | Raspberry Pi 5 (192.168.1.90, user: nerdy) | docker-compose.yml + docker-compose.pi.yml (project: invoicing) | 8999 | 5432 |

## Deployment Process (Pi Prod)

1. Make changes locally, commit and push to GitHub (arshdeepromy/Orainvoice, main branch)
2. Sync code to Pi: `tar -cf - <files> | ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && tar -xf -"`
3. Backend changes: `ssh nerdy@192.168.1.90 "cd /home/nerdy/invoicing && docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate app"`
4. Frontend changes: stop frontend+nginx, rm containers, delete `invoicing_frontend_dist` volume, rebuild with `--build`
5. The docker entrypoint runs `alembic upgrade head` automatically on app start
6. Pi has no git — code is synced via tar+SSH. Pi-specific files (.env.pi, docker-compose.pi.yml) are preserved during sync.

## Key Patterns & Rules

- All API responses wrap arrays in objects: `{ items: [...], total: N }` — never bare arrays
- Frontend must use `?.` and `?? []` / `?? 0` on all API data (see #[[file:.kiro/steering/safe-api-consumption.md]])
- After `db.flush()`, always `await db.refresh(obj)` before returning ORM objects for Pydantic serialization (prevents MissingGreenlet)
- Trade families gate features per business type (see #[[file:.kiro/steering/trade-family-gating-for-new-features.md]])
- All bugs are logged in #[[file:docs/ISSUE_TRACKER.md]] (currently up to ISSUE-106)
- Database migrations must be idempotent where possible (use IF NOT EXISTS for CREATE TABLE)
- The `get_db_session` dependency uses `session.begin()` which auto-commits — use `flush()` not `commit()` in services

## Current State (as of 2026-04-08)

- Alembic: revision 0139 (head) on all environments
- 132 tables in the database
- 106 issues tracked and resolved
- Prod has 1 org, 1 customer, 2 invoices, 1 user (early production)
- HA replication configured between Pi primary and local standby nodes
- Xero accounting integration with webhooks deployed
- Branch management, claims, scheduling, stock transfers all implemented
- Customer creation only requires First Name (all other fields optional per user feedback)
