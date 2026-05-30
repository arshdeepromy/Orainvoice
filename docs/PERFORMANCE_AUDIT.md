# OraInvoice / WorkshopPro — Production Performance & Scalability Audit

**Date:** 2026-05-30
**Status:** App is **live in production**. This audit is post-launch hardening, not pre-launch gating.
**Target scale:** ~500 organisations × 2–6 users (~1k–3k users)
**Deployment:** Self-hosted, single-host Docker Compose on ARM hardware
**Stack:** FastAPI (Python 3.11) + Postgres 16 + Redis 7 + React 19 + Vite 8 + nginx
**Codebase size at audit:** 187 k LOC backend (~80 modules), 204 k LOC frontend, 204 Alembic migrations
**Method:** Four parallel deep-dive agents scanning actual source (not docs), one per layer.

> All findings reference real `file:line` locations. Every recommendation is non-breaking and rolls forward safely on a live system unless explicitly noted. Security impact is called out per finding.

---

## 0. Executive summary

The platform is already running in production. The audit identified four classes of issue that need attention; some are urgent (security/correctness), some affect headroom, and some are positioning for the next 2–5× of growth.

1. **Tenant-isolation defence-in-depth gap (urgent).** RLS policies exist, but the app connects as the Postgres superuser, so RLS is bypassed in practice. One forgotten `org_id` filter at any point = cross-tenant leak. This is the most important fix on the list.
2. **Blocking calls in the async event loop (high impact, low risk).** WeasyPrint (PDFs), bcrypt (login), the synchronous Stripe SDK and emailer-init all run inside `async def` handlers. With 4 gunicorn workers, a few PDF requests or a login burst can freeze the whole platform.
3. **Frontend main bundle is 1.38 MB uncompressed.** ~700 KB is admin/page-editor code that ~5 of 2 500 users ever touch. Service-worker registration is currently a no-op stub.
4. **Connection-pool and background-work topology have no safety margin.** Pool sizing oversubscribes Postgres `max_connections`, the scheduler runs 4× in parallel workers, and there is no real job queue — Stripe/email/PDF work all runs in fire-and-forget `asyncio.create_task` inside request workers.

The §1 quick wins are ~5 dev-days and lift capacity by an estimated 5–10× with no schema changes and no API contract changes. The deeper architectural items in §2 determine your trajectory past 1 000 orgs.

### Rolling this out on a live system

A few principles for every change in this document:

