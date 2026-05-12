# Python Dependency Audit — OraInvoice Backend

**Date:** 2026-05-08
**Scope:** All Python third-party dependencies declared in `pyproject.toml`
**Python version:** 3.11
**Audit method:** Import scans across `app/`, `alembic/`, `tests/`, `scripts/` plus entrypoint / Dockerfile / docker-compose inspection

---

## Executive Summary

`pyproject.toml` declares **29 runtime** and **5 dev** third-party dependencies.

| Category | Count | Action |
|---|---:|---|
| Core (required, heavily used) | 22 | Keep |
| Required but narrowly used (still needed) | 4 | Keep |
| **Dead / replaceable — safe to remove** | **3** | **Remove** |
| Optional dev tooling (review usage) | 1 | Optional |

**Three runtime packages have zero direct imports in the codebase and can be removed with no code changes:**

| Package | Size on disk (approx) | Transitive deps pulled in |
|---|---:|---|
| `reportlab` | ~3.2 MB | Pillow (already direct), chardet |
| `requests` | ~0.5 MB | urllib3, charset-normalizer, idna, certifi |
| `twilio` | ~3.0 MB | PyJWT (already direct), aiohttp, yarl, multidict, frozenlist, propcache, async-timeout |

Removing these three shrinks the install by approximately **10–15 MB** (including their transitive graph), removes roughly **10 transitive packages** from the supply chain, eliminates **3 unnecessary attack surfaces**, and drops 3 packages from the monthly security-patch surface.

A fourth package, `certifi`, has no direct imports but is a transitive dep of `httpx` and `requests`, so removing it from the `pyproject.toml` is cosmetic — pip will still install it.

---

## Methodology

For each declared package the audit checked:

1. **Direct imports** — `grepSearch` on `^(from|import)\s+<module>` across all `.py` files, using the real module name (e.g. `PIL` for `pillow`, `jwt` for `PyJWT`, `dateutil` for `python-dateutil`, `multipart` for `python-multipart`).
2. **Indirect / lazy uses** — searches for known API symbols (e.g. `EmailStr`, `UploadFile`, `relativedelta`, `stripe.PaymentIntent`, `Canvas`).
3. **Non-Python entrypoints** — `Dockerfile`, `docker-compose*.yml`, `alembic.ini`, shell scripts.
4. **Prior analysis** — cross-checked against `docs/DEPENDENCY_UPGRADE_PLAN.md` and `scripts/upgrade_phase5.sh` (which already flagged some items).

---

## 1. Core Runtime Dependencies (Keep — Hard Requirements)

### 1.1 Web framework / server

#### `fastapi` (>=0.135.3)
- **Purpose:** HTTP framework
- **Imports:** 140+ files across `app/modules/**`, `app/main.py`, tests
- **Key symbols:** `FastAPI`, `APIRouter`, `Depends`, `HTTPException`, `UploadFile`, `File`, `Form`
- **Status:** Core. No alternative considered.

#### `uvicorn[standard]` (>=0.44.0)
- **Purpose:** ASGI server / worker
- **Direct Python imports:** None
- **Used via:** `Dockerfile` CMD (`gunicorn ... -k uvicorn.workers.UvicornWorker`), `docker-compose.dev.yml` (direct `uvicorn` command), `docker-compose.ha-standby.yml`, `docker-compose.pi.yml` (UvicornWorker)
- **Status:** Required by every deployment mode. `[standard]` extra pulls in `httptools`, `uvloop`, `websockets`, `watchfiles` — all used by the worker. Keep.

#### `gunicorn` (>=22.0.0)
- **Purpose:** Production process manager
- **Direct Python imports:** None
- **Used via:** `Dockerfile` CMD, `docker-compose.pi.yml`, `docker-compose.pi-standby.yml`, `docker-compose.standby-prod.yml`. Also relied on for multi-worker behaviour in `app/modules/ha/` (BUG-HA-06 Redis lock fix assumes gunicorn workers).
- **Status:** Keep. Previously evaluated for removal in `scripts/upgrade_phase5.sh` and explicitly kept because it drives the production CMD on the Pi and standby nodes.

### 1.2 Database / caching

#### `sqlalchemy[asyncio]` (>=2.0.49)
- **Purpose:** ORM, async query builder
- **Imports:** ~300+ files (every module's `models.py`, `service.py`, router, plus `alembic/versions/*.py` import `sqlalchemy as sa`)
- **Key symbols:** `AsyncSession`, `select`, `text`, `Mapped`, `mapped_column`, `ext.asyncio.*`, `dialects.postgresql.*`
- **Status:** Core.

#### `asyncpg` (>=0.30.0)
- **Purpose:** PostgreSQL async driver used by SQLAlchemy, and directly in scripts.
- **Imports:** `scripts/check_storage.py`, `scripts/check_stripe_config.py`, `scripts/test_*_e2e.py`, `scripts/_check_demo.py`, `scripts/migrate_v1_orgs.py`, etc. (~15 scripts).
- **Used via:** `DATABASE_URL=postgresql+asyncpg://...` (wired into SQLAlchemy).
- **Status:** Core. Required by SQLAlchemy's async engine for PostgreSQL.

#### `redis` (>=7.4.0)
- **Purpose:** Redis client (async)
- **Imports:**
  - `app/core/redis.py`, `app/core/cache.py`
  - `app/middleware/rate_limit.py` (uses `redis.exceptions.RedisError`)
  - `app/integrations/carjam.py`
  - `app/modules/kiosk/{router,service}.py`
  - `app/modules/vehicles/{router,service}.py`
  - `app/modules/kitchen_display/redis_pubsub.py`
  - `app/modules/landing/router.py`
  - `app/modules/admin/live_migration_router.py`, `live_migration_service.py`, `analytics_router.py`
  - Tests: `tests/test_kiosk*.py`, `tests/properties/test_kiosk_properties.py`
- **Status:** Core. Used for rate-limiting, CAPTCHA store, WebAuthn challenge store, CarJam lookup cache, kitchen display pubsub, HA lock, etc.

### 1.3 Security / crypto / auth

#### `cryptography` (>=46.0.7)
- **Purpose:** Low-level crypto primitives
- **Imports:**
  - `app/core/encryption.py` — `cryptography.hazmat.primitives.ciphers.aead.AESGCM` (envelope encryption for all secrets in DB)
  - `app/core/firebase_token.py` — `cryptography.x509`, `default_backend` (Firebase ID token cert verification)
- **Status:** Core. No stdlib equivalent for AES-GCM or X.509 cert parsing.

#### `PyJWT[crypto]` (>=2.12.1)
- **Purpose:** JWT encode / decode
- **Imports:**
  - `app/modules/auth/jwt.py` — access/refresh tokens (HS256 and RS256)
  - `app/middleware/auth.py` — token verification on every request
  - `app/core/firebase_token.py` — Firebase ID token verification
  - Tests: `tests/test_rbac*.py`, `tests/test_middleware.py`, `tests/test_auth_*.py`, `tests/test_api_versioning.py`, `tests/test_core_utilities.py`
- **Status:** Core. `[crypto]` extra provides RSA support via `cryptography` (already direct dep).

#### `bcrypt` (>=4.0.0)
- **Purpose:** Password hashing
- **Imports:**
  - `app/modules/auth/password.py` (`hash_password`, `verify_password`)
  - `app/modules/auth/password_policy.py`
  - `app/modules/auth/mfa_service.py` (backup code hashing)
  - Tests: `tests/test_org_security_settings_property.py`, `tests/properties/test_passkey_properties.py`, `test_mfa_*_properties.py`
- **Status:** Core. (The upgrade plan confirms `passlib` was removed; we use `bcrypt` directly.)

#### `webauthn` (py_webauthn, >=2.7.1)
- **Purpose:** FIDO2 / WebAuthn server-side for passkeys
- **Imports:** Lazy-imported inside `app/modules/auth/service.py` — functions `generate_registration_options`, `verify_registration_response`, `generate_authentication_options`, `verify_authentication_response`, `helpers.structs.*`
- **Also referenced by:** `app/config.py` (`webauthn_rp_id`, `webauthn_rp_name`, `webauthn_origin`)
- **Tests:** `tests/test_auth_passkey.py`, `tests/properties/test_passkey_properties.py`
- **Status:** Core for passkey MFA. No stdlib equivalent.

#### `pyotp` (>=2.9.0)
- **Purpose:** TOTP generation/validation for authenticator-app MFA
- **Imports:**
  - `app/modules/auth/mfa_service.py`
  - Tests: `tests/test_auth_mfa.py`, `tests/test_verify_enrolment.py`, `tests/properties/test_mfa_totp_properties.py`
- **Status:** Core. Trivial to replace with stdlib `hmac` + base32 if needed, but the size/maintenance cost is negligible. Keep.

#### `certifi` (>=2026.2.25)
- **Purpose:** Mozilla CA bundle
- **Direct imports:** None (`grepSearch ^(from|import)\s+certifi` returns zero matches)
- **Transitive consumers:** `httpx`, `requests`
- **Status:** Effectively dead as a direct dep. Removing from `pyproject.toml` does not save install size because `httpx` still depends on it. **Drop the explicit pin unless we specifically want to force a minimum CA bundle freshness; otherwise leave to `httpx`.** Low priority.

### 1.4 Schemas / config

#### `pydantic` (>=2.12.5)
- **Purpose:** Data validation / serialisation
- **Imports:** 100+ files — every `schemas.py`, router request bodies, test validations
- **Status:** Core.

#### `pydantic-settings` (>=2.13.1)
- **Purpose:** `BaseSettings` for env-sourced config
- **Imports:** `app/config.py` (the only consumer)
- **Status:** Core. Pydantic v2 split `BaseSettings` out into this package.

#### `email-validator` (>=2.1.0)
- **Purpose:** Peer dep of Pydantic's `EmailStr` type
- **Direct imports:** None
- **Used via `EmailStr` in:**
  - `app/modules/auth/schemas.py` (login, password reset, invite, email change)
  - `app/modules/admin/schemas.py` (org create, global admin create)
  - `app/modules/organisations/schemas.py` (org provisioning)
  - `app/modules/bookings_v2/schemas.py`
  - `app/modules/landing/schemas.py` (contact form)
- **Status:** Keep. `Pydantic` imports it lazily; without it, every schema using `EmailStr` raises `ImportError` at startup. `scripts/upgrade_phase5.sh` already evaluated and retained it.

### 1.5 HTTP client

#### `httpx` (>=0.28.1)
- **Purpose:** Async HTTP client (sole outbound HTTP library)
- **Imports:**
  - Integrations: `xero.py`, `connexus_sms.py`, `carjam.py`, `stripe_connect.py`, `myob.py`, `hibp.py`, `google_oauth.py`, `brevo.py`
  - `app/core/firebase_token.py` — JWKS fetch
  - `app/modules/ha/heartbeat.py`
  - `app/modules/banking/akahu.py`
  - `app/modules/webhooks/service.py`, `webhooks_v2/service.py`
  - `app/tasks/webhooks.py`
  - Tests (~20 files) use `httpx.AsyncClient` or `ASGITransport` as FastAPI test transport
  - Scripts (~20 `test_*_e2e.py` files)
- **Status:** Core. Used for every outbound HTTP call and as the test-client transport.

### 1.6 Templates / file uploads

#### `jinja2` (>=3.1.0)
- **Purpose:** HTML template rendering
- **Imports:**
  - `app/modules/invoices/template_preview.py`, `invoices/public_router.py`
  - `app/modules/quotes/public_router.py`, `quotes/service.py` (lazy)
  - `app/modules/job_cards/snapshot_renderer.py`
  - `app/modules/vehicles/report_service.py` (lazy)
  - `app/modules/inventory/service.py` (lazy)
  - Tests: `tests/test_invoice_templates.py`, `tests/properties/test_service_history_report_properties.py`
- **Status:** Core. Drives invoice/quote/job-card HTML→PDF templates.

#### `python-multipart` (>=0.0.9)
- **Purpose:** Multipart/form-data parsing — peer dep of FastAPI for `UploadFile` and `Form(...)`
- **Direct imports:** None
- **Used via `UploadFile` / `File` / `Form` in:**
  - `app/modules/branding/router.py` (logo upload)
  - `app/modules/invoices/attachment_router.py`
  - `app/modules/job_cards/attachment_router.py`
  - `app/modules/compliance_docs/{router,service,file_storage}.py`
  - `app/modules/data_io/router.py` (CSV import for customers/vehicles)
  - `app/middleware/storage_quota.py`
  - Tests: `tests/test_branding_upload_validation_property.py`
- **Status:** Keep. FastAPI raises at runtime if this is missing and any endpoint uses `UploadFile`/`Form`.

### 1.7 Date arithmetic

#### `python-dateutil` (>=2.8.0)
- **Purpose:** Calendar-aware date arithmetic (months/years)
- **Imports (`dateutil.relativedelta`):**
  - `app/modules/recurring_invoices/service.py` — `_FREQUENCY_DELTAS` for monthly/quarterly/annually
  - `app/modules/invoices/service.py` — recurring schedule generation
  - `app/modules/vehicles/report_service.py` — service-history date cutoff
  - `app/modules/billing/router.py` — next-billing-date calculation, card expiry window
  - `app/modules/billing/interval_pricing.py` — `compute_interval_duration`
  - Tests: `tests/properties/test_payment_methods_properties.py`, `tests/properties/test_service_history_report_properties.py`
- **Status:** Keep. `datetime.timedelta` cannot express "one calendar month" — the `relativedelta` behaviour is genuinely required. `scripts/upgrade_phase5.sh` evaluated this and kept it.

---

## 2. Integrations (Keep — each is actively wired)

### 2.1 `stripe` (>=15.0.1)
- **Purpose:** Stripe SDK (billing + Connect)
- **Imports:**
  - `app/integrations/stripe_billing.py` — `stripe.Customer`, `stripe.PaymentMethod`, `stripe.PaymentIntent`, `stripe.InvoiceItem`, `stripe.Subscription`, `stripe.SubscriptionItem`, `stripe.Invoice`, `stripe.error.CardError`
  - `app/modules/billing/router.py` — webhook construction via `stripe.Webhook.construct_event`, `stripe.error.SignatureVerificationError`
  - `app/modules/billing/branch_billing.py` — subscription quantity sync
  - `app/modules/admin/router.py` — test webhooks, delete test customer
  - Tests: extensive mocking of `stripe.*` throughout
- **Status:** Core. Heavily integrated.

### 2.2 `alembic` (>=1.18.4)
- **Purpose:** Database migrations
- **Imports:** `alembic/env.py`, every file under `alembic/versions/*.py` (currently 180+ migrations; head is `0182`)
- **Used via:** `alembic.ini` + `docker-entrypoint.sh` (`alembic upgrade head`)
- **Status:** Core.

### 2.3 `pillow` (>=12.2.0)
- **Purpose:** Image processing
- **Imports:**
  - `app/core/captcha.py` — `Image`, `ImageDraw`, `ImageFont` for signup CAPTCHA rendering
  - `scripts/generate_template_thumbnails.py`, `scripts/generate_template_thumbnails_real.py`
  - Tests: `tests/test_invoice_templates.py`
- **Status:** Keep. The CAPTCHA endpoint is the only runtime user, but it's an actively used anti-bot feature on signup (see `CAPTCHA_IMPLEMENTATION.md`). Replacing Pillow here would require a stdlib-only bitmap renderer — not worth the effort.

### 2.4 `weasyprint` (>=62.0)
- **Purpose:** HTML → PDF rendering
- **Imports (all lazy inside function bodies):**
  - `app/modules/invoices/service.py` — `generate_invoice_pdf`
  - `app/modules/quotes/service.py` — quote PDFs
  - `app/modules/inventory/service.py` — supplier PDFs
  - `app/modules/vehicles/report_service.py` — service-history report PDFs
  - `scripts/generate_template_thumbnails_real.py`
  - Tests: `tests/test_supplier_management.py`, `tests/test_pdf_generation.py`, plus properties test mocks
- **Status:** Core. Drives every customer-facing PDF. The `Dockerfile` already installs its native system deps (`libpango`, `libcairo`, etc.).

---

## 3. Dev / Test Dependencies

### 3.1 `hypothesis` (>=6.151.12)
- **Purpose:** Property-based test generator
- **Imports:** 60+ test files (all `test_*_property.py`, `test_*_properties.py`)
- **Status:** Keep. Heavily used across the test suite.

### 3.2 `pytest` (>=8.0.0)
- **Purpose:** Test runner
- **Imports:** Every test file
- **Status:** Keep.

### 3.3 `pytest-asyncio` (>=0.23.0)
- **Purpose:** Async test support
- **Imports:** `pytest_asyncio.fixture` used in `tests/e2e/*.py` (8 files) and `tests/integration/test_feature_flag_fallback.py`; `@pytest.mark.asyncio` used in ~150+ test files
- **Status:** Keep.

### 3.4 `pytest-cov` (>=5.0.0)
- **Purpose:** Coverage reporting (wraps `coverage.py`)
- **Direct references:** None in scripts; `.gitignore` and `.dockerignore` mention `.coverage` / `htmlcov/`
- **Status:** **Review.** No CI script, Makefile, or docs runs `--cov`. If coverage reporting is not part of the current workflow, this can be dropped from dev deps and re-added on demand. Listed as **optional** — confirm with the team before removing.

### 3.5 `fakeredis` (>=2.35.0)
- **Purpose:** In-memory Redis fake for tests
- **Imports:** `tests/test_dependency_upgrade_property.py` uses `fakeredis.aioredis.FakeRedis`
- **Status:** Keep (narrowly used but the only real Redis mock in the suite).

---

## 4. Removable Dependencies (DEAD CODE)

### 4.1 `reportlab` (>=4.4.10) — REMOVE

- **Purpose:** Declared for PDF generation
- **Direct imports across `app/`, `alembic/`, `tests/`, `scripts/`:** **zero**
  - `grepSearch ^(from|import)\s+reportlab` → 0 matches
  - `grepSearch reportlab` → only comments in `app/modules/progress_claims/pdf.py` and `app/modules/variations/pdf.py` saying *"In production this would use ReportLab or WeasyPrint"*. Those modules currently emit plain-text PDFs, not ReportLab.
- **Why it's here:** Historical. `docs/DEPENDENCY_UPGRADE_PLAN.md` lists it under "Phase 2 safe minor upgrades" and `scripts/upgrade_phase2.sh` bumps it — but no code has ever imported it. All real PDF generation goes through WeasyPrint.
- **Install footprint:** ~3.2 MB; pulls in a C extension and Pillow (already required directly).
- **Action:** **Remove from `pyproject.toml`.** Zero risk — no `import reportlab` anywhere.

### 4.2 `requests` (>=2.33.1) — REMOVE

- **Purpose:** Declared as HTTP client
- **Direct imports:** **zero**
  - `grepSearch ^import\s+requests$|^from\s+requests\s+import` → 0 matches
  - `grepSearch requests\.(get|post|put|delete|patch|Session|head)` → 0 matches
- **Why it's here:** All outbound HTTP uses `httpx` exclusively (see §1.5).
- **Install footprint:** `requests` plus transitive `urllib3`, `charset-normalizer`, `idna` — roughly 1.5–2 MB and 4 packages.
- **Action:** **Remove from `pyproject.toml`.** `certifi` may still be pulled in by `httpx`.

### 4.3 `twilio` (>=9.10.4) — REMOVE

- **Purpose:** Declared to support SMS send via Twilio's official SDK
- **Direct imports:** **zero**
  - `grepSearch (from twilio|twilio\.rest|twilio\.base)` → 0 matches
  - `grepSearch ^(from|import)\s+twilio` → 0 matches
- **Historical context:**
  - The platform originally shipped `app/integrations/twilio_sms.py` (a thin `httpx`-based Twilio client — *not* using the `twilio` SDK).
  - Per `.kiro/specs/connexus-sms-integration/` (Requirement 3.6, task 7.1), the file was deleted and SMS was migrated to Connexus (`app/integrations/connexus_sms.py`).
  - Remaining references to `twilio` are limited to: orphan tests (`tests/test_sms_twilio.py`, `tests/integration/test_notifications.py`) that still try to `from app.integrations.twilio_sms import ...` — these tests are broken (the target module was deleted and only `__pycache__/*.pyc` remains); a legacy admin endpoint `POST /admin/integrations/twilio/test` in `app/modules/admin/router.py` which, despite the name, internally calls `ConnexusSmsClient` (see `save_twilio_config` / `send_test_sms` in `app/modules/admin/service.py`).
  - Neither the orphan tests nor the legacy endpoint uses the official `twilio` Python SDK.
- **Install footprint:** `twilio` plus transitive `aiohttp`, `yarl`, `multidict`, `frozenlist`, `propcache`, `async-timeout` — roughly 4–6 MB and 6 packages. `aiohttp` is a notable additional attack surface we do not otherwise need.
- **Action:** **Remove from `pyproject.toml`.** Separately recommended follow-up (outside the scope of this audit): delete or rename the orphan test files and rename the admin endpoint path (`/admin/integrations/twilio/test` → `/admin/integrations/sms/test`) for consistency with the Connexus migration.

---

## 5. Transitive / Cosmetic

### 5.1 `certifi` (>=2026.2.25)

- **Direct imports:** zero
- **Who actually uses it:** `httpx` (transitive), previously `requests`
- **Action:** Optional. Remove the direct pin unless we want to force a fresher CA bundle than `httpx` requires. Keeping it is harmless but adds a line to maintain.

---

## 6. Recommendations (Prioritised)

### P1 — Immediate removals (no code change required)

Remove these three lines from `[project].dependencies` in `pyproject.toml`:

```toml
"reportlab>=4.4.10",
"requests>=2.33.1",
"twilio>=9.10.4",
```

Validation steps before removing:

1. `grep -rE "^(from|import)\s+(reportlab|requests|twilio)\b" app/ alembic/ tests/ scripts/` — must return nothing (already verified above).
2. Rebuild the Docker image; confirm `docker compose up` boots and the health check passes.
3. Run the full test suite. The three orphan Twilio test files (`tests/test_sms_twilio.py`, `tests/integration/test_notifications.py`) already fail to import because `app/integrations/twilio_sms.py` was deleted — removing the `twilio` pin does not make them worse. Handling those files is a separate cleanup.

**Estimated impact:**
- Install size: ~10–15 MB smaller
- Transitive packages removed: ~10 (urllib3, charset-normalizer, idna, aiohttp, yarl, multidict, frozenlist, propcache, async-timeout, plus reportlab's own deps)
- Security patch surface: 3 direct + ~10 transitive packages no longer need monthly update review
- Docker image build time: marginally faster

### P2 — Clean up dead test code (follow-up)

Not part of this audit's scope, but needed to keep CI green once `twilio` is removed:

- Delete or archive `tests/test_sms_twilio.py`
- Delete or rewrite the Twilio-era portions of `tests/integration/test_notifications.py` to target Connexus
- Rename the legacy admin endpoint `POST /admin/integrations/twilio/test` → `POST /admin/integrations/sms/test` (or keep as alias); the underlying service layer already uses Connexus, only the URL/Pydantic schema names still say "Twilio"
- Rename `TwilioConfigRequest`/`TwilioConfigResponse`/`TwilioTestSmsRequest`/`TwilioTestSmsResponse` in `app/modules/admin/schemas.py`

### P3 — Review `pytest-cov` usage

No script, Makefile, or CI config references `--cov`. Either:
- Confirm coverage is run manually and keep the pin, or
- Drop `pytest-cov` from `[project.optional-dependencies].dev` and re-add when a coverage workflow is re-introduced.

### P4 — Consider dropping the explicit `certifi` pin

`httpx` already depends on `certifi`. The explicit pin in `pyproject.toml` is cosmetic unless we want to force a specific CA-bundle freshness. Low priority; no measurable impact either way.

### P5 — Retain the following despite prior "consider removing" notes

`docs/DEPENDENCY_UPGRADE_PLAN.md` mentioned these as potential removal candidates; this audit confirms they must stay:

| Package | Why keep |
|---|---|
| `gunicorn` | Actively used in `Dockerfile` CMD + 3 prod compose files; HA split-brain lock logic depends on multi-worker semantics |
| `python-dateutil` | `relativedelta(months=...)` / `relativedelta(years=...)` — no stdlib equivalent |
| `email-validator` | Required at import time by `pydantic.EmailStr`, which is used in 6+ schemas |
| `jinja2` | Drives invoice/quote/job-card/service-history PDF templates |

---

## 7. Final Categorisation

| # | Package | Status | Action |
|---:|---|---|---|
| 1 | fastapi | Core | Keep |
| 2 | uvicorn[standard] | Core (deployment) | Keep |
| 3 | gunicorn | Core (deployment) | Keep |
| 4 | sqlalchemy[asyncio] | Core | Keep |
| 5 | asyncpg | Core | Keep |
| 6 | redis | Core | Keep |
| 7 | cryptography | Core (security) | Keep |
| 8 | certifi | Transitive via httpx | Optional removal |
| 9 | pydantic | Core | Keep |
| 10 | pydantic-settings | Core (config) | Keep |
| 11 | PyJWT[crypto] | Core (auth) | Keep |
| 12 | bcrypt | Core (auth) | Keep |
| 13 | weasyprint | Core (PDF) | Keep |
| 14 | httpx | Core (HTTP) | Keep |
| 15 | jinja2 | Core (templates) | Keep |
| 16 | python-multipart | Core (FastAPI peer) | Keep |
| 17 | email-validator | Core (Pydantic peer) | Keep |
| 18 | alembic | Core (migrations) | Keep |
| 19 | webauthn | Core (passkeys) | Keep |
| 20 | pyotp | Core (MFA) | Keep |
| 21 | stripe | Core (payments) | Keep |
| 22 | **twilio** | **DEAD** | **Remove** |
| 23 | pillow | Core (CAPTCHA + thumbs) | Keep |
| 24 | python-dateutil | Core (date math) | Keep |
| 25 | **reportlab** | **DEAD** | **Remove** |
| 26 | **requests** | **DEAD** | **Remove** |
| **Dev** | | | |
| 27 | hypothesis | Core (tests) | Keep |
| 28 | pytest | Core (tests) | Keep |
| 29 | pytest-asyncio | Core (async tests) | Keep |
| 30 | pytest-cov | Unused in CI | Optional |
| 31 | fakeredis | Narrowly used (tests) | Keep |

---

## Appendix A — Estimated Install-Size Reduction

Sizes are approximations based on PyPI wheel sizes for 3.11-compatible wheels on Linux x86_64 at the current pinned versions. Actual on-disk size after install will vary with `.dist-info` and `__pycache__`.

| Package to remove | Approx wheel size | Transitive packages removed |
|---|---:|---|
| reportlab | ~3.2 MB | chardet (if not already pulled) |
| requests | ~0.5 MB | urllib3 (~0.5 MB), charset-normalizer (~0.3 MB), idna (~0.1 MB) |
| twilio | ~3.0 MB | aiohttp (~1.5 MB), yarl (~0.3 MB), multidict (~0.2 MB), frozenlist (~0.2 MB), propcache (~0.1 MB), async-timeout (<0.1 MB) |
| **Total direct** | **~6.7 MB** | |
| **Total with transitive** | **~10–15 MB** | ~10 packages |

---

## Appendix B — Grep audit transcript (commands used)

```text
# Direct import scans (module names as actually imported)
^(from|import)\s+fastapi          → many
^(from|import)\s+uvicorn          → 0   (used via Dockerfile CMD)
^(from|import)\s+gunicorn         → 0   (used via Dockerfile CMD)
^(from|import)\s+sqlalchemy       → many
^(from|import)\s+asyncpg          → ~15 (scripts)
^(from|import)\s+redis            → many
^(from|import)\s+cryptography     → 2   (encryption, firebase)
^(from|import)\s+certifi          → 0
^(from|import)\s+pydantic         → many
^(from|import)\s+pydantic_settings→ 1   (app/config.py)
^(from|import)\s+jwt              → many
^(from|import)\s+bcrypt           → many
^(from|import)\s+PIL              → 4   (captcha + scripts + tests)
^(from|import)\s+weasyprint       → 5   (lazy in services + 1 script)
^(from|import)\s+jinja2           → many
^(from|import)\s+multipart        → 0   (used via FastAPI UploadFile)
^(from|import)\s+email_validator  → 0   (used via EmailStr)
^(from|import)\s+alembic          → many (versions/)
^(from|import)\s+webauthn         → lazy inside auth/service.py
^(from|import)\s+pyotp            → 4   (mfa + tests)
^(from|import)\s+stripe           → 3   (+ many mock patches in tests)
^(from|import)\s+twilio           → 0
^(from|import)\s+dateutil         → 4   (services + tests)
^(from|import)\s+reportlab        → 0
^(from|import)\s+requests\b       → 0
^(from|import)\s+httpx            → many
^(from|import)\s+hypothesis       → many
^(from|import)\s+pytest           → many
^(from|import)\s+fakeredis        → 1   (tests/test_dependency_upgrade_property.py)
```