- **Every change must be backward-compatible.** Old workers and new workers will overlap during rollout. No request-shape changes, no response-shape changes.
- **Schema changes only with `CREATE INDEX CONCURRENTLY`.** Never `op.create_index(...)` again — that takes ACCESS EXCLUSIVE locks. Indexes can be added live; see [Appendix A](#appendix-a).
- **Config changes (Postgres `max_connections`, `work_mem`, pool size) require a restart**, but each one is independently reversible. Roll one at a time during a low-traffic window.
- **Frontend bundle changes are zero-risk to ship**, but invalidate the service worker cache (once §F-H5 is wired up) so users actually get the new chunks.
- **Sequence the security fix (Theme A) carefully.** Switching to a non-superuser role + `FORCE ROW LEVEL SECURITY` while live needs a stepwise rollout — script in §3 / Theme A.
- **Take a backup before each schema or config change.** [Section 5 I-M4](#i-m4) flags that backups today are local-only and unverified — fix that first if you haven't already.

---

## 1. Top 10 quick wins (highest leverage, safe to ship to production)

Each item is independent, backward-compatible, and reversible. Order is by leverage, not by sequencing — you can ship in any order.

| # | Change | Effort | Expected impact | Rollout risk | Status |
|---|---|---|---|---|---|
| 1 | Lazy-load admin routes + Puck editor in `App.tsx`; add Vite `manualChunks` | 0.5 d | Main bundle 1.38 MB → ~450 KB. First paint ~3× faster on tablets. | None — old bundles still cached until browser refreshes. | ✅ DONE 2026-05-30 — main chunk now 283 KB (gzip 54 KB), ~5× reduction. Puck/recharts/react-vendor/firebase/dnd/headlessui/axios all in own chunks. Dashboard + 20 admin pages + ManagedPage now lazy-loaded. |
| 2 | Wrap WeasyPrint, bcrypt, sync Stripe SDK with `asyncio.to_thread(...)` | 0.5 d | Eliminates event-loop stalls. 5–10× concurrency on PDF/login paths. | None — semantics identical. Roll worker-by-worker. | ✅ DONE 2026-05-30 — bcrypt (`hash_password`/`verify_password`) made async; 16+ call sites updated. WeasyPrint wrapped in 4 PDF generators (invoice, quote, vehicle service report, purchase order). All 13 sync Stripe SDK calls in `stripe_billing.py` routed through new `_stripe_call()` helper. |
| 3 | Add the index pack in [Appendix A](#appendix-a) via `CREATE INDEX CONCURRENTLY` | 1 d | Customer search and invoice list go from seq-scan to index-scan. | None — `CONCURRENTLY` takes only SHARE UPDATE EXCLUSIVE lock. Run after-hours. | ⏳ pending |
| 4 | Reduce DB pool: `pool_size=15`, `max_overflow=10` × 4 workers = 100 conns. Drop Postgres `max_connections` to 80, `work_mem` to 8 MB | 0.5 d | Eliminates connection-storm risk; ~30 GB of theoretical work-mem reclaimed. | Requires PG restart + app restart. Roll during low-traffic window. Reversible by reverting compose values. | ⏳ pending |
| 5 | Enable service worker (currently a no-op stub in `frontend/src/registerSW.ts`) | 0.5 d | Repeat visits become instant. Kiosk reboots no longer redownload 5 MB. | Low — bake `__APP_VERSION__` into `CACHE_NAME` so deploys cleanly invalidate. Test in staging first. | ✅ DONE 2026-05-30 — `registerSW.ts` now registers `/service-worker.js` on the `load` event with proper error swallow. `vite.config.ts` multi-input emits the SW to `dist/service-worker.js` (no hash, root path). `service-worker.ts` cache name baked from `__APP_VERSION__` (currently `workshoppro-1.13.0`) so each deploy invalidates the previous cache. nginx adds explicit `location = /service-worker.js` block with `Cache-Control: no-cache, no-store, must-revalidate` and `Service-Worker-Allowed: /` headers, returns 404 on missing instead of SPA fallback. Live-tested on dev: `curl -I /service-worker.js` returns `application/javascript`, body contains `workshoppro-1.13.0`. 14/14 pwa.test.tsx pass. |
| 6 | Cache org settings / module enablement / terminology / feature flags in Redis | 0.5 d | Removes 3–5 DB hits from every request. | Low — pick conservative TTLs (60 s settings, 5 min modules). Add invalidation on writes for org-settings PATCH. | ✅ DONE 2026-05-30 — investigation revealed module enablement (60s TTL) and feature flags (30s TTL) were already cached + invalidated. The remaining gap was `get_org_settings` (called from `get_invoice`, customer search, stock-items, tax-wallets). Added read-through 60s Redis cache at key `org:settings:{org_id}` with write-through invalidation in `update_org_settings` + `save_onboarding_step`. Smoke-tested on dev: 5 reads = 1 DB load (4 cache hits); cache key cleared instantly on update. 7 unit tests cover hit/miss/invalidate/Redis-down. |
| 7 | Gate the scheduler behind a single-worker flag (Redis SETNX or env-gated worker 0) | 0.5 d | Stops 4× duplicate billing / Stripe charges / emails on every restart. | **Verify before merge.** Audit logs after rollout to confirm no scheduled task is missed. | ✅ DONE 2026-05-30 — Redis SETNX lock at `scheduler:loop_lock` with 60s TTL renewed every 30s tick. Matches the existing HA heartbeat pattern in `app/main.py`. Workers without the lock stand by and re-attempt acquisition each tick; takeover resets `last_run` to "now" so the predecessor's recent runs aren't repeated. Best-effort lock release on graceful shutdown. Stripe billing path was already protected by stable `idempotency_key`, so this primarily prevents wasted work + duplicate emails/SMS on the other 18 tasks. Unit tests cover acquire/renew/release + Redis-down fail-safe. |
| 8 | Drop `console.log`s in production via Vite `esbuild.drop: ['console','debugger']`; explicit `build.sourcemap: false` | 0.1 d | Smaller bundles + no info leak on payment/portal pages. | None. | ✅ DONE 2026-05-30 — implemented as `stripConsoleInProduction()` plugin in `vite.config.ts` (Vite 8 / rolldown ignores esbuild.drop config; plugin does the same job at build time). `build.sourcemap: false` codified. |
| 9 | Gunicorn `--preload`, env-driven worker count (`WEB_CONCURRENCY=2` on the Pi) | 0.2 d | 3× faster startup; CPU oversubscription resolved. | Low — verify worker-startup modules are fork-safe (current code is; `redis_pool` is created at import). | ✅ DONE 2026-05-30 — Dockerfile defaults to `WEB_CONCURRENCY=2` env var, drops the pinned `--workers 4`. `--preload` added to Dockerfile + Pi + Pi-standby + standby-prod compose files. Dev/ha-standby use single-process uvicorn — `--preload` not applicable. |
| 10 | Wire `DeadLetterService` into Stripe webhook + email failover + recurring-invoice failure | 0.5 d | Money paths gain a recovery channel. | None — purely additive. | ✅ DONE 2026-05-30 — Stripe platform webhook + Stripe Connect (portal) webhook now write to DLQ on exception with full event payload. Recurring-invoice generation failures stored per-schedule. `send_email()` accepts new `dlq_task_name` / `dlq_task_args` kwargs so callers opt critical sends (invoices, receipts) into DLQ on chain exhaustion. |

Total: ~5 dev-days. Items 1, 8, 9, 10 are zero-risk; 3, 6, 7 are low-risk with verification; 2, 4, 5 deserve staging soak.

---

## 2. What tips first — capacity trajectory

Since you're already live, this is a forward-looking risk register, not a forecast. The current state is "running OK but with no safety margin"; each row says what fails next as load grows from today's baseline.

| Range | First failure mode | Why | Mitigation |
|---|---|---|---|
| **At today's load** | Symptom: occasional 502/timeout under sustained PDF/email bursts; long-tail login latency on Monday mornings | WeasyPrint + bcrypt + sync Stripe SDK are blocking. A "send all invoices to my email" + one Stripe webhook = 4/4 workers blocked. May already be intermittent in your access logs. | Phase 2 items 1, 2 (asyncio.to_thread). Then Phase 4 — PDFs behind a queue. |
| **Today, anytime** | Cross-tenant leak from a new endpoint missing `org_id` | Postgres superuser bypasses RLS. The ORM + middleware do the isolation today; there is no second line of defence. | Phase 1 audit + Phase 3 RLS rollout (Theme A). |
| **Today, on any host failure** | Upload-volume data loss | Encrypted uploads live on one local Docker volume. No nightly off-host backup. SD-card / disk failure = total loss of customer receipts. | Phase 1 first task — `rclone copyto` nightly. |
| **As you grow → 200 orgs** | Postgres connection saturation + `work_mem` blow-up | `max_connections=200` × `work_mem=64MB` × sort/hash ops can request >30 GB on a 7.6 GB host. Kernel OOM-kills the largest process (probably Postgres). | Phase 2 — pool & work_mem retune. |
| **200 → 500 orgs** | DB CPU saturated on N+1 patterns | `get_invoice()` is 8+ sequential round-trips; customer search is seq-scanning a 2.5 M-row table on every keystroke. Today p50 is fine; p99 will widen first, then p50. | Phase 2 indexes + Phase 3 N+1 fixes. |
| **500 → 2 000 orgs (10×)** | Single-host Compose plateau | Postgres + Redis + app + nginx all on one box. No multi-host story. Single-host upgrade path runs out around the 1k-org mark. | Phase 4 forklift: PG on its own host with PgBouncer, S3 uploads, ≥2 app replicas behind a real LB. |

Things that look scary but **won't tip first**: nginx (sound config), Redis (1 GB plenty for caches + sessions denylist), the static-asset path (already long-cached + hashed), the in-process scheduler (until the PDF/email volume forces a real queue, which §1 item 2 buys you time on).

How to tell where you are right now: the metrics package in I-M5 (`structlog` + Prometheus) is what tells you which row above you're tripping. Wire it in Phase 3 so subsequent decisions are data-driven instead of guesses.

---

## 3. Cross-cutting themes (audited multiple times, consensus issues)

These appeared independently in two or more agents — treat as the strongest signal:

### Theme A — RLS configured but not enforced
- **Backend audit:** noted superuser bypass risk (`docker-compose.yml:7` connects as `postgres`).
- **DB audit:** counted 59 `ENABLE ROW LEVEL SECURITY` vs only 27 `CREATE POLICY`; zero `FORCE ROW LEVEL SECURITY` anywhere in `alembic/`.
- **Infra audit:** flagged it as the highest-priority security item.
- **Action:** Create `orainvoice_app` role (NOLOGIN superuser bits, DML grants), switch `DATABASE_URL` over, run a migration that adds `FORCE ROW LEVEL SECURITY` to every tenant table and ensures a `tenant_isolation` policy exists. Keep `postgres` only for migrations and ops.

**Live-system rollout (do not skip a step):**

1. **Audit first** — before changing roles, run a one-off script that lists every `SELECT`/`UPDATE`/`DELETE` statement in `app/modules/*/service.py` missing an explicit `org_id` predicate. Fix any found. This is your real safety net; RLS is the second one.
2. **Backfill policies.** Migration creates a `tenant_isolation` policy on every table that has `ENABLE ROW LEVEL SECURITY` but no policy (32 tables currently). Use `current_setting('app.current_org_id', true)::uuid` (with the `, true`) so unset GUC returns NULL instead of throwing.
3. **Wrap the GUC read in a `STABLE` SQL function** (D-M11) so the planner folds it and indexes still get used.
4. **Create the new role in staging**, switch `DATABASE_URL`, run the full e2e suite. Expect to find missed-`org_id` queries in less-trafficked endpoints (admin tools, exports).
5. **In production:** create the role, `GRANT ... TO orainvoice_app`, run for 24 h with `DATABASE_URL` still pointing at `postgres` but the role *available*. Then cut over `DATABASE_URL` during a low-traffic window — `app/core/database.py` already supports env-driven role.
6. **Last** — only after the role cutover is stable, apply `FORCE ROW LEVEL SECURITY` table-by-table, smallest tables first. Each one is independently reversible (`ALTER TABLE x NO FORCE ROW LEVEL SECURITY`).

### Theme B — Blocking I/O inside `async def`
- `bcrypt.checkpw` / `bcrypt.hashpw` in [app/modules/auth/password.py:12,17](app/modules/auth/password.py#L12-L17) (called from auth/service.py:157, 1859, 2506). ~80–300 ms each, caps logins/sec/worker to single digits.
- WeasyPrint `HTML(...).write_pdf()` in [app/modules/invoices/service.py:4446](app/modules/invoices/service.py#L4446) and [app/modules/quotes/service.py:1160](app/modules/quotes/service.py#L1160). 200–1500 ms freezes the whole event loop.
- Sync Stripe SDK in [app/integrations/stripe_billing.py:257, 277, 306, 341, 367, 391, 449, 491, 532, 569, 594, 625, 688](app/integrations/stripe_billing.py). 200–800 ms WAN RTT per call.
- **Action:** `await asyncio.to_thread(...)` wrap on each call site. Mechanical change, zero behaviour difference.

### Theme C — Connection-pool oversubscription
- Backend: `pool_size=30 + max_overflow=15` × 4 workers = 180 connections vs Postgres `max_connections=200`. Leaves ~20 for migrations, replication, psql, monitoring.
- Infra: same finding plus `work_mem=64MB` × 200 conns × 3 sort/hash ops = potentially 38 GB of theoretical work-mem on a 7.6 GB host.
- DB: confirms PgBouncer-in-front is the cleanest fix; cites pool-storm leading to FATAL too-many-connections during deploy.
- **Action:** Item 4 in §1. Then add PgBouncer (transaction mode) as the medium-term answer.

### Theme D — Scheduler/background-work topology
- Backend: scheduler runs in every uvicorn worker; 19 daily tasks × 4 workers means duplicate Stripe charges/emails on every restart.
- Infra: `app/core/job_queue.py` (Celery routing) is dead code, never wired. No `worker` service in compose. Stripe webhook handlers, PDFs, emails all run as fire-and-forget `asyncio.create_task` inside request workers.
- **Action:** Short-term — gate the scheduler behind a Redis SETNX lock (or run only on worker 0 via env). Medium-term — add an `arq` worker container (single dep, Redis-backed, async-native). Move PDFs/emails/Stripe webhooks onto it. Delete `app/core/job_queue.py`.

### Theme E — Per-request DB/Redis hits in middleware
Every authenticated request currently does, in the worst case:
- Auth middleware JWT decode (RS256 + HS256 fallback).
- Tenant middleware (sets ContextVar).
- RBAC middleware: 1 Redis GET + sometimes 1 DB SELECT (`UserPermissionOverride`).
- Feature-flag middleware: 1 Redis GET (cache-miss → DB).
- Module middleware: 1 Redis GET (cache-miss → DB).
- Idempotency middleware (writes only): **2 DB sessions** opened — SELECT then INSERT/UPDATE.
- Rate-limiter: **4 Redis ops** (pipelined to 2 RTTs) + a `PING` per request to validate the client.
- Plus `_check_portal_token_expiry` (portal routes only): 1 DB SELECT.

At 200 req/s that's ~1 200 Redis ops/s + ~600 DB ops/s just for middleware before any business logic runs.

- **Action:** Pipeline RBAC + feature-flag + module + tenant into one Redis `MGET`. Drop the per-request `redis.ping()` in the rate-limiter (rely on auto-reconnect). Move idempotency to Redis SETNX with DB only as a 24 h durable fallback. Cache portal-token expiry for 60 s.

---

## 4. Backend findings (FastAPI / async / middleware)

### HIGH

#### B-H1. WeasyPrint blocks the event loop on every PDF
- **Status:** ✅ DONE 2026-05-30 — wrapped via `asyncio.to_thread(lambda: HTML(string=html_content).write_pdf())` in `app/modules/invoices/service.py`, `app/modules/quotes/service.py`, `app/modules/inventory/service.py` (purchase order PDFs), and `app/modules/vehicles/report_service.py` (service-history reports). PDF rendering now runs on a thread, freeing the event loop for other request handlers during the 200-1500 ms render.
- **Where:** [app/modules/invoices/service.py:4446](app/modules/invoices/service.py#L4446), [app/modules/quotes/service.py:1160](app/modules/quotes/service.py#L1160).
- **Fix:** `pdf_bytes = await asyncio.to_thread(lambda: HTML(string=html_content).write_pdf())`.
- **Medium-term:** Move PDFs behind a job queue (Theme D) and cache rendered PDFs at `/app/uploads/_cache/pdf/<invoice_id>.pdf` keyed by `invoice.version`.

#### B-H2. `bcrypt` is synchronous in async login/refresh/password-reset
- **Status:** ✅ DONE 2026-05-30 — `app/modules/auth/password.py` now exposes `hash_password`/`verify_password` as `async` wrappers around `asyncio.to_thread`, with `*_sync` escape hatches for non-async contexts. Same change applied to `app/modules/fleet_portal/auth.py`. All call sites updated to `await`: auth/service, auth/router, auth/mfa_service, auth/pending_signup, admin/service, admin/router (demo seed), staff/router, organisations/service, fleet_portal/router, fleet_portal/services/account_service.
- **Where:** [app/modules/auth/password.py:12,17](app/modules/auth/password.py#L12-L17); callers at [auth/service.py:157, 1859, 2506](app/modules/auth/service.py).
- **Fix:** `verify_password` → `async def`, `await asyncio.to_thread(bcrypt.checkpw, ...)`. Same for `hash_password`. Update 6 call sites to `await`.

#### B-H3. Scheduler runs in every uvicorn worker
- **Status:** ✅ DONE 2026-05-30 — `_scheduler_loop` now acquires a Redis SETNX lock (`scheduler:loop_lock`, TTL 60s, renewed every 30s tick) before running tasks. Pattern mirrors the existing HA heartbeat in `app/main.py`. Non-holder workers stand by and re-attempt each tick; takeover resets `last_run` to "now" to avoid double-firing recent tasks. Fail-safe: if Redis is briefly unavailable the scheduler runs anyway (log WARN) — same trade-off the heartbeat makes. Test coverage in `tests/test_scheduled_tasks.py::TestSchedulerLock`.
- **Where:** [app/main.py:752-755](app/main.py#L752-L755) → [app/tasks/scheduled.py:908-914](app/tasks/scheduled.py#L908-L914). 19 daily tasks (`process_recurring_billing_task`, `publish_scheduled_notifications`, etc.) all fire 4× concurrently. Only the HA heartbeat has a Redis lock.
- **Fix (short-term):** Wrap each task body in the same `SETNX` lock pattern. Or gate the scheduler behind `RUN_BACKGROUND_TASKS=1` and only set it for one worker.
- **Fix (medium-term):** Move to `arq` in a dedicated worker container.

#### B-H4. Synchronous Stripe SDK calls inside `async def`
- **Status:** ✅ DONE 2026-05-30 — added `_stripe_call(fn, *args, **kwargs)` helper at top of `app/integrations/stripe_billing.py` that runs SDK calls through `asyncio.to_thread`. All 13 documented sync sites now go through it: `Customer.create`, `Customer.modify`, `SetupIntent.create`, `PaymentMethod.list`, `PaymentMethod.detach`, three `PaymentIntent.create` blocks, `InvoiceItem.create`, `Subscription.retrieve`, `SubscriptionItem.create_usage_record`, `Invoice.list`, `billing_portal.Session.create`. Migrating to `httpx.AsyncClient` against `api.stripe.com` directly remains a separate option for the future.
- **Where:** [app/integrations/stripe_billing.py](app/integrations/stripe_billing.py) — 13 call sites listed in Theme B.
- **Fix:** `await asyncio.to_thread(stripe.X.create, ...)`. Or migrate to `httpx.AsyncClient` against `api.stripe.com` directly — the pattern already exists in [payments/service.py:1522, 2077, 2120, 2215](app/modules/payments/service.py).

#### B-H5. DB pool sized too high for `max_connections=200`
- See Theme C and §1 item 4.

#### B-H6. Idempotency middleware does 2 DB hits per write
- **Where:** [app/middleware/idempotency.py:73, 111-118](app/middleware/idempotency.py#L73). Each state-changing POST/PUT/PATCH with `Idempotency-Key` opens two fresh sessions.
- **Fix:** Use Redis `SET ... NX EX 86400` for the first-write lock and cache the JSON response there for 24 h. Fall back to DB row on cache miss only.

#### B-H7. Middleware chain rebuilds `Request(scope)` 9× per request
- **Where:** Every middleware in [app/middleware/](app/middleware/) constructs `Request(scope)`. Each is cheap (~10 µs) but cumulative; the dual-algorithm JWT decode at [auth.py:230-242](app/middleware/auth.py#L230-L242) catches per-iteration exceptions, wasting CPU on the dominant case.
- **Fix:** Where only `scope["path"]` is needed, read it directly. Cache decoded JWT payload in Redis keyed by `jti` for token-lifetime (60 s). Eventually collapse RBAC + feature-flag + module + tenant into one middleware (they share the same path-prefix logic and consume `request.state.org_id`).

#### B-H8. RBAC middleware can stampede on cold cache
- **Where:** [app/middleware/rbac.py:93, 102-123](app/middleware/rbac.py#L93). 60 s Redis cache, but cold cache after deploy means 3 k users × 1 DB query at once.
- **Fix:** Raise TTL to 5 min; consider stamping permission overrides into the JWT at issue so the middleware needs no out-of-process lookup.

#### B-H9. Rate-limiter does ~4 Redis ops + a `PING` per request
- **Where:** [app/middleware/rate_limit.py:92-109, 124-141](app/middleware/rate_limit.py#L92-L141).
- **Fix:** (a) Remove the per-request `redis.ping()` — rely on auto-reconnect. (b) Rewrite the sliding-window check as a single Lua script registered at startup. (c) For per-org/per-user limits, INCR with EXPIRE-on-first-write beats ZADD sorted-sets.

### MEDIUM

- **B-M1.** [auth.py:308-352](app/middleware/auth.py#L308-L352) — portal-token expiry checked via DB on every `/portal/*` request. Cache in Redis 60 s.
- **B-M2.** [app/main.py:115-148](app/main.py#L115-L148) — `SQLAlchemyError` handler opens **another** session to log the error; during a DB outage every error response will hang for `pool_timeout=5s`. Use a separate engine or a Redis stream for error logs; wrap in `asyncio.wait_for(..., timeout=0.5)`.
- **B-M3.** Fire-and-forget `asyncio.create_task` for invoice email + Xero sync + Stripe in [invoices/router.py:271, 292, 327, 779, 870, 1148](app/modules/invoices/router.py) and others. No supervision, no concurrency cap, dropped on graceful shutdown. Move to job queue.
- **B-M4.** Feature-flag + module middlewares cold-start storm at deploy time. Warm both in `cache_warming.py`. Merge the two middlewares (identical path-prefix logic).
- **B-M5.** CORS uses `allow_methods=["*"]`, `allow_headers=["*"]` ([main.py:244-250](app/main.py#L244-L250)). Tighten.
- **B-M6.** No `orjson`. Switch to `FastAPI(default_response_class=ORJSONResponse, ...)`; 3–5× faster JSON for large list responses.
- **B-M7.** Gunicorn missing `--preload`. With 30+ imports + `configure_mappers()` per worker, startup time is 4× the necessary. Add `--preload` in [Dockerfile:38](Dockerfile#L38). ✅ DONE 2026-05-30 — added to Dockerfile CMD + the three compose files that override the gunicorn command (Pi, Pi-standby, standby-prod).
- **B-M8.** `pool_pre_ping=True` adds a `SELECT 1` per checkout. Consider disabling and relying on `pool_recycle=1800`.
- **B-M9.** Replace `@app.on_event` (deprecated) with `lifespan` context manager. Run independent startup tasks via `asyncio.gather(...)`.

### LOW

- **B-L1.** `/health` reads VERSION file from disk on every poll. Read at startup.
- **B-L2.** `email_sender.py` constructs a new `httpx.AsyncClient` per send. Reuse a module-level client; close in shutdown.
- **B-L3.** `IntegrityError` handler iterates a 38-entry dict per error. Compile a single regex at module load.
- **B-L4.** `--workers 4` is pinned in the Dockerfile. Make it `${GUNICORN_WORKERS:-2}`. ✅ DONE 2026-05-30 — Dockerfile now uses `${WEB_CONCURRENCY:-2}` (matching gunicorn's documented env var). Pi/Pi-standby/standby-prod compose files already explicit-set `--workers 2`.

---

## 5. Database findings (Postgres / SQLAlchemy async)

### HIGH

#### D-H1. RLS bypassed by superuser connection
- See Theme A. Also note: the original [migration 0008](alembic/versions/) RLS policy uses `current_setting('app.current_org_id')::uuid` *without* the `, true` second argument, so any code path that forgets to set the GUC throws `unrecognized configuration parameter` instead of explicit-denying. The newer `bounced_addresses` policy [0197:165](alembic/versions/) correctly passes `, true` — backfill the same fix to the older policies.

#### D-H2. Connection-pool sizing
- See Theme C / §1 item 4.

#### D-H3. No `CREATE INDEX CONCURRENTLY` anywhere in `alembic/`
- Every `op.create_index(...)` runs an ACCESS EXCLUSIVE lock. On a 5 M-row `invoices` table this blocks writes for tens of seconds — release-blocking at scale.
- **Fix:** Convention/CI lint: index DDL in migrations must use raw SQL `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...` outside Alembic's implicit transaction. Reject `op.create_index(` in code review.

#### D-H4. Missing composite indexes for hot list queries `(org_id, created_at DESC)`
- [invoices/service.py:3348-3366](app/modules/invoices/service.py#L3348) sorts `Invoice.created_at.desc()` filtered by `org_id` — but the only available index is `idx_invoices_org(org_id)`. Planner does index-scan-then-sort.
- See [Appendix A](#appendix-a) for the full SQL block.

#### D-H5. Missing FK indexes
- `payments.org_id`, `line_items.org_id`, `credit_notes.org_id`, `quote_line_items.org_id`, `customer_vehicles.customer_id` all declare FKs but have no covering index. `org_vehicles.(org_id, UPPER(rego))` is needed because [invoices/service.py:1822-1826](app/modules/invoices/service.py#L1822) does exactly that comparison inside `get_invoice()`.

#### D-H6. N+1 in `get_invoice()` — 8+ sequential awaits
- **Where:** [app/modules/invoices/service.py:1703-2020](app/modules/invoices/service.py#L1703). Sequential `await`s for invoice → line_items → org → customer → vehicle → org_settings → per-additional-vehicle vehicle lookups → payments → users.
- **Fix:** Use `selectinload` on the top-level Invoice query to fold line_items + payments + credit_notes into one round-trip. Batch the additional-vehicle lookup into a single `WHERE UPPER(rego) IN (...)`. Memoise `get_org_settings()` on `db.info` per request or cache in Redis.

#### D-H7. Customer search ILIKE bypasses the GIN tsvector index
- **Where:** [customers/service.py:147-153](app/modules/customers/service.py#L147-L153). ILIKE on first_name/last_name/email/phone, none of which have trigram indexes. The existing GIN index on `to_tsvector` is unusable by ILIKE.
- **Fix:** `pg_trgm` GIN indexes — see [Appendix A](#appendix-a).

#### D-H8. N+1 in `search_customers(include_vehicles=True)`
- **Where:** [customers/service.py:260-293](app/modules/customers/service.py#L260-L293). One sub-query per returned customer.
- **Fix:** One `IN (customer_ids)` query, bucket in Python.

#### D-H9. `mark_invoices_overdue` cross-tenant scan
- **Where:** [invoices/service.py:2951-2983](app/modules/invoices/service.py#L2951-L2983). No `org_id`, no covering index, loads all overdue invoices into Python, updates one by one.
- **Fix:** Partial index `WHERE status IN ('issued','partially_paid') AND balance_due > 0`. Convert to a single bulk `UPDATE ... RETURNING id`. Run with explicit `SET LOCAL row_security = off`.

#### D-H10. No caching of org settings / module enablement / terminology
- **Status:** ✅ DONE 2026-05-30 — module enablement (`app/core/modules.py::ModuleService.is_enabled`) was already cached with 60s TTL + invalidation. Feature flags (`app/middleware/feature_flags.py` + `app/modules/feature_flags/service.py::FeatureFlagCRUDService`) were already cached at 30s + invalidated on writes via two cache layers. The remaining gap was `get_org_settings`. Added read-through cache at `org:settings:{org_id}` with 60s TTL, write-through invalidation hooked into `update_org_settings` and `save_onboarding_step`. Other write paths (billing webhooks, payment surcharge, retention warnings) self-heal within 60s. Verified on dev: 5 reads = 1 DB load.
- **Where:** `app/core/cache.py` exists and is well-designed, but `grep -rln "from app.core.cache" app/` returns only `app/main.py`. Per-request hot lookups happen via direct DB hits:
  - [customers/service.py:128](app/modules/customers/service.py#L128) — `ModuleService.is_enabled` per search.
  - [invoices/service.py:1764](app/modules/invoices/service.py#L1764) — `get_org_settings()` per `get_invoice()`.
- **Fix:** Decorate these with `@cached("module_enabled", ttl=600, ...)`. Add a request-scoped memo in `db.info`.

### MEDIUM

- **D-M1.** Partial indexes for soft-deleted/`is_anonymised=false` and `dismissed_at IS NULL` — see [Appendix A](#appendix-a).
- **D-M2.** No GIN indexes on JSONB columns that will be searched later (`invoices.invoice_data_json`, `customers.tags/custom_fields`). Add `jsonb_path_ops` GIN as filters come online.
- **D-M3.** LIMIT/OFFSET deep pagination. Move hot list endpoints (invoices, customers) to keyset pagination: `WHERE (created_at, id) < (:last_created, :last_id) ORDER BY created_at DESC, id DESC LIMIT n`.
- **D-M4.** Count-and-data double round-trip on every list. Use `COUNT(*) OVER ()` window function or cache `(org_id, filter-hash)` totals for 30 s in Redis.
- **D-M5.** Correlated scalar subqueries (`has_stripe_payment`, `attachment_count_subq`) in `search_invoices` fire per row. Replace with a single LEFT JOIN + aggregate, or add `CREATE INDEX CONCURRENTLY idx_payments_inv_method_refund ON payments (invoice_id) WHERE method='stripe' AND is_refund=false`.
- **D-M6.** Every `select(Invoice)` loads the JSONB `invoice_data_json` blob even when not needed. Use explicit-column SELECTs in batch jobs / analytics.
- **D-M7.** Set `lock_timeout=5000` in Postgres command. Hot `FOR UPDATE` on `invoice_sequences` at [service.py:3006](app/modules/invoices/service.py#L3006) can block indefinitely.
- **D-M8.** `pool_timeout=5` is too aggressive given current pool storms. Raise to 15 s until D-H2 is resolved.
- **D-M9.** No cache-invalidation convention. When invoice X changes, which keys are busted? Adopt entity-scoped key conventions; add `invalidate_invoice(invoice_id, org_id)` helpers called from create/update/void.
- **D-M10.** Only ~55 occurrences of `selectinload`/`joinedload` across 200+ service files. Lint for any `for x in result.scalars().all(): ... await ...`.
- **D-M11.** RLS policy uses `current_setting(...)::uuid` cast per row. Wrap in a `STABLE` SQL function returning UUID so the planner can fold it.

### LOW

- **D-L1.** `pool_recycle=1800` vs PG `idle_in_transaction_session_timeout=30s` — minor reconnect churn on background tasks; fine to leave.
- **D-L2.** `cache_warming.py:170` swallows all exceptions silently. Wire a metric counter.
- **D-L3.** `notification_log` and audit-log tables — audit retention & partitioning post-launch. At 500 orgs × 1 k events/day, ranges by `created_at` monthly is the eventual answer.
- **D-L4.** `recurring_schedules` is duplicated across `quotes/models.py` and `recurring_invoices/models.py` with `extend_existing=True`. Consolidate post-launch.

---

## 6. Frontend findings (React 19 / Vite 8)

Built `dist/assets` directory measured at audit time: 5.0 MB across ~250 chunks; **main chunk `index-*.js` = 1.38 MB uncompressed (~330–400 KB gzipped)**.

### HIGH

#### F-H1. No `manualChunks` strategy
- **Status:** ✅ DONE 2026-05-30 — function-form `manualChunks` classifier added in `frontend/vite.config.ts`. Splits puck, stripe, recharts, dnd, firebase-auth, headlessui, qrcode, axios, react-vendor each into their own chunks. Vite 8/rolldown requires the function form (not object).
- **Where:** [frontend/vite.config.ts:15-54](frontend/vite.config.ts#L15-L54) — no `build.rollupOptions.output.manualChunks`. Rollup's default grouping has produced opaque chunk names lumped into the main bundle.
- **Fix:**
  ```ts
  build: {
    target: 'es2020',
    cssCodeSplit: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor':  ['react', 'react-dom', 'react-router-dom'],
          'stripe':        ['@stripe/react-stripe-js', '@stripe/stripe-js'],
          'recharts':      ['recharts'],
          'dnd':           ['@dnd-kit/core', '@dnd-kit/sortable', '@dnd-kit/utilities'],
          'puck':          ['@puckeditor/core'],
          'firebase-auth': ['firebase/app', 'firebase/auth'],
          'headlessui':    ['@headlessui/react'],
          'axios':         ['axios'],
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
  ```

#### F-H2. Puck visual-editor runtime (~311 KB) loaded on every public page
- **Status:** ✅ DONE 2026-05-30 — `ManagedPage.tsx` now dynamic-imports `@puckeditor/core` + `puckConfig` only when the resolve endpoint returns published content. Public-page visitors who only ever see hand-coded fallback never download Puck. `ManagedPage` itself also lazy-loaded in `App.tsx`.
- **Where:** [src/App.tsx:145](frontend/src/App.tsx#L145) statically imports `ManagedPage`, which imports `Render` + the full `puckConfig` at top level ([src/pages/public/ManagedPage.tsx:21-27](frontend/src/pages/public/ManagedPage.tsx#L21-L27)). The editor is global-admin-only (~5 of 2500 users) but every public-page visitor (`/`, `/privacy`, `/trades`, `/workshop`) downloads the runtime.
- **Fix:** Dynamic-import Puck + puckConfig only when the resolve endpoint returns published content. Also lazy-load `ManagedPage` itself.

#### F-H3. Dashboard pulls recharts (~274 KB) eagerly
- **Status:** ✅ DONE 2026-05-30 — `Dashboard` converted to `lazy(() => import('@/pages/dashboard'))`. Recharts now in its own chunk (346 KB / 102 KB gzip), loads only when an authenticated user opens the dashboard. Per-widget lazy-loading deferred to a follow-up.
- **Where:** [src/App.tsx:31](frontend/src/App.tsx#L31) eagerly imports `Dashboard`, which statically imports all three role-specific dashboards, which in turn import `CashFlowChartWidget` → recharts.
- **Fix:** `lazy()` the Dashboard route. Inside the Dashboard, `lazy()` each widget — charts are below the fold.

#### F-H4. All ~20 admin routes eagerly imported
- **Status:** ✅ DONE 2026-05-30 — every admin page in `App.tsx` now uses `lazy(() => import(...))`: Organisations, AnalyticsDashboard, AdminSettings, ErrorLog, NotificationManager, BrandingConfig, MigrationTool, LiveMigrationTool, HAReplication, AuditLog, AdminReports, Integrations, UserManagement, SubscriptionPlans, FeatureFlags, GlobalAdminProfile, TradeFamilies, AdminSecurityPage, OrganisationDetail. Main chunk dropped from 1.38 MB to 283 KB.
- **Where:** [src/App.tsx:35-53](frontend/src/App.tsx#L35-L53) — `Organisations`, `AnalyticsDashboard`, `HAReplication` (143 KB source!), `SubscriptionPlans` (67 KB), `LiveMigrationTool`, `FeatureFlags`, etc., all with regular `import`. Touched by ~5 of 2500 users.
- **Fix:** Convert each to `lazy(() => import(...))` exactly like the org pages do already. Expected main-chunk reduction: 250–400 KB.

#### F-H5. Service worker is a no-op stub
- **Status:** ✅ DONE 2026-05-30 — `registerSW.ts` now actually registers `/service-worker.js` on the window `load` event with a `.catch` to swallow registration errors. `service-worker.ts` cache name embeds `__APP_VERSION__` (`workshoppro-1.13.0`) so each deploy cleanly invalidates the previous cache (verified by reading the emitted file body). `vite.config.ts` updated with a multi-input `rollupOptions` so the SW is built as a separate bundle and emitted at `dist/service-worker.js` with a stable URL (no hash, root path — required for SW spec scope claim). nginx gained an explicit `location = /service-worker.js` block setting `Cache-Control: no-cache, no-store, must-revalidate` and `Service-Worker-Allowed: /`; returns 404 on missing instead of the SPA fallback so a broken build can never poison clients with index.html as their SW. Frontend dev compose adds `package.json:ro` bind mount so the in-container build sees the host's version (otherwise stale).
- **Where:** [src/registerSW.ts:1-7](frontend/src/registerSW.ts#L1-L7) — empty function with a comment. But [src/service-worker.ts](frontend/src/service-worker.ts) is a fully-written cache-first/network-first worker that's never emitted by the build.
- **Fix:** Wire it into the Vite build (copy to `public/` or use `vite-plugin-pwa`). Cache-bust on deploys by interpolating `__APP_VERSION__` into the SW's CACHE_NAME. Excludes `/api/*` already exist in the worker — safe.

#### F-H6. `console.log` ships to production
- **Status:** ✅ DONE 2026-05-30 — `stripConsoleInProduction()` plugin in `vite.config.ts` rewrites statement-position `console.*` and `debugger` calls in our `.ts/.tsx/.js/.jsx` sources during `NODE_ENV=production` builds (skips `node_modules` so third-party warning paths stay intact). Vite 8 / rolldown ignores the legacy `esbuild.drop` config; the plugin replaces it.
- **Where:** [VehicleLiveSearch.tsx:88,98](frontend/src/components/vehicles/VehicleLiveSearch.tsx#L88), [PageEditorList.tsx:255](frontend/src/admin/page-editor/pages/PageEditorList.tsx#L255), [AccountingIntegrations.tsx:235](frontend/src/pages/settings/AccountingIntegrations.tsx#L235), [WebhookManagement.tsx:506](frontend/src/pages/settings/WebhookManagement.tsx#L506).
- **Fix:**
  ```ts
  esbuild: {
    drop: process.env.NODE_ENV === 'production' ? ['console', 'debugger'] : [],
  }
  ```
- **Security:** leaks search queries / response bodies to anyone with DevTools on the public portal/payment pages.

### MEDIUM

- **F-M1.** Provider tree wraps the whole app in 7 nested contexts ([App.tsx:632-653](frontend/src/App.tsx#L632-L653)). Several fetch on mount post-auth, cascading rerenders. Move the auth-dependent providers (Tenant/Module/FeatureFlag/Branch) below `RequireAuth`. Verify each provider's `value={{}}` is memoised.
- **F-M2.** Polling without `visibilitychange` gate — Dashboard 60 s, HAStatusPanel 10 s, InboxBellBadge, PlatformNotificationBanner. Pause when tab hidden. (Pattern in §6 below.)
- **F-M3.** No data-cache / dedup layer. Every navigation refetches. Add `@tanstack/react-query` (~13 KB gzipped) and convert the heavy lists first. `staleTime: 30_000` makes back-navigation instant.
- **F-M4.** [InvoiceCreate.tsx:1446, 1538](frontend/src/pages/invoices/InvoiceCreate.tsx#L1446) fetches `/inventory/stock-items?limit=500` twice. Convert to server-side typeahead with debounce 200 ms, limit 20 — pattern already used by `VehicleLiveSearch`.
- **F-M5.** [JobBoard.tsx:77](frontend/src/pages/jobs/JobBoard.tsx#L77) fetches `page_size=200` jobs synchronously, no virtualization. Use `@tanstack/react-virtual` or paginate per status column.
- **F-M6.** `optimizeDeps.include` only affects dev. Comment is misleading about prod first-load. (Item F-H1 is the real fix.)
- **F-M7.** ErrorBoundary's "Try again" doesn't reset Suspense's lazy retry. Wrap with `resetKeys` pattern; move boundary inside Suspense.
- **F-M8.** Codify `build.sourcemap: false` in vite.config.ts so a future flip doesn't leak source. ✅ DONE 2026-05-30 — explicit `sourcemap: false` set in `frontend/vite.config.ts`.
- **F-M9.** `isAccessTokenValid()` parses JWT via `atob` every interceptor call ([src/api/client.ts:20-30](frontend/src/api/client.ts#L20)). Memoise.

### LOW

- **F-L1.** Only 6 of 22 `<img>` tags use `loading="lazy"`. Add it to below-fold images (customer/vehicle thumbnails). Mark the first hero image `fetchPriority="high"`.
- **F-L2.** 40+ `<link rel="modulepreload">` in `index.html`. Once F-H1–F-H4 land most disappear naturally. Set `build.modulePreload.polyfill: false` if still excessive.
- **F-L3.** [src/router/ModuleRouter.tsx](frontend/src/router/ModuleRouter.tsx) defines a parallel route table that appears unused. Verify and delete.
- **F-L4.** Audit `tailwind.config.js content:` glob — does it include `../shared/`? If not, classes from shared types are missing in prod.
- **F-L5.** [src/api/client.ts:73-78](frontend/src/api/client.ts#L73-L78) mutates `config.baseURL = ''` per request. Use a separate `apiV2Client` instance.
- **F-L6.** [QrPaymentWaitingPopup.tsx:99](frontend/src/pages/invoices/QrPaymentWaitingPopup.tsx#L99) 3 s polling has no visibility gate (acceptable while modal is open; verify `clearInterval` on close).
- **F-L7.** 0 occurrences of `React.memo` or `memo(`. Address only if profiler shows row-level re-renders dominating.
- **F-L8.** [Dockerfile:8](frontend/Dockerfile#L8) `|| true` on `@rollup/rollup-linux-arm64-musl` masks failures. Pin in `optionalDependencies`.

---

## 7. Architecture & infrastructure findings

### HIGH

#### I-H1. RLS not enforced (superuser connect)
- See Theme A. The single most important security item before launch.

#### I-H2. No real background worker
- See Theme D.

#### I-H3. Dead-letter queue never written to
- **Status:** ✅ DONE 2026-05-30 — three highest-impact sites wired:
  - Stripe platform webhook (`app/modules/payments/router.py`) — DLQ entry on `handle_stripe_webhook` exception with full event payload.
  - Stripe Connect portal webhook (`app/modules/portal/router.py`) — same pattern.
  - Recurring invoice generation (`app/tasks/scheduled.py`) — per-schedule DLQ entry on failure so a broken org doesn't get silently skipped on every cycle.
  - Email exhaustion path now optional via new `dlq_task_name` / `dlq_task_args` kwargs on `send_email()` (callers opt in for invoice emails, payment receipts, etc.).
  - `alert_if_stale` cron remains pending — wire as a small follow-up.
- **Where:** [app/core/dead_letter.py](app/core/dead_letter.py), [app/models/dead_letter.py](app/models/dead_letter.py). Zero callers of `DeadLetterService.store_failed_task` outside the module itself.
- **Fix:** Wire into (1) Stripe webhook processing failures, (2) `send_email_task` exhausted retries, (3) recurring-invoice generation per-schedule failures. Add a daily cron that runs `alert_if_stale(60)`.

#### I-H4. Postgres tuned for a 16 GB host that isn't the deploy target
- See Theme C / §1 item 4.

#### I-H5. Uploads on a local Docker volume, not backed up off-host
- **Status:** ⚠️ PARTIAL 2026-05-30 — DB backups now off-host (every 4 h pg_dump from Pi PROD's local replica → `/home/romy/OraBck/`, retained 24 h intra-day + 7 daily). The uploads volume tar is still pending — deferred until BYO Drive ships and handles both DB + uploads in one stream. Local-only-but-different-machine is sufficient for the current hardware-failure threat model; remote off-site lands with the BYO Drive feature.
- **Where:** [docker-compose.yml:133](docker-compose.yml#L133) (`app_uploads:/app/uploads`). `scripts/deploy-prod.sh` only backs up Postgres.
- **Fix (short-term):** Nightly cron tars `/app/uploads` to off-host storage (rclone to B2/S3 or a NAS).
- **Fix (medium-term):** Migrate to S3-compatible object storage; the upload helper is a single chokepoint, so swapping in `boto3`/`s3fs` is contained. Required for ever running >1 app replica.

#### I-H6. sshd running inside the app container on port 2222
- **Where:** [Dockerfile:12](Dockerfile#L12) (`openssh-server`), [scripts/docker-entrypoint.sh:65-73](scripts/docker-entrypoint.sh#L65-L73), port 2222 exposed in compose.
- **Why:** A Python RCE escalates to "host networking via container sshd"; the same container holds Stripe/Twilio/Xero secrets, JWT signing keys, encryption master key.
- **Fix:** (a) Bind 2222 to `127.0.0.1` or the HA-network interface only, never 0.0.0.0. (b) Run an rsync sidecar container with read-only mount of `/app/uploads` instead of bundling sshd. (c) If sshd stays, gate it behind `HA_ENABLED=1` so single-node deployments don't run it.

#### I-H7. Migrations + demo seeding run on every container start
- **Where:** [scripts/docker-entrypoint.sh:83-128, 178-181](scripts/docker-entrypoint.sh).
- **Fix:** Split out a one-shot `migrate` service in compose (`docker compose run --rm migrate`). Today, wrap the entrypoint block in a Postgres advisory lock so duplicate boots wait cleanly.

#### I-H8. No `/readyz` — `/health` is a constant 200
- **Where:** [app/main.py:703-714](app/main.py#L703-L714). No DB or Redis check; no `healthcheck:` declared on the `app` service.
- **Fix:** Add `/readyz` doing `SELECT 1` + `redis.ping()` with 1 s timeout. Add a Docker `healthcheck:` and nginx upstream `proxy_next_upstream` so requests route around a wedged worker.

### MEDIUM

- **I-M1.** Module enablement = 1 Redis GET per request × N modules. Cache full per-org module set as one JSON blob, 5-min TTL, single GET.
- **I-M2.** Feature-flag eval same shape. Add 5 s in-process LRU on `(org_id, flag_key)`.
- **I-M3.** `statement_timeout=30s` kills legitimate cross-org reports. Pattern already exists in `query_optimizer.py:24` — extend to all report endpoints via `SET LOCAL statement_timeout=120000`.
- **I-M4.** Backups are local-only, 5 snapshots, no off-host, no verified restore. Nightly `pg_dump | age -e | rclone copyto`; quarterly restore drill into the standby stack. ⚠️ PARTIAL 2026-05-30 — DB backups now run every 4 h from the Pi PROD replica into `/home/romy/OraBck/` on the local box (different physical machine than Pi PROD). Retention: 24 h intra-day + 7 daily. Setup in `scripts/backup-standby-prod.sh` + user crontab. Off-site (Drive/S3/B2) and verified restore drill still pending — both planned alongside the BYO Drive backup feature.
- **I-M5.** No structured logs, metrics, or tracing. Add `structlog` JSON with `org_id`/`user_id`/`request_id`; add `prometheus-fastapi-instrumentator` (5 lines, exposes `/metrics`); configure compose `logging:` driver with size caps so logs don't fill the SD card.
- **I-M6.** WeasyPrint in request worker — see B-H1; move to job queue.
- **I-M7.** [frontend/Dockerfile:19](frontend/Dockerfile#L19) keeps Node alive forever (`setInterval(()=>{},60000)`) just to hold a shared volume. ~80 MB of pointless RAM. Multi-stage build that copies `dist/` into the nginx image at build time instead.
- **I-M8.** `cpus: '4.0'` limit on both `postgres` and `app` on a 4-vCPU box = 200% oversubscription. Drop the limit and let the scheduler do its job.
- **I-M9.** Uploads served via gunicorn (decrypt in Python). Use `internal;` nginx location + `X-Accel-Redirect` for non-sensitive categories. Preserve encryption for PII categories.
- **I-M10.** No Redis JWT denylist for revoked access tokens — invalidation waits up to 15 min. Add Redis denylist keyed by JTI with access-token TTL; check in `AuthMiddleware`.
- **I-M11.** Logical replication publication auto-refreshes on primary boot. If migration creates a table and entrypoint crashes pre-refresh, standby silently misses those rows. Run publication refresh inside the Alembic transaction, or switch to `FOR ALL TABLES` with row filter.

### LOW

- **I-L1.** nginx `client_max_body_size 50M` vs app upload limit 10 MB — mismatch. Drop nginx limit to 12 MB.
- **I-L2.** No brotli compression, no edge rate-limit on `/api/v1/auth/login`. Switch to openresty image or add nginx `limit_req_zone` for login.
- **I-L3.** CORS allow_methods=`*`, allow_headers=`*`, allow_credentials=True ([main.py:244-250](app/main.py#L244-L250)). Enumerate explicit values.
- **I-L4.** Email retry delays `(60, 300, 900)` thunder-herd on provider recovery. Add `random.uniform(0.8, 1.2)` jitter.
- **I-L5.** `ENCRYPTION_MASTER_KEY` in `.env`. Document a rotation runbook.
- **I-L6.** `huge_pages=try` silently falls back. Log actual setting at boot for ops visibility.

---

## 8. Phased rollout plan (since you're already in production)

Four phases, ordered by urgency × safety. Nothing here is breaking; nothing requires a maintenance window beyond the brief PG restart in Phase 2.

### Phase 1 — This week (urgent: security & easy wins, no restart needed)

- [x] **Off-host backup first.** Before any other change, get nightly `pg_dump | rclone copyto` + `/app/uploads` tar to off-host storage. (I-M4, I-H5.) Without this, every later step is riskier than it needs to be. ⚠️ PARTIAL 2026-05-30 — DB done (4-hour cron from Pi PROD's local replica → `/home/romy/OraBck/`). Uploads tar + remote off-site (Drive/S3) still pending; both deferred until the BYO Drive feature ships.
- [ ] **Bind sshd's port 2222 to the HA-network interface only** — not 0.0.0.0. (I-H6.) Single compose change, takes effect on restart.
- [x] **Drop `console.log` in production** via Vite `esbuild.drop: ['console','debugger']`. (F-H6.) Static-asset deploy only — no backend touched. ✅ DONE 2026-05-30.
- [x] **Codify `build.sourcemap: false`** in `vite.config.ts`. (F-M8.) ✅ DONE 2026-05-30.
- [x] **Lazy-load admin routes + Puck + Dashboard + add Vite `manualChunks`.** (F-H1, F-H2, F-H3, F-H4.) Frontend-only ship, fully reversible. ✅ DONE 2026-05-30 — main chunk 1.38 MB → 283 KB.
- [ ] **Audit `app/modules/*/service.py` for queries missing `org_id`** — this is the prerequisite step for Theme A's RLS rollout. Treat as a code-review pass, not a code change.

### Phase 2 — Next 2 weeks (perf & headroom, one careful restart)

Plan a single low-traffic window. Bring everything below in one PR per area, ship sequentially.

- [x] **`asyncio.to_thread` wraps on bcrypt, WeasyPrint, Stripe SDK** (B-H1, B-H2, B-H4). Roll worker-by-worker via gunicorn graceful restart. ✅ DONE 2026-05-30.
- [x] **Gunicorn `--preload`; `WEB_CONCURRENCY=${WEB_CONCURRENCY:-2}`** (B-M7, B-L4, I-M8). ✅ DONE 2026-05-30 (I-M8 cpus limit not changed in this batch).
- [x] **Gate the scheduler behind Redis SETNX or single-worker env flag** (B-H3). Watch logs for 24 h to confirm no scheduled task is missed. ✅ DONE 2026-05-30.
- [ ] **Index pack from [Appendix A](#appendix-a)** via `CREATE INDEX CONCURRENTLY`. Budget ~5 min per index on 5 M-row tables. Live-safe.
- [ ] **Pool size 15 + overflow 10 × 4 workers; PG `max_connections=80`, `work_mem=8MB`.** (C / §1 item 4.) Requires PG restart + app restart — this is the one maintenance window in the plan. Take a `pg_dump` immediately before, even with backups in place.
- [ ] **`lock_timeout=5000` in Postgres command** (D-M7) — ship alongside the PG restart above.
- [x] **Service worker actually registers** (F-H5). Bake `__APP_VERSION__` into `CACHE_NAME`. Test in staging first; broken SW caching is the one frontend item that can damage UX persistently. ✅ DONE 2026-05-30.
- [x] **Cache org settings / module enablement / terminology / feature flags in Redis** (D-H10, I-M1, I-M2). Conservative TTLs; add invalidation on writes. ✅ DONE 2026-05-30 — modules + feature flags were already done; `get_org_settings` cache + invalidation added.
- [x] **Wire `DeadLetterService` into Stripe webhook + email failover + recurring-invoice** (I-H3). Purely additive. ✅ DONE 2026-05-30 — three sites + opt-in email DLQ kwargs.
- [ ] **`/readyz` endpoint + Docker `healthcheck:` + nginx `proxy_next_upstream`** (I-H8). Purely additive.

### Phase 3 — Next month (the RLS fix, sequenced carefully)

This is the most important security item but it needs the audit-first approach from Theme A above.

- [ ] **Create `orainvoice_app` Postgres role** in staging; switch `DATABASE_URL`; run full e2e suite; fix any missed `org_id` filters found.
- [ ] **Backfill `current_setting('app.current_org_id', true)` (with the `, true`)** in the original 0008 policy; wrap in a `STABLE` SQL function (D-H1, D-M11).
- [ ] **In prod: create the role, grant DML, keep `DATABASE_URL=postgres` for 24 h.** Verify nothing else (cron, manual psql) breaks.
- [ ] **Cut `DATABASE_URL` over to `orainvoice_app`** during low-traffic window. Roll back is one env-var change away.
- [ ] **Apply `FORCE ROW LEVEL SECURITY` table-by-table**, smallest first. Each is independently reversible.
- [ ] **Add Redis denylist for revoked JWT access tokens** (I-M10). Required for forced-logout to actually work.
- [ ] **N+1 fix in `get_invoice()` + `search_customers(include_vehicles=True)`** (D-H6, D-H8). Highest p95 wins.
- [ ] **`structlog` JSON + `prometheus-fastapi-instrumentator` + compose `logging:` rotation** (I-M5). You will want this *before* you start the bigger architectural changes in Phase 4.

### Phase 4 — Next quarter (architectural, do once trust is built)

- [ ] **Add an `arq` worker container**; move PDFs, emails, Stripe-webhook side effects, and recurring-invoice generation to it. Cache rendered PDFs at `/app/uploads/_cache/pdf/<invoice_id>.pdf` keyed by `invoice.version`. Delete `app/core/job_queue.py`.
- [ ] **PgBouncer (transaction mode)** in front of Postgres. Lets you drop app-side `pool_size` to 10 × 4 workers and survive bursts without raising `max_connections`.
- [ ] **Keyset pagination on invoices + customers list endpoints**. Hot lists only; keep offset for "jump to page N" admin views.
- [ ] **React Query for the heavy lists** (invoices, customers, inventory, items). Set `staleTime: 30_000` so back-button navigation is instant.
- [ ] **Replace `@app.on_event` with `lifespan` + `asyncio.gather(...)`**. Independent startup tasks fan out in parallel.
- [ ] **X-Accel-Redirect for non-sensitive uploads**. Keep Python decryption for PII categories.
- [ ] **Migrate uploads to S3-compatible object storage** (MinIO if you self-host). Prerequisite for ever running >1 app replica.
- [ ] **Frontend Dockerfile multi-stage**: copy `dist/` into nginx image at build time; drop the always-on Node container (M7 / I-M7).
- [ ] **Split the `migrate` step into a one-shot compose service** instead of running in every entrypoint (I-H7).

---

## 9. Things that already look right

The audit also surfaced a meaningful list of correct decisions worth preserving:

- Postgres tuning has the right shape (`shared_buffers`, `effective_cache_size`, JIT on, `default_statistics_target=200`, `log_min_duration_statement=200`) — only the sizing is off for the actual host (§5 / Theme C).
- Redis sized at 1 GB allkeys-lru with `io-threads 2` and `lazyfree-*` is correct for caches + sessions.
- `cache.py` is well-designed (TTL, key-builder, pattern-invalidation). The only gap is that almost nothing uses it (D-H10).
- gunicorn worker recycling `--max-requests 10000 --max-requests-jitter 1000` is good practice and protects against slow memory leaks.
- TLS to Postgres (`ssl=on` with proper cert mount) is in place.
- The 9-layer middleware stack is correctly ordered (auth before tenant before RBAC before feature-flag before module before rate-limit).
- ASGI middlewares correctly bypass non-HTTP scopes (WebSocket safe — but verify the kitchen-display WS does its own JWT validation).
- `pool_pre_ping=True` defends against stale connections — drop only if measured to be expensive.
- `pyproject.toml` is current (`fastapi>=0.135`, `sqlalchemy[asyncio]>=2.0.49`, `pydantic>=2.12`) — no migration debt.
- TypeScript `strict: true` + `noUnusedLocals/Parameters` — good signal hygiene.
- ErrorBoundary exists and is wired (small retry-semantics gap noted in F-M7).
- The `cache_warming.py` startup hook is structurally right; just needs to warm more per-org data (Theme E).
- Postgres `max_wal_senders=10`, `max_replication_slots=10`, `wal_level=logical` — replication-ready.

---

## Appendix A — Index migration

Run as a single migration with **`CREATE INDEX CONCURRENTLY`** outside the Alembic transaction. Each statement is independent and re-runnable due to `IF NOT EXISTS`.

```sql
-- D-H4: hot list ordering -----------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_org_created_desc
  ON invoices (org_id, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_org_status_created
  ON invoices (org_id, status, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quotes_org_created_desc
  ON quotes (org_id, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_org_created_desc
  ON payments (org_id, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_credit_notes_org_created_desc
  ON credit_notes (org_id, created_at DESC);

-- D-H5: FK indexes ------------------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_org              ON payments (org_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_line_items_org            ON line_items (org_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_credit_notes_org          ON credit_notes (org_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_quote_line_items_org      ON quote_line_items (org_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_vehicles_customer ON customer_vehicles (customer_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_org_vehicles_org_rego_upper
  ON org_vehicles (org_id, UPPER(rego));

-- D-H7: customer search via pg_trgm -------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_first_trgm
  ON customers USING gin (first_name gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_last_trgm
  ON customers USING gin (last_name gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_company_trgm
  ON customers USING gin (company_name gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_email_lower
  ON customers (lower(email));
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_phone
  ON customers (phone);

-- D-H9: overdue partial index -------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_invoices_due_overdue
  ON invoices (due_date)
  WHERE status IN ('issued','partially_paid') AND balance_due > 0;

-- D-M1: partial active indexes ------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_org_active
  ON customers (org_id) WHERE is_anonymised = false;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pending_qr_active
  ON pending_qr_sessions (org_id) WHERE dismissed_at IS NULL;

-- D-M5: covering for invoice-list subquery ------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payments_inv_method_refund
  ON payments (invoice_id) WHERE method = 'stripe' AND is_refund = false;
```

Run after-hours; each `CONCURRENTLY` index acquires only a `SHARE UPDATE EXCLUSIVE` lock, but the catalog scan to detect existing rows takes proportional time on multi-million-row tables. Budget ~5 min per index on a 5 M-row `invoices` table.

## Appendix B — Visibility-gated polling helper

For frontend pollers that should pause when the tab is hidden:

```ts
function usePoll(fn: () => void, intervalMs: number, deps: unknown[] = []) {
  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null
    const start = () => { if (!id) id = setInterval(fn, intervalMs) }
    const stop  = () => { if (id) { clearInterval(id); id = null } }
    const onVis = () => (document.hidden ? stop() : start())
    start()
    document.addEventListener('visibilitychange', onVis)
    return () => { stop(); document.removeEventListener('visibilitychange', onVis) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps])
}
```

Apply at Dashboard, HAStatusPanel, InboxBellBadge, PlatformNotificationBanner (F-M2).

## Appendix C — Auditing methodology

Four parallel agents read the actual source code (not the .kiro/ specs or docs) and reported back. Coverage:

- Backend API & async — `app/main.py`, `app/core/*`, `app/middleware/*`, sample hot-path modules (invoices, payments, customers, auth, email_sender).
- Database & queries — `app/core/database.py`, `app/core/cache.py`, `app/core/query_optimizer.py`, `app/models/*` (sampled), 10 most recent migrations, hot-path service files.
- Frontend — `frontend/vite.config.ts`, `frontend/src/App.tsx`, `frontend/src/router/`, the 8 largest page components, `frontend/dist/` measured.
- Architecture & infra — all compose files, Dockerfiles, nginx config, `app/core/job_queue.py`, `app/core/dead_letter.py`, `app/core/backup.py`, `app/tasks/scheduled.py`, `scripts/docker-entrypoint.sh`.

Total findings: 28 backend, 24 database, 25 frontend, 27 infra = **104 specific issues** with file:line references. This document distils them into the cross-cutting themes plus the per-layer breakouts.
