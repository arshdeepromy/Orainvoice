# Implementation Plan: B2B Fleet Portal

## ⚠️ Naming Note (added during execution of task 1.1)

The spec originally proposed creating a new table named `fleet_accounts`. During task 1.1 a name collision was discovered: a `fleet_accounts` table already exists from migration 0002 (used by `app/modules/customers/` and `app/modules/reports/`, with a one-to-many `customers.fleet_account_id` relationship and unrelated columns: `name`, `primary_contact_*`, `billing_address`, `notes`).

**Resolution applied in migration 0191**: the new table is named `portal_fleet_accounts`. Internal column names stay `fleet_account_id` so service code and Pydantic schemas read naturally.

**For all subsequent tasks**: every mention of `fleet_accounts` (the new table) in this document and in `requirements.md` and `design.md` should be read as `portal_fleet_accounts`. The legacy migration-0002 `fleet_accounts` table is not modified by this spec. The ORM model class name for the new table is `PortalFleetAccount`. Glossary entry `Fleet_Account` still refers conceptually to "a row in `portal_fleet_accounts`".

## Overview

This plan implements the B2B Fleet Portal end-to-end as described in the design document. It follows the project's FastAPI module pattern (`app/modules/fleet_portal/` with `router.py`, `service.py`, `models.py`, `schemas.py`), uses Alembic migration `0191_b2b_fleet_portal.py` for the new tables (current Alembic head is `0190` — verified against `alembic/versions/` rather than the project overview steering doc which lists 0182), and adds two React surfaces: a standalone Fleet Portal SPA (`frontend/src/fleet-portal/`) and Workshop_Admin pages (`frontend/src/fleet-portal-admin/`).

The 34 correctness properties from the design are mapped to backend `hypothesis` tests under `tests/fleet_portal/` and frontend `fast-check` tests under `frontend/src/fleet-portal/__tests__/`, following the property-to-file coverage table in design.md.

Implementation language: **Python 3.11** (backend) and **TypeScript / React 18** (frontend) — both already in use in the project. Tests use **pytest + hypothesis** (backend) and **vitest + fast-check** (frontend).

### Project conventions enforced in every task

These rules are non-negotiable. Every implementation task below MUST follow them:

- **Transaction discipline (ISSUE-024, ISSUE-040, ISSUE-044, ISSUE-102):** Service functions use `await db.flush()` and `await db.refresh(obj)` only — never `db.commit()` or `db.rollback()`. Routers also do not call `db.commit()` or `db.rollback()` — the `get_db_session` dependency uses `async with session.begin()` which auto-commits on success and auto-rolls-back on exception.
- **API response shape (steering: `safe-api-consumption.md`, `frontend-backend-contract-alignment.md`):** Lists return `{ items, total, limit, offset }`, never bare arrays. Pagination uses `offset`/`limit` (rejects `skip` with 422). Errors return `{ "detail": "<msg>" }`.
- **Pydantic schema gate (steering Rule 8):** Every field added to a service dict must also be added to the matching Pydantic response schema. Every endpoint sets `response_model=` so FastAPI validates against the schema.
- **Frontend safe consumption:** Every `set*(res.data.x)` uses `res.data?.x ?? fallback`. Every `.map()` / `.filter()` on API data has `?? []`. Every `useEffect` API call uses `AbortController` cleanup. No `as any`.
- **`SET LOCAL` / RLS variable parameterisation (ISSUE-007 fix already shipped):** The existing `_set_rls_org_id` in `app/core/database.py:75-99` already uses `SELECT set_config('app.current_org_id', :org_id, true)` with bound parameters — `set_config()` is `SET LOCAL`-equivalent but supports parameterised queries safely. **Follow the same pattern** for any new RLS variable: bound params are fine with `set_config()`, no string interpolation needed.
- **External HTTP calls (steering: `performance-and-resilience.md`):** Use `httpx.AsyncClient` as a context manager with explicit timeout. Heavy / synchronous I/O (email send, SMS send) goes to background tasks. Cache tokens in Redis with TTL.
- **Migration idempotency (steering: `database-migration-checklist.md`):** Use `CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO NOTHING`. Run `alembic upgrade head` inside the dev container immediately after creating the migration. Verify the migration by reading actual column names back from PostgreSQL.

### Test scoping policy — run only relevant tests

Every checkpoint and "verify the change" step in this spec runs ONLY the tests that exercise the code touched by that task. The full suite is NOT run between tasks. This rule comes from the existing project pattern in `.kiro/specs/kiosk-qr-payment/tasks.md`, `.kiro/specs/service-package-builder/tasks.md`, and `.kiro/specs/invoice-settings-integration/tasks.md` (all explicitly say "Checkpoints run ONLY relevant tests — not the full test suite — to keep feedback fast").

**Backend (pytest):**

- For a new test file added by this spec, run that file: `pytest tests/fleet_portal/test_<name>_property.py -v --no-header`.
- For a checkpoint covering several files added by this spec, run the directory: `pytest tests/fleet_portal/ -v --no-header`.
- For tests scattered across the repo that share a keyword (e.g. property tests touching reminder logic), use `-k`: `pytest tests/ -k "fleet_portal or reminder_queue" --no-header -q`.
- All backend test commands in this spec MUST run inside the dev container: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest <args>`.
- DO NOT run `pytest tests/` (no path / no `-k` filter) at any checkpoint. The full suite runs only in CI on the final commit.

**Frontend / mobile (vitest):**

- For specific test files added by this spec, run them by path: `npx vitest run frontend/src/fleet-portal/__tests__/touch-target.property.test.ts`.
- For all tests in a directory: `npx vitest run frontend/src/fleet-portal/`.
- For mobile: `npx vitest run mobile/src/__tests__/fleet-portal-routing.property.test.ts`.
- DO NOT run `npm run test` (which executes `vitest --run` against the whole project) at any checkpoint. Reserve that for the final task only.
- For TypeScript-only verification (no test execution): `npx tsc --noEmit` from the relevant package directory — fast, catches type errors without running tests.

**E2E (Playwright):**

- E2E flows added by this spec live under `tests/e2e/fleet_portal/` and run only at the final checkpoint with: `npx playwright test tests/e2e/fleet_portal/`.

**What "relevant" means for each task:**

- Pure backend service / model task → only backend pytest files for that service.
- Pure frontend component task → only the test file(s) for that component, plus `npx tsc --noEmit` on the changed package.
- Migration task → `alembic upgrade head` + a smoke test that imports the new model and round-trips one row, NOT the full backend suite.
- Cross-cutting checkpoint task (e.g. tasks 4, 11, 19) → all property test files added by tasks in that section, joined with `-k` or by path.

Each task in this spec already names its own test command. The rule above documents the philosophy so reviewers know why a checkpoint task does not run the full suite.

## Tasks

- [x] 1. Database migration and module registry
  - [x] 1.1 Create Alembic migration `0191_b2b_fleet_portal.py`
    - **Verify head before writing**: run `ls alembic/versions | sort | tail -5` to confirm the current head is `0190` (not `0182` as the project overview suggests). Set `down_revision = '0190'`.
    - Create the `portal_accounts` table from scratch (it does not exist — `docs/future/portal-password-login.md` was a proposal, never migrated). Columns per design.md "Data Models" → `portal_accounts (created in this migration)`.
    - Create `portal_account_mfa_methods`, `portal_account_backup_codes`, `portal_account_password_history`, `portal_audit_log`, `portal_account_devices` tables per design.md.
    - Create the 10 fleet-domain tables: `fleet_accounts`, `fleet_driver_assignments`, `fleet_checklist_templates`, `fleet_checklist_template_items`, `fleet_checklist_submissions`, `fleet_checklist_submission_items`, `fleet_reminder_preferences`, `fleet_service_booking_requests`, `fleet_quotation_requests`, `fleet_driver_hours`. Use `CREATE TABLE IF NOT EXISTS` and create indexes with `IF NOT EXISTS`.
    - Add unique partial index on `fleet_checklist_templates(fleet_account_id) WHERE is_default = true`.
    - Add unique indexes on `portal_accounts(reset_token)` and `portal_accounts(invite_token)` WHERE NOT NULL.
    - Add CHECK constraint on `fleet_driver_hours(end_at >= start_at)`.
    - **Add `fleet_checklist_template_id UUID NULL` column to the existing `customer_vehicles` table** with `ALTER TABLE customer_vehicles ADD COLUMN IF NOT EXISTS fleet_checklist_template_id UUID NULL REFERENCES fleet_checklist_templates(id) ON DELETE SET NULL` (verified absent — `app/modules/vehicles/models.py:98-138` has no such column).
    - **Add `portal_account_id UUID NULL` column to the existing `portal_sessions` table** with `ALTER TABLE portal_sessions ADD COLUMN IF NOT EXISTS portal_account_id UUID NULL REFERENCES portal_accounts(id) ON DELETE CASCADE` so the existing `PortalSession` row can be reused for password-based fleet sessions (see task 3.5 for usage). **Do NOT change `customer_id` to nullable** — it stays NOT NULL. When creating a fleet portal session, the service writes BOTH `portal_account_id = ...` AND `customer_id = fleet_account.customer_id` (i.e. the underlying customers row that the fleet account links to). This keeps existing token-link queries that join on `customer_id` working unchanged. Discriminator: token-link sessions have `portal_account_id IS NULL`; fleet portal sessions have `portal_account_id IS NOT NULL`.
    - Insert the `b2b-fleet-management` row into `module_registry` with `ON CONFLICT (slug) DO NOTHING`. Required fields per `setup-guide-for-new-modules.md`:
      - `slug = 'b2b-fleet-management'`
      - `display_name = 'B2B Fleet Management'`
      - `description = 'Self-service portal for business customers to manage vehicle fleets.'`
      - `category = 'fleet_management'`
      - `is_core = false`
      - `dependencies = '["vehicles"]'::jsonb`
      - `status = 'available'`
      - `setup_question = 'Do your business customers need a self-service portal to manage their vehicle fleet?'`
      - `setup_question_description = 'Let fleet operators log in to view vehicles, invite drivers, run NZTA pre-trip checklists, book services, request quotes, and manage WOF/COF reminders.'`
    - **Do NOT add a `trade_family_required` column** — trade-family gating is implemented in code via `TRADE_FAMILY_REQUIRED_MODULES` constant (see task 1.3), matching the setup-guide spec's pattern.
    - Insert default `portal_security_policy` JSONB value into the `org_settings` for any org that has the module enabled (default values per design.md Requirement 21 schema).
    - Provide a downgrade that drops the new tables and removes the `module_registry` row.
    - **After writing**, run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` and verify it succeeds (per `database-migration-checklist.md`).
    - _Implements Requirements: 1.1, 4.2, 5.2, 8.1, 9.1, 10.3, 11.2, 12.2, 14.1, 17.2, 21.1, 21.5, 21.10, 21.12, 21.15_

  - [x] 1.2 Enable Postgres RLS on every new table
    - In the same migration, run `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` and create policies `USING (org_id = current_setting('app.current_org_id', true)::uuid)` for SELECT/INSERT/UPDATE/DELETE on each new table.
    - For fleet-scoped tables (everything except `fleet_accounts`, `portal_accounts`, `portal_account_mfa_methods`, `portal_account_backup_codes`, `portal_account_password_history`, `portal_audit_log`), add a second predicate component `OR fleet_account_id = current_setting('app.current_fleet_account_id', true)::uuid` per the design defence-in-depth note.
    - **Set the new RLS variable inside the auth dependency, NOT inside `get_db_session`.** Add a parallel `_current_fleet_account_id: ContextVar[str | None]` to `app/core/database.py` next to the existing `_current_org_id`. Add a helper `_set_rls_fleet_account_id(session, fleet_account_id)` that follows the existing `_set_rls_org_id` pattern at `app/core/database.py:75-99` — `await session.execute(text("SELECT set_config('app.current_fleet_account_id', :fid, true)"), {"fid": validated_uuid_str})`. Bound parameters work with `set_config()`.
    - The `require_fleet_portal_session` FastAPI dependency (task 3.5) calls `_set_rls_fleet_account_id` on every fleet portal request after looking up the session. The existing `get_db_session` is unchanged — it continues to set only `app.current_org_id`. This keeps staff request paths unchanged.
    - _Implements Requirements: 17.2_

  - [x] 1.3 Add `b2b-fleet-management` to `DEPENDENCY_GRAPH` and module config
    - Update `app/core/modules.py` to register `b2b-fleet-management` with `vehicles` as a hard AND-dependency so `ModuleService.enable_module()` auto-enables `vehicles`.
    - Add the constant `TRADE_FAMILY_REQUIRED_MODULES: dict[str, str] = {"b2b-fleet-management": "automotive-transport"}` next to `CORE_MODULES`. Add the gating logic in the module list endpoint and the enable endpoint to read this dict and reject mismatches with HTTP 403.
    - Update the existing setup-guide router (`app/modules/setup_guide/router.py`) to honour this dict (extend its existing trade-gated exclusion set so the new module is correctly excluded for non-automotive-transport orgs and correctly included with its `setup_question` for matching orgs).
    - **Smoke verification**: after deploying, GET `/api/v2/setup-guide/questions` for an `automotive-transport` org with the module not yet enabled — assert the `b2b-fleet-management` question appears with the correct text. For a non-automotive org, assert it is absent.
    - _Implements Requirements: 1.2, 1.3, 1.4_

- [x] 2. Backend module skeleton (`app/modules/fleet_portal/`)
  - [x] 2.1 Create the module package layout
    - Create `app/modules/fleet_portal/__init__.py`, `router.py`, `admin_router.py`, `auth.py`, `dependencies.py`, `models.py`, `schemas.py`, `nzta_template.py`, and the `services/` subfolder with `__init__.py` and one file per service (`account_service.py`, `vehicle_service.py`, `checklist_service.py`, `driver_service.py`, `reminder_service.py`, `booking_service.py`, `quote_service.py`, `invoice_service.py`, `dashboard_service.py`).
    - Wire `router.py` (prefix `/fleet/api`, tag `fleet-portal`) and `admin_router.py` (prefix `/api/v2/fleet-portal/admin`, tag `fleet-portal-admin`) into `app/main.py`.
    - _Implements Requirements: 18.4, 18.5_

  - [x] 2.2 Implement SQLAlchemy ORM models in `models.py`
    - One class per new table matching the schema in design.md. Include all columns, FKs, indexes, and CHECK constraints.
    - Create the new `PortalAccount` ORM model (the foundation table is being created in this migration — see task 1.1).
    - **Add the new models to `app/main.py` model-loading block** (around line 196 after `_staff_models`): `from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401`. This is required so SQLAlchemy can resolve string-based relationship references (the existing comment at `app/main.py:182` already mentions `FleetAccount.organisation` — that comment becomes accurate once this import is added).
    - _Implements Requirements: 1.1, 4.2, 5.2, 8.1, 9.2, 10.3, 11.2, 12.2, 14.1_

  - [x] 2.3 Implement Pydantic schemas in `schemas.py`
    - Request/response schemas for: login, forgot-password, reset-password, accept-invite, current-user, vehicle list/detail, odometer log, hours log, driver invite, driver list item, driver-vehicle assignment, checklist template (with nested items), submission start, submission item update, submission complete, reminder preference (per-vehicle, per-type), booking request, booking list item, quote request, quote detail, invoice list item, dashboard summary, driver activity, paginated list wrapper `{ items, total, limit, offset }`, and error envelope `{ detail }`.
    - Validators: password ≥ 8 and not equal to email local-part; `service_description` length ≥ 10; `preferred_slot ∈ {morning, afternoon, all_day}`; `lead_time_days ∈ {7,14,30}`; `channels ⊆ {email,sms}` and `recipients ⊆ {fleet_admin, assigned_drivers}`; `limit ∈ [1,100]`, `offset ≥ 0`; reject `skip` field with HTTP 422.
    - _Implements Requirements: 3.8, 10.2, 11.1, 11.3, 12.1, 18.1, 18.2, 18.3_

  - [x] 2.4 Implement `nzta_template.py` with the canonical NZTA item set
    - Define `NZTA_ITEMS: list[tuple[str, str, bool]]` exactly as listed in design.md (29 items across 10 categories, each tagged with `requires_photo_on_fail`).
    - Export a helper `nzta_items() -> list[NZTATemplateItem]` returning the canonical list with `display_order` populated 1..N.
    - _Implements Requirements: 8.1, 8.2_

- [x] 3. Authentication, sessions, and dependencies
  - [x] 3.1 Implement password hashing, token generation, and lockout helpers in `auth.py`
    - `hash_password(plaintext) -> str` using passlib bcrypt cost 12.
    - `verify_password(plaintext, hashed) -> bool`.
    - `validate_password_rules(password, email)` raising `ValueError` if length < 8 or lowercase form equals lowercase email local-part.
    - `generate_invite_token() -> str` and `generate_reset_token() -> str` using `secrets.token_urlsafe(32)`.
    - Lockout helpers: `record_failed_attempt(account)`, `check_locked(account)`, `reset_lockout(account)`. Lock at 5 failures with 30-minute window.
    - _Implements Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 3.2 Write property test for auth state machine
    - **Property 6: Login lockout state machine** — Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 4.10
    - **Property 7: Password storage and validation rules** — Validates: Requirements 3.7, 3.8
    - File: `tests/fleet_portal/test_auth_state_machine_property.py`
    - Use hypothesis to generate sequences of login attempts and assert lockout/unlock invariants and bcrypt round-trip.
    - _Implements Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.10_

  - [x] 3.3 Implement Workshop_Org URL resolver
    - Function `resolve_workshop_org_from_request(request) -> Organisation | None` honouring precedence: subdomain (`<slug>.fleet.<domain>`), path (`/fleet/<slug>/...`), then `FLEET_PORTAL_DEFAULT_ORG_SLUG` env. Return `None` (→ 404) on no match.
    - Add the env vars `FLEET_PORTAL_HOST` and `FLEET_PORTAL_DEFAULT_ORG_SLUG` to settings.
    - _Implements Requirements: 2.1, 2.3, 2.4_

  - [x] 3.4 Write property test for URL resolution
    - **Property 4: Workshop_Org URL resolution is deterministic** — Validates: Requirements 2.3, 2.4
    - File: `tests/fleet_portal/test_url_resolution_property.py`
    - Generate hostnames/paths and assert single-org or 404 outcomes; never falls through to staff `/login`.
    - _Implements Requirements: 2.3, 2.4_

  - [x] 3.5 Implement FastAPI dependencies in `dependencies.py`
    - `require_module_enabled` — checks `b2b-fleet-management` enabled for the resolved org; 403 with the disabled-module message; the resolver also handles `/fleet/login` returning 404 when org not found.
    - `require_fleet_portal_session` — reads HttpOnly `fleet_portal_session` cookie, looks up `portal_sessions` rows where `portal_account_id IS NOT NULL` (discriminator from token-link sessions), validates `is_active` on portal_account and fleet_account. After validation, **sets BOTH RLS variables**: `_set_rls_org_id(session, org_id)` AND `_set_rls_fleet_account_id(session, fleet_account_id)`. Also stores both values into the `_current_org_id` and new `_current_fleet_account_id` ContextVars so subsequent calls within the same request see them. Rejects staff JWTs with 401.
    - `require_fleet_admin` — wraps the session dep and rejects `portal_user_role = 'driver'` with 403 "This action requires Fleet Account Admin access".
    - `require_driver_or_admin` — passes both roles; downstream services discriminate.
    - **Reuse existing CSRF infrastructure**: `app/modules/portal/service.py:378-398` already has `validate_portal_csrf(request)` (double-submit cookie). Either factor it out to accept a cookie-name parameter, or write a parallel `validate_fleet_portal_csrf(request)` that reads the `fleet_portal_csrf` cookie (parallel naming, scoped to fleet host so it doesn't cross origins). Reuse the same `secrets.compare_digest` check. Header name stays `X-CSRF-Token`.
    - _Implements Requirements: 1.5, 2.5, 2.6, 3.15, 17.5, 17.6_

  - [x] 3.6 Implement auth endpoints in `router.py`
    - **Reuse `create_portal_session` from `app/modules/portal/service.py:254-280`**: extend it to accept an optional `portal_account_id` parameter (currently takes only `customer_id`), or write a parallel `create_fleet_portal_session(db, portal_account_id) -> tuple[session_token, csrf_token]` following the same shape. Both write to the same `portal_sessions` table; the discriminator column is `portal_account_id IS NOT NULL`.
    - Cookie names: HttpOnly session cookie is `fleet_portal_session`; non-HttpOnly CSRF cookie is `fleet_portal_csrf`. Both scoped to the fleet host (`Path=/` + `Domain=fleet.<domain>` for subdomain mode, `Path=/fleet` for sub-path mode — detect at runtime from `FLEET_PORTAL_HOST`).
    - `POST /fleet/api/auth/login` — rate-limited 10/min/IP; sets HttpOnly cookie; returns user/fleet context.
    - `POST /fleet/api/auth/logout` — destroys session, clears both cookies.
    - `POST /fleet/api/auth/forgot-password` — rate-limited 3/min per email; identical 200 response regardless of email match; persists `reset_token` only on match.
    - `POST /fleet/api/auth/reset-password/{token}` — validates token + freshness, sets password, clears token, resets lockout.
    - `POST /fleet/api/auth/accept-invite/{token}` — validates ≤ 7 days old, sets password, sets `invite_accepted_at`, clears `invite_token`.
    - `GET /fleet/api/me` — returns current portal user + fleet account context (role, name, fleet name, sms_provider_configured).
    - _Implements Requirements: 3.1, 3.2, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 4.4, 4.5, 4.6_

  - [x] 3.7 Write property test for token validity and CSRF
    - **Property 8: Forgot-password is anti-enumerating** — Validates: Requirements 3.9, 3.10
    - **Property 9: Token validity predicate** — Validates: Requirements 3.11, 3.12, 4.4, 4.5, 4.6, 4.9, 5.4
    - **Property 10: CSRF and rate limits gate state-changing requests** — Validates: Requirements 3.14, 3.15
    - File: `tests/fleet_portal/test_token_and_csrf_property.py`
    - _Implements Requirements: 3.9–3.15, 4.4–4.6, 4.9, 5.4_

  - [x] 3.8 Write property test for module + session gating
    - **Property 3: Module-disabled gate is uniform and existence-preserving** — Validates: Requirements 1.5, 1.6, 1.7, 17.6
    - **Property 5: Staff JWTs cannot access fleet portal endpoints** — Validates: Requirements 2.5, 2.6
    - File: `tests/fleet_portal/test_session_gate_property.py`
    - _Implements Requirements: 1.5, 1.6, 1.7, 2.5, 2.6, 17.6_

  - [x] 3.9 Write property test for module gating + dependency
    - **Property 1: Trade-family gating governs both visibility and enableability** — Validates: Requirements 1.2, 1.3
    - **Property 2: Module dependency auto-resolution** — Validates: Requirements 1.4
    - File: `tests/fleet_portal/test_module_gating_property.py`
    - _Implements Requirements: 1.2, 1.3, 1.4_

- [x] 4. Checkpoint — Auth and gating
  - **Scoped test run** (only what tasks 1–3 + 4A touched):
    - Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/fleet_portal/test_module_gating_property.py tests/fleet_portal/test_session_gate_property.py tests/fleet_portal/test_url_resolution_property.py tests/fleet_portal/test_auth_state_machine_property.py tests/fleet_portal/test_token_and_csrf_property.py tests/fleet_portal/test_security_parity_property.py -v --no-header` — runs only the auth/gating/security property files added in this section.
    - Type check: `npx tsc --noEmit` from `frontend/` (no test execution) and from `frontend/src/fleet-portal/` if a sub-package tsconfig was added.
    - Frontend tests for security UI (only if 4B.5 was implemented): `npx vitest run frontend/src/fleet-portal/__tests__/security-ui.property.test.ts`.
  - DO NOT run `pytest tests/` or `npm run test`. If any of the above scoped runs fail, fix and re-run only that file.
  - Ensure all listed scoped tests pass; ask the user if questions arise.

- [x] 4A. Security settings parity — MFA, password policy, lockout, session, audit log
  - [x] 4A.1 Implement password policy enforcement in `auth.py`
    - Replace the simple `validate_password_rules(password, email)` with `validate_password_against_policy(password, email, policy: PasswordPolicy, history: list[str])` that enforces every PasswordPolicy field (`min_length`, `require_uppercase`, `require_lowercase`, `require_digit`, `require_special`, `expiry_days`, `history_count`, `require_not_pwned`).
    - Implement HIBP k-anonymity check: SHA-1 the candidate password, send the first 5 hex chars to `https://api.pwnedpasswords.com/range/{prefix}`, check if the suffix appears in the response. Cache results in Redis for 24 hours per prefix bucket. Use `httpx.AsyncClient` as a context manager with a 5-second timeout.
    - Implement password history check: query `portal_account_password_history` for the last `history_count` rows for the account; bcrypt-verify each against the candidate; reject on match with message "You cannot reuse a recent password.".
    - On successful password change, append the **old** hash to history and FIFO-evict any rows beyond `history_count`.
    - _Implements Requirements: 21.3, 21.4, 21.5, 21.6_

  - [x] 4A.2 Implement TOTP MFA enrolment and verification
    - Reuse the staff `app/modules/auth/mfa_service.py` patterns. Mirror the `_store_challenge_session` Redis flow but rooted at `portal_account_id`.
    - Service functions: `start_totp_enrolment(portal_account_id) -> {secret, qr_code_data_uri}`, `confirm_totp_enrolment(portal_account_id, code) -> PortalAccountMfaMethod`, `verify_totp(portal_account_id, code) -> bool`, `remove_mfa_method(portal_account_id, method_id)`.
    - Encrypt the TOTP secret using the existing `app/core/encryption.envelope_encrypt_str` (the pattern from `integration-credentials-architecture.md`). Never store the raw secret.
    - Endpoints: `POST /fleet/api/auth/mfa/enroll/totp/start`, `POST /fleet/api/auth/mfa/enroll/totp/confirm`, `POST /fleet/api/auth/mfa/verify`, `DELETE /fleet/api/auth/mfa/{method_id}`, `GET /fleet/api/auth/mfa/methods`.
    - _Implements Requirements: 21.10, 21.13, 21.14_

  - [x] 4A.3 Implement SMS MFA enrolment and verification
    - Add `start_sms_enrolment(portal_account_id, phone) -> challenge_token` (sends 6-digit code via existing Connexus integration; rejects with HTTP 400 if no SMS provider).
    - Add `confirm_sms_enrolment(portal_account_id, code) -> PortalAccountMfaMethod`.
    - Endpoints: `POST /fleet/api/auth/mfa/enroll/sms/start`, `POST /fleet/api/auth/mfa/enroll/sms/confirm`.
    - _Implements Requirements: 21.11_

  - [x] 4A.4 Implement backup codes
    - On first MFA enrolment (TOTP or SMS), generate 10 random codes (`secrets.token_urlsafe(8)`), bcrypt-hash and persist to `portal_account_backup_codes`.
    - Endpoint: `GET /fleet/api/auth/mfa/backup-codes` (admin/self only; returns codes once on generation, not on read), `POST /fleet/api/auth/mfa/backup-codes/regenerate` (replaces existing codes).
    - During login, if the user provides a backup code instead of an OTP, verify against any unconsumed `code_hash` and mark consumed in the same transaction.
    - _Implements Requirements: 21.12_

  - [x] 4A.5 Update lockout to support permanent lock
    - Extend `auth.py` lockout helpers: when `failed_login_attempts >= permanent_lock_threshold`, set `is_locked_permanently = true`. Login attempts on permanently-locked accounts return HTTP 403 with message "Your account is locked. Please contact the workshop." and do not auto-unlock.
    - Workshop_Admin can manually unlock via the portal account detail page (sets `failed_login_attempts = 0`, `locked_until = NULL`, `is_locked_permanently = false`, audit-logs `portal_auth.account_unlocked`).
    - _Implements Requirements: 21.7, 21.18_

  - [x] 4A.6 Implement session policy enforcement
    - On login success, count active sessions for the portal account; if count >= `max_sessions_per_user`, delete the oldest session (FIFO) before creating the new one.
    - Update the session validity check to consider `idle_timeout_minutes` (touch `last_activity_at` on every request; reject sessions where `now - last_activity_at > idle_timeout_minutes`).
    - **Replace the hardcoded 4-hour idle timeout in `app/modules/portal/service.py`**: locate the existing 4-hour timeout (search for `4 * 60` or `timedelta(hours=4)` in the portal service), and for sessions where `portal_account_id IS NOT NULL` (fleet portal sessions), read `idle_timeout_minutes` from `org.settings.portal_security_policy.session_policy.idle_timeout_minutes` instead. Keep the 4-hour default for token-link sessions where `portal_account_id IS NULL`.
    - Endpoint `GET /fleet/api/auth/sessions` (lists current account's sessions), `DELETE /fleet/api/auth/sessions/{session_id}` (revoke specific session), `DELETE /fleet/api/auth/sessions/all` (revoke all except current).
    - _Implements Requirements: 21.8, 21.16_

  - [x] 4A.7 Implement audit log
    - Add `app/modules/fleet_portal/services/audit_service.py` with `log_event(db, *, org_id, portal_account_id, actor_user_id, action, ip, ua, details)`.
    - Wire into every auth endpoint (login success/fail, MFA verified/failed, password changed/reset, session revoked, account locked/unlocked, MFA enrolled/disabled).
    - Endpoint `GET /fleet/api/auth/audit` (current account's last 50 events, self-view), `GET /api/v2/fleet-portal/admin/accounts/{portal_account_id}/audit` (admin view, last 90 days).
    - _Implements Requirements: 21.15, 21.17_

  - [x] 4A.8 Implement portal_security_policy CRUD endpoints
    - Add to `admin_router.py`: `GET /api/v2/fleet-portal/admin/security-policy` (returns the policy from `org_settings.portal_security_policy`), `PUT /api/v2/fleet-portal/admin/security-policy` (validates against the `OrgSecuritySettings`-shaped Pydantic schema, persists to `organisations.settings`).
    - On update, audit-log the change with before/after diff (mirror the staff `org.security_settings_updated` pattern).
    - _Implements Requirements: 21.1, 21.2_

  - [x] 4A.9 Implement Workshop_Admin-side MFA / password reset / unlock / impersonation actions
    - `POST /api/v2/fleet-portal/admin/accounts/{portal_account_id}/unlock` — manually unlock.
    - `POST /api/v2/fleet-portal/admin/accounts/{portal_account_id}/force-mfa-reenroll` — deletes all `portal_account_mfa_methods` rows.
    - `POST /api/v2/fleet-portal/admin/accounts/{portal_account_id}/admin-reset-password` — admin sets a new password (per the kiosk-password-reset spec pattern), sets `must_change_password = true`, deletes all sessions, sends an email with the new password and a "must change on next login" notice.
    - `POST /api/v2/fleet-portal/admin/accounts/{portal_account_id}/start-impersonation` — creates a 15-minute impersonation session, audit-logs `portal_auth.impersonation_started`, returns a one-time impersonation token.
    - `POST /api/v2/fleet-portal/admin/accounts/{portal_account_id}/end-impersonation` — destroys the session, audit-logs `portal_auth.impersonation_ended`.
    - All admin routes are `RequireOrgAdmin` and module-gated. State-changing portal API calls reject when the session is impersonation (HTTP 403, "Impersonation is read-only").
    - _Implements Requirements: 21.18, 21.19, 21.20, 21.21_

  - [x] 4A.10 Write property tests for security parity
    - **Property 35: Configurable password policy enforcement** — generate random policies and password candidates; assert that bcrypt-stored password verifies and that violations are rejected with the correct message.
    - **Property 36: Configurable lockout policy** — generate sequences of login attempts under random `(temp_threshold, perm_threshold, temp_minutes)` configs and assert state transitions (unlocked → temp-locked → unlocked-after-timeout → permanently-locked-after-perm-threshold).
    - **Property 37: Session policy enforcement** — generate sequences of login events with random `max_sessions` and `idle_timeout` and assert FIFO eviction and idle-timeout cutoff.
    - **Property 38: MFA mode enforcement** — for each (mode, role) pair, assert that login behaves correctly (allow / require enrolment / require verification / fail).
    - **Property 39: HIBP breach check** — using a stub HIBP responder, generate password candidates and assert that the breached ones are rejected and clean ones accepted; assert cache prefix bucketing is k-anonymous (only 5-char prefix sent over wire).
    - File: `tests/fleet_portal/test_security_parity_property.py`
    - _Implements Requirements: 21.3–21.16_

- [x] 4B. Frontend — Security settings UI
  - [x] 4B.1 Create the Workshop_Admin Portal Settings page
    - File: `frontend/src/fleet-portal-admin/pages/PortalSecuritySettings.tsx`. Mirror the staff `OrgSecuritySettings` page UI (existing in `frontend/src/pages/settings/SecuritySettings.tsx` if available — read it first per `no-shortcut-implementations.md`).
    - Form sections: MFA Policy, Password Policy, Lockout Policy, Session Policy. Save calls `PUT /api/v2/fleet-portal/admin/security-policy`.
    - Wrap in `<ModuleGate module="b2b-fleet-management">`. Route: `/fleet-portal-admin/security-policy`.
    - Add nav item to OrgLayout sidebar under "Fleet Portal" group.
    - _Implements Requirements: 21.2_

  - [x] 4B.2 Create the Portal_User Account Detail page (admin)
    - File: `frontend/src/fleet-portal-admin/pages/PortalAccountDetail.tsx`. Route: `/fleet-portal-admin/accounts/:portal_account_id`.
    - Sections: Status & last login, Active sessions (with revoke), MFA methods (with force re-enrol), Password (with admin reset), Audit log (last 90 days, paginated), Impersonate button.
    - Apply safe-API consumption rules.
    - _Implements Requirements: 21.17, 21.18, 21.19, 21.20, 21.21_

  - [x] 4B.3 Create the Portal_User "My Security" page (self-service)
    - File: `frontend/src/fleet-portal/pages/MySecurity.tsx`. Route: `/fleet/security`.
    - Sections: Change Password, MFA Methods (enrol/remove), Backup Codes (view-on-generate), Active Sessions (revoke), Recent Login Events.
    - Sub-routes: `/fleet/security/mfa/enroll/totp` (QR + 6-digit confirm), `/fleet/security/mfa/enroll/sms` (phone + 6-digit confirm), `/fleet/security/mfa/backup-codes` (one-time view).
    - All forms use `?.` and `?? []` patterns; `useEffect` with `AbortController`.
    - _Implements Requirements: 21.16_

  - [x] 4B.4 Update the Login flow to handle MFA challenge
    - When `POST /fleet/api/auth/login` returns `{ mfa_required: true, mfa_token, mfa_methods, default_method }`, navigate to `/fleet/login/mfa-verify` with the token in route state. The verify form posts to `POST /fleet/api/auth/mfa/verify` with `{ mfa_token, code, method }`. On success, sets the session cookie and redirects to dashboard.
    - When the response is `{ mfa_setup_required: true, mfa_token }`, redirect to `/fleet/security/mfa/enroll/totp` with the token; only allow access to that page until enrolment completes.
    - _Implements Requirements: 21.13, 21.14_

  - [x] 4B.5 Frontend property tests for security UI
    - Test that the password change form rejects passwords violating each policy clause; test that the MFA challenge flow handles all branches; test that the impersonation banner is shown and read-only is enforced.
    - File: `frontend/src/fleet-portal/__tests__/security-ui.property.test.ts`
    - _Implements Requirements: 21.4, 21.13, 21.16, 21.21_

- [x] 5. Fleet account provisioning and role gating
  - [x] 5.1 Implement `account_service.py`
    - `invite_fleet_admin(org_id, customer_id, invited_by_user_id)` — verifies `customer.customer_type == 'business'`; idempotent on `(org_id, customer_id)` for `fleet_accounts`; creates `portal_accounts` with `portal_user_role='fleet_admin'`, `invite_token`, `invite_sent_at`; sends invite email through the existing email-provider failover.
    - `accept_invite(invite_token, new_password)` — validates token freshness, sets password (calls `auth.validate_password_rules`), sets `invite_accepted_at`, clears `invite_token`. Use `await db.flush()` then `await db.refresh(account)` before return.
    - `revoke_access(portal_account_id)` — sets `is_active=False` and deletes all `portal_sessions` for that account in the same transaction.
    - `resend_invite(portal_account_id)` — generates fresh `invite_token`, updates `invite_sent_at`, re-sends email.
    - _Implements Requirements: 4.2, 4.3, 4.6, 4.8, 4.9_

  - [x] 5.2 Implement admin invite/revoke endpoints in `admin_router.py`
    - `POST /api/v2/fleet-portal/admin/invite` (Workshop_Admin only, JWT-authenticated, module-gated).
    - `POST /api/v2/fleet-portal/admin/revoke/{portal_account_id}`.
    - `POST /api/v2/fleet-portal/admin/resend-invite/{portal_account_id}`.
    - `GET /api/v2/fleet-portal/admin/accounts` — paginated `{ items, total, limit, offset }` of fleet accounts with portal status, vehicle count, driver count, last login.
    - _Implements Requirements: 4.1, 4.2, 4.3, 4.7, 4.8, 4.9, 16.6_

  - [x] 5.3 Write unit tests for account_service
    - Test: invite reuses existing `fleet_account` for same `(org_id, customer_id)`; non-business customer rejected with 400; revoke deletes sessions; expired invite is rejected.
    - _Implements Requirements: 4.2, 4.3, 4.6, 4.8_

- [x] 6. Vehicle access (admin and driver views)
  - [x] 6.1 Implement `vehicle_service.py`
    - `list_vehicles_for_session(session_ctx, offset, limit)` — admin sees full fleet (filter by `org_id` AND `customer_id`); driver sees only vehicles joined via `fleet_driver_assignments`.
    - `get_vehicle(session_ctx, customer_vehicle_id)` — 404 on cross-tenant or missing driver assignment.
    - `add_vehicle_to_fleet(session_ctx, rego)` — looks up via existing CarJam pathway, creates `customer_vehicles` link, creates default-disabled `fleet_reminder_preferences` rows for `wof`, `cof`, `service_due`.
    - `update_vehicle_fields(session_ctx, customer_vehicle_id, payload)` — applies the per-role allowlist; 403 on disallowed fields.
    - `log_odometer_reading(session_ctx, customer_vehicle_id, value_km)` — strict `>` previous max; persists to existing `odometer_readings` table.
    - `log_driver_hours(session_ctx, customer_vehicle_id, start_at, end_at, notes)` — driver-only; writes `fleet_driver_hours` row.
    - `unlink_vehicle(session_ctx, customer_vehicle_id)` — admin-only soft-unlink (does not delete `global_vehicles`).
    - _Implements Requirements: 6.1, 6.2, 6.5, 6.6, 6.7, 6.9, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.9_

  - [x] 6.2 Implement vehicle endpoints in `router.py`
    - `GET /fleet/api/vehicles` (paginated), `GET /fleet/api/vehicles/{id}`, `POST /fleet/api/vehicles` (admin), `PATCH /fleet/api/vehicles/{id}`, `DELETE /fleet/api/vehicles/{id}` (admin), `POST /fleet/api/vehicles/{id}/odometer`, `POST /fleet/api/vehicles/{id}/hours` (driver-only).
    - All list responses use `{ items, total, limit, offset }`.
    - _Implements Requirements: 6.1–6.9, 7.1–7.8, 18.1, 18.2_

  - [x] 6.3 Implement expiry-badge utility
    - Add `app/modules/fleet_portal/services/expiry.py` with `badge(expiry_date, today) -> 'red' | 'amber' | 'green'` using the rules: `< today → red`; `today ≤ d ≤ today+28 → amber`; otherwise `green`.
    - Reuse in vehicle list response and dashboard service.
    - _Implements Requirements: 6.3, 6.4, 7.8_

  - [x] 6.4 Write property test for vehicle edit allowlist + odometer monotonicity
    - **Property 14: Per-role field allowlist for vehicle edits** — Validates: Requirements 6.6, 7.2, 7.3, 7.4
    - **Property 15: Odometer monotonicity** — Validates: Requirements 7.6, 7.7
    - File: `tests/fleet_portal/test_vehicle_edit_property.py`
    - _Implements Requirements: 6.6, 7.2, 7.3, 7.4, 7.6, 7.7_

  - [x] 6.5 Write property test for tenant isolation
    - **Property 12: Tenant and fleet isolation** — Validates: Requirements 6.9, 13.6, 17.1, 17.2, 17.3
    - File: `tests/fleet_portal/test_tenant_isolation_property.py`
    - Generate cross-org/cross-fleet access attempts and assert 404 (not 403) on every fleet-scoped resource.
    - _Implements Requirements: 6.9, 13.6, 17.1, 17.2, 17.3_

  - [x] 6.6 Write property test for driver-vehicle visibility
    - **Property 13: Driver-vehicle visibility via assignments** — Validates: Requirements 5.5, 5.6, 5.8, 7.1, 9.1, 17.4
    - File: `tests/fleet_portal/test_driver_assignment_property.py`
    - _Implements Requirements: 5.5, 5.6, 5.8, 7.1, 9.1, 17.4_

  - [x] 6.7 Write property test for role gate
    - **Property 11: Role gate — driver vs. fleet_admin** — Validates: Requirements 5.1, 12.1, 13.7, 14.1, 17.5
    - File: `tests/fleet_portal/test_role_gate_property.py`
    - _Implements Requirements: 5.1, 12.1, 13.7, 14.1, 17.5_

- [x] 7. Drivers management (Fleet_Account_Admin)
  - [x] 7.1 Implement `driver_service.py`
    - `invite_driver(session_ctx, first_name, last_name, email, phone)` — duplicate-email-in-org check returning 409; creates `portal_accounts` with role `driver`, `fleet_account_id` from session, `invite_token`.
    - `assign_vehicle(session_ctx, portal_account_id, customer_vehicle_id)` — admin-only; idempotent (unique on `(portal_account_id, customer_vehicle_id)`).
    - `unassign_vehicle(session_ctx, portal_account_id, customer_vehicle_id)`.
    - `deactivate_driver(session_ctx, portal_account_id)` — admin-only; sets `is_active=False`; deletes sessions.
    - `list_drivers_with_activity(session_ctx)` — joins to `fleet_driver_assignments`, last login, last submission.
    - `driver_activity_aggregate(session_ctx, portal_account_id, date_from, date_to)` — implements Property 33 aggregations.
    - `driver_activity_csv(session_ctx, portal_account_id, date_from, date_to)` — one row per `(date, vehicle)` pair.
    - _Implements Requirements: 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.9, 14.1, 14.2, 14.3, 14.4, 14.5_

  - [x] 7.2 Implement driver endpoints in `router.py`
    - `GET /fleet/api/drivers` (admin), `POST /fleet/api/drivers/invite` (admin), `POST /fleet/api/drivers/{id}/assignments` (admin), `DELETE /fleet/api/drivers/{id}/assignments/{vehicle_id}` (admin), `POST /fleet/api/drivers/{id}/deactivate` (admin), `GET /fleet/api/drivers/{id}/activity` (admin), `GET /fleet/api/drivers/{id}/activity.csv` (admin).
    - _Implements Requirements: 5.1, 5.2, 5.3, 5.5–5.7, 5.9, 14.1–14.5_

  - [x] 7.3 Write property test for activity aggregation
    - **Property 33: Activity aggregation for drivers** — Validates: Requirements 14.2, 14.3, 14.4, 14.5
    - File: `tests/fleet_portal/test_activity_aggregation_property.py`
    - _Implements Requirements: 14.2, 14.3, 14.4, 14.5_

- [x] 8. NZTA seeding and checklist templates
  - [x] 8.1 Implement template lifecycle in `checklist_service.py`
    - `seed_nzta_default_for_fleet(org_id, fleet_account_id)` — idempotent; creates one `is_system_seeded=true, is_default=true` template using items from `nzta_template.py` if none exists.
    - Hook the seed call into `require_fleet_portal_session` (run-once-per-fleet on first fleet-admin authenticated request) using a `fleet_accounts.nzta_seeded_at` timestamp or equivalent guard, set within the same transaction.
    - `clone_template(template_id)` — copies template + items into a fresh non-system, non-default template.
    - `set_default_template(template_id)` — admin-only; clears any existing default for the fleet within the same transaction.
    - `create_template`, `update_template`, `archive_template`, `delete_template` — admin-only; reject edits to system-seeded templates; reject hard-delete when non-archived submissions reference the template (offer archive instead).
    - `add_item`, `update_item`, `reorder_items`, `delete_item` — operate only on non-system, non-archived templates; preserve `display_order` invariants.
    - `assign_template_to_vehicle(customer_vehicle_id, template_id)` — sets `customer_vehicles.fleet_checklist_template_id`. **Verify first**: this column likely does NOT exist yet — if absent, add it in migration `0191` (task 1.1) as `fleet_checklist_template_id UUID NULL` with FK to `fleet_checklist_templates(id) ON DELETE SET NULL`. Use `ALTER TABLE customer_vehicles ADD COLUMN IF NOT EXISTS ...`.
    - `resolve_template_for_vehicle(customer_vehicle_id)` — Property 20 precedence: vehicle override → fleet default → NZTA seed.
    - _Implements Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_

  - [x] 8.2 Implement template endpoints in `router.py`
    - `GET /fleet/api/checklists/templates` (admin), `POST /fleet/api/checklists/templates` (admin), `GET /fleet/api/checklists/templates/{id}` (admin), `PATCH /fleet/api/checklists/templates/{id}` (admin), `POST /fleet/api/checklists/templates/{id}/clone` (admin), `POST /fleet/api/checklists/templates/{id}/set-default` (admin), `POST /fleet/api/checklists/templates/{id}/archive` (admin), `DELETE /fleet/api/checklists/templates/{id}` (admin).
    - Item endpoints: `POST/PATCH/DELETE /fleet/api/checklists/templates/{id}/items[/{item_id}]`, plus `POST /fleet/api/checklists/templates/{id}/items/reorder`.
    - _Implements Requirements: 8.3, 8.4, 8.5, 8.7, 8.8_

  - [x] 8.3 Write property tests for templates
    - **Property 18: NZTA seed is idempotent and complete** — Validates: Requirements 8.1, 8.2, 8.3, 8.8
    - **Property 19: At-most-one default checklist template per fleet** — Validates: Requirements 8.5
    - **Property 20: Template resolution for submissions** — Validates: Requirements 8.6
    - **Property 21: Template item CRUD round-trip** — Validates: Requirements 8.4
    - **Property 22: Templates referenced by submissions cannot be hard-deleted** — Validates: Requirements 8.7, 9.10
    - File: `tests/fleet_portal/test_checklist_template_property.py`
    - _Implements Requirements: 8.1–8.8, 9.10_

- [x] 9. Checklist submissions (driver flow + photo upload)
  - [x] 9.1 Implement submission lifecycle in `checklist_service.py`
    - `start_submission(session_ctx, customer_vehicle_id)` — driver must have an assignment for the vehicle (Property 13); resolves template via Property 20; creates `fleet_checklist_submissions` (status `in_progress`, `started_at=now()`) + one `fleet_checklist_submission_items` row per template item (snapshotting `category`, `label`, `requires_photo_on_fail`).
    - `update_submission_item(submission_id, item_id, result, notes)` — only while `status='in_progress'` and only by the submission's `portal_account_id`.
    - `upload_item_photo(submission_id, item_id, file)` — validates `image/*` MIME, ≤ 8 MB; saves via existing storage adapter; appends URL to `photo_urls` jsonb.
    - `complete_submission(submission_id)` — validates Property 23 photo predicate; sets counts, `completed_at`, `status='completed'`; emits `fleet_checklist_failure` notification iff `failed_item_count > 0`.
    - `list_submissions(session_ctx, filters)` — drivers see only own; admins see all in fleet; supports vehicle, driver, date-range, has-failure filters; paginated.
    - _Implements Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10_

  - [x] 9.2 Implement submission endpoints in `router.py`
    - `POST /fleet/api/checklists/start`, `PATCH /fleet/api/checklists/{id}/items/{item_id}`, `POST /fleet/api/checklists/{id}/items/{item_id}/photo` (multipart), `POST /fleet/api/checklists/{id}/complete`, `GET /fleet/api/checklists/submissions` (paginated), `GET /fleet/api/checklists/submissions/{id}`.
    - _Implements Requirements: 9.1–9.10_

  - [x] 9.3 Write property test for submission completion + photo enforcement
    - **Property 23: Photo evidence enforcement at completion** — Validates: Requirements 9.2, 9.3, 9.4, 9.5
    - **Property 24: Submission completion finalises counts and emits exactly the failure-driven notification** — Validates: Requirements 9.6, 9.7
    - File: `tests/fleet_portal/test_submission_completion_property.py`
    - _Implements Requirements: 9.2–9.7_

- [x] 10. Reminder preferences and Celery Beat integration
  - [x] 10.1 Implement `reminder_service.py`
    - `upsert_preference(...)` — validates Property 25 predicate, including `sms_provider_configured` check via the existing org SMS settings; rejects writes that violate any clause; round-trippable on accept.
    - `list_preferences(session_ctx)` — returns one row per `(vehicle, reminder_type)`, defaulting missing rows to `enabled=false`.
    - `compute_service_due_date(last_service_at, last_odometer, current_odometer, interval_km, interval_months)` — Property 27 math; returns `NULL` when neither interval is set. Writes back to the underlying `global_vehicles.service_due_date` / `org_vehicles.service_due_date` (the existing column — do NOT create a new `next_service_due_at`).
    - `send_ad_hoc_sms(session_ctx, vehicle_id, message)` — admin-only; rejects with 400 if no SMS provider; routes through existing Connexus integration.
    - `default_preferences_for_new_vehicle(...)` — already wired from `add_vehicle_to_fleet` (creates three rows with `enabled=false`).
    - _Implements Requirements: 10.1, 10.2, 10.3, 10.6, 10.7, 10.8, 10.9_

  - [x] 10.2 Extend `notifications.reminder_queue_service` to read `fleet_reminder_preferences`
    - **Read `app/modules/notifications/reminder_queue_service.py` and `enqueue_customer_reminders()` first** (per `no-shortcut-implementations.md`). The reminder system is a two-phase queue: Phase 1 renders the email/SMS body at queue time using org-level templates; Phase 2 sends the pre-rendered body. Existing reminder types are `wof_expiry_reminder`, `cof_expiry_reminder`, `registration_expiry_reminder`, `service_due_reminder` (`app/modules/notifications/schemas.py:27-32`). Existing settings live at `notifications/wof-rego-settings` (org-wide).
    - Extend `enqueue_customer_reminders()` to ALSO scan `fleet_reminder_preferences` rows. For each enabled preference matching today (using existing date columns: `wof_expiry`, `cof_expiry`, `service_due_date` — NOT a new `next_service_due_at`), enqueue a reminder using the **existing template resolution path** (`resolve_template(db, org_id=..., template_type='wof_expiry_reminder' | 'cof_expiry_reminder' | 'service_due_reminder' | 'registration_expiry_reminder', channel=..., variables={...})`).
    - Reuse the existing template variables: `customer_first_name`, `customer_last_name`, `vehicle_rego`, `vehicle_make`, `vehicle_model`, `expiry_date` (for WOF/COF/registration) or `service_due_date` (for service), `org_name`, `org_phone`, `org_email`. Don't invent new variable names.
    - Idempotency: **reuse the existing `reminder_queue` table's `INSERT ... ON CONFLICT DO NOTHING` mechanism** keyed on `(customer_id, vehicle_id, reminder_type, scheduled_date)` (verified in `app/modules/notifications/reminder_queue_service.py:424-430`). When a `fleet_reminder_preferences` row enqueues a reminder, write `customer_id = fleet_account.customer_id` (the same customer that owns the vehicle), `vehicle_id = customer_vehicle.global_vehicle_id` (or `org_vehicle_id`, matching the existing column), `reminder_type = pref.reminder_type` (one of the four full names), `scheduled_date = today`. The conflict resolution naturally dedups across the org-wide and per-fleet enqueue paths — do NOT add a second dedup key. Failures are recorded on the same `reminder_queue` row (`status = 'failed'`, `attempt_count`, `last_error`); there is no separate `notification_audit_log` table.
    - Per-vehicle override semantics: when a `fleet_reminder_preferences` row is enabled for a vehicle, it overrides the org-wide `wof_rego_settings` for that vehicle (so the customer's preference wins).
    - Retry policy is unchanged from the existing queue (Phase 2's exponential-backoff retry already covers SMTP/SMS failures — don't reimplement).
    - _Implements Requirements: 10.4, 10.5, 10.6, 10.10_

  - [x] 10.3 Implement reminder endpoints in `router.py`
    - `GET /fleet/api/reminders` (admin), `PUT /fleet/api/reminders/{vehicle_id}/{reminder_type}` (admin), `POST /fleet/api/reminders/{vehicle_id}/sms-now` (admin, body: message).
    - _Implements Requirements: 10.1, 10.2, 10.7, 10.8_

  - [x] 10.4 Write property test for reminder preference validity + defaults
    - **Property 25: Reminder preference validity** — Validates: Requirements 10.2, 10.3, 10.8
    - **Property 28: Reminder defaults are off on add-vehicle** — Validates: Requirements 10.9
    - File: `tests/fleet_portal/test_reminder_validation_property.py`
    - _Implements Requirements: 10.2, 10.3, 10.8, 10.9_

  - [x] 10.5 Write property test for reminder idempotency + retry
    - **Property 26: Reminder firing is idempotent per (vehicle, type, expiry_date)** — Validates: Requirements 10.4, 10.5, 10.6
    - **Property 29: Reminder retry policy** — Validates: Requirements 10.10
    - File: `tests/fleet_portal/test_reminder_idempotence_property.py`
    - _Implements Requirements: 10.4, 10.5, 10.6, 10.10_

  - [x] 10.6 Write property test for service-due math
    - **Property 27: Service-due math** — Validates: Requirements 10.6
    - File: `tests/fleet_portal/test_service_due_math_property.py`
    - _Implements Requirements: 10.6_

- [x] 11. Checkpoint — Core fleet domain
  - **Scoped test run** (only what tasks 5–10 touched):
    - Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/fleet_portal/test_role_gate_property.py tests/fleet_portal/test_tenant_isolation_property.py tests/fleet_portal/test_driver_assignment_property.py tests/fleet_portal/test_vehicle_edit_property.py tests/fleet_portal/test_dashboard_aggregation_property.py tests/fleet_portal/test_checklist_template_property.py tests/fleet_portal/test_submission_completion_property.py tests/fleet_portal/test_reminder_validation_property.py tests/fleet_portal/test_reminder_idempotence_property.py tests/fleet_portal/test_service_due_math_property.py tests/fleet_portal/test_activity_aggregation_property.py -v --no-header`
    - Quick alternative for the same scope: `pytest tests/fleet_portal/ -v --no-header -k "not security_parity and not module_gating and not session_gate and not url_resolution and not auth_state_machine and not token_and_csrf"` (runs everything in `tests/fleet_portal/` EXCEPT the section-1 files which were already covered at task 4).
    - Verify the existing `notifications.reminder_queue_service` integration didn't regress: `pytest tests/ -k "reminder_queue" --no-header -q` (runs only reminder-queue tests across the repo).
    - Type check: `npx tsc --noEmit` from `frontend/`.
  - DO NOT run `pytest tests/` or `npm run test`.
  - Ensure all listed scoped tests pass; ask the user if questions arise.

- [x] 12. Booking and quote requests
  - [x] 12.1 Implement `booking_service.py`
    - `create_booking_request(session_ctx, vehicle_id, preferred_date, preferred_slot, service_description, notes)` — validates Property 30 predicate (vehicle accessible to user, date today-or-later in workshop tz, slot enum, description ≥ 10 chars); inserts row and emits `fleet_booking_request` notification to all Workshop_Admins.
    - `cancel_booking_request(session_ctx, request_id)` — requester only, while still pending.
    - `accept_booking_request(workshop_admin_ctx, request_id, refined_date_time)` — creates draft `bookings` row, links via `booking_id`, sets status `accepted`, emails requester.
    - `decline_booking_request(workshop_admin_ctx, request_id, decline_reason)` — sets status `declined`, emails requester.
    - `list_for_fleet(session_ctx)`, `list_for_org(workshop_admin_ctx)` — paginated.
    - _Implements Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_

  - [x] 12.2 Implement `quote_service.py`
    - `create_quote_request(session_ctx, vehicle_id, service_description, notes)` — admin-only; same vehicle/description predicates as booking; emits `fleet_quote_request` notification.
    - `link_quote(workshop_admin_ctx, request_id, quote_id)` — sets status `quoted`, emails fleet admin.
    - `accept_quote(session_ctx, request_id)` — admin-only; uses existing portal-quote acceptance path; sets request status `accepted`; rejects if linked quote `valid_until < now()`.
    - `decline_quote(session_ctx, request_id)` — admin-only; uses existing portal-quote decline path; sets request status `declined`.
    - State-machine guard: reject any transition not in Property 31's allowed set.
    - `list_for_fleet`, `list_for_org` — paginated.
    - _Implements Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [x] 12.3 Implement booking & quote endpoints in `router.py` and `admin_router.py`
    - Portal: `POST /fleet/api/bookings`, `GET /fleet/api/bookings`, `POST /fleet/api/bookings/{id}/cancel`, `POST /fleet/api/quotes/request` (admin), `GET /fleet/api/quotes` (admin), `GET /fleet/api/quotes/{id}` (admin), `POST /fleet/api/quotes/{id}/accept` (admin), `POST /fleet/api/quotes/{id}/decline` (admin).
    - Admin: `GET /api/v2/fleet-portal/admin/bookings`, `POST /api/v2/fleet-portal/admin/bookings/{id}/accept`, `POST /api/v2/fleet-portal/admin/bookings/{id}/decline`, `GET /api/v2/fleet-portal/admin/quotes`, `POST /api/v2/fleet-portal/admin/quotes/{id}/link`.
    - _Implements Requirements: 11.4, 11.5, 11.6, 11.7, 11.8, 12.3, 12.4, 16.2, 16.3, 16.4_

  - [x] 12.4 Write property test for booking/quote request and state machines
    - **Property 30: Booking/Quote request validation predicate** — Validates: Requirements 11.1, 11.2, 11.3, 12.1, 12.2
    - **Property 31: Booking/Quote status state machines** — Validates: Requirements 11.4, 11.5, 11.6, 11.8, 12.3, 12.5, 12.6, 12.7
    - File: `tests/fleet_portal/test_request_state_machines_property.py`
    - _Implements Requirements: 11.1–11.8, 12.1–12.7_

- [x] 13. Invoices and dashboard
  - [x] 13.1 Implement `invoice_service.py` (delegates to existing portal invoice service)
    - `list_invoices(session_ctx, status_filter, offset, limit)` — admin-only; reuses the existing portal invoice service filtered by `org_id` and the fleet account's `customer_id`.
    - `get_invoice(session_ctx, invoice_id)` — admin-only.
    - `get_invoice_pdf(session_ctx, invoice_id)` — admin-only; calls existing `get_portal_invoice_pdf`.
    - _Implements Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 13.2 Implement `dashboard_service.py`
    - `admin_dashboard(session_ctx)` — returns the summary card values from Property 17, the recent-failure panel (last 10 failed submissions), pending-bookings count, pending-quotes count.
    - `driver_dashboard(session_ctx)` — assigned vehicles, today's checklist status per vehicle, next assigned shift if any.
    - _Implements Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

  - [x] 13.3 Implement dashboard + invoice endpoints in `router.py`
    - `GET /fleet/api/dashboard` (role-aware), `GET /fleet/api/invoices` (admin), `GET /fleet/api/invoices/{id}` (admin), `GET /fleet/api/invoices/{id}/pdf` (admin).
    - _Implements Requirements: 13.1–13.7, 15.1–15.6_

  - [x] 13.4 Write property test for dashboard aggregations + badge function
    - **Property 16: Expiry-status badge function** — Validates: Requirements 6.3, 6.4, 7.8
    - **Property 17: Fleet summary aggregations** — Validates: Requirements 6.8, 15.2, 15.3, 15.4, 15.5, 15.6
    - File: `tests/fleet_portal/test_dashboard_aggregation_property.py`
    - _Implements Requirements: 6.3, 6.4, 6.8, 7.8, 15.2–15.6_

  - [x] 13.5 Write property test for pagination shape
    - **Property 32: Pagination and list response shape** — Validates: Requirements 13.1, 13.3, 18.1, 18.2
    - File: `tests/fleet_portal/test_pagination_property.py`
    - _Implements Requirements: 13.1, 13.3, 18.1, 18.2_

- [x] 14. Frontend — Fleet Portal SPA scaffold
  - [x] 14.1 Set up `frontend/src/fleet-portal/` package
    - **Read `frontend/src/App.tsx` first** (per `no-shortcut-implementations.md`) to understand the existing `<RequireAuth>`, `<RequireOrgAdmin>`, `<RequireGlobalAdmin>` patterns before creating the symmetric portal guards.
    - Create `FleetPortalApp.tsx`, `FleetPortalLayout.tsx`, `FleetPortalRouter.tsx` with the sidebar (Dashboard, Vehicles, Checklists, Drivers, Bookings, Quotes, Invoices, Reminders, Profile, Security).
    - Create route guards in `frontend/src/fleet-portal/guards/`:
      - `RequireFleetSession` — redirects to `/fleet/login` if no `FleetSessionContext.account`.
      - `RequireFleetAdmin` — wraps `RequireFleetSession` and redirects to `/fleet/dashboard` (with toast) if `account.portal_user_role !== 'fleet_admin'`.
      - `RequireDriverOrAdmin` — wraps `RequireFleetSession` (no extra check; symmetric with `RequireFleetSession` but explicit for readability).
      - `RequireNotImpersonating` — used on state-changing routes; reads `account.is_impersonation` and shows a read-only banner instead of the form.
    - In `frontend/src/App.tsx`, add a top-level switch: when `window.location.host.startsWith('fleet.')` or `window.location.pathname.startsWith('/fleet')`, render `<FleetPortalRouter>` instead of `OrgLayout`/`AdminLayout`.
    - Create `contexts/FleetSessionContext.tsx` and `contexts/FleetCsrfContext.tsx`.
    - Create `api/client.ts` with axios baseURL `/fleet/api`, withCredentials, CSRF header from cookie; and `api/endpoints.ts` with typed wrappers per endpoint. **Use typed generics on every API call — no `as any`.**
    - **CSRF cookie reading**: mirror the existing `getPortalCsrfCookie` pattern from `frontend/src/api/client.ts:40-71`. Read from the `fleet_portal_csrf` cookie (parallel name, scoped to fleet host) and send as `X-CSRF-Token` header on POST/PUT/PATCH/DELETE.
    - **Apply safe-API consumption rules** (`safe-api-consumption.md`): `res.data?.items ?? []`, `res.data?.total ?? 0`, every `useEffect` API call uses `AbortController` cleanup, no `as any`.
    - _Implements Requirements: 2.1, 2.2, 2.7, 19.1, 19.4, 19.5, 19.6_

  - [x] 14.2 Implement auth pages
    - `pages/Login.tsx`, `pages/AcceptInvite.tsx`, `pages/ForgotPassword.tsx`, `pages/ResetPassword.tsx`. Use the existing form primitives; show inline errors on 400/409, redirect-to-login on 401, full-page module-disabled message on 403.
    - _Implements Requirements: 3.1, 3.9, 3.11, 3.12, 4.4, 4.5, 4.6_

  - [x] 14.3 Implement shared components
    - `components/ExpiryBadge.tsx` — mirrors backend Property 16 colours.
    - `components/PhotoUpload.tsx` — camera capture, ≤ 8 MB, `image/*`.
    - `components/KioskButton.tsx` — `min-h-[56px] min-w-[56px] text-lg`.
    - `components/ChecklistItemRow.tsx` — large pass/fail/na buttons; mobile sticky.
    - _Implements Requirements: 9.4, 9.11, 9.12, 19.2, 19.3_

  - [x] 14.4 Write property test for touch targets
    - **Property 34: Touch target sizes** — Validates: Requirements 9.11, 19.2, 19.3
    - File: `frontend/src/fleet-portal/__tests__/touch-target.property.test.ts`
    - Use fast-check to generate component variants and assert width/height ≥ 44 (≥ 56 in kiosk paths) via getBoundingClientRect-equivalent on rendered DOM.
    - _Implements Requirements: 9.11, 19.2, 19.3_

- [x] 15. Frontend — Vehicles, drivers, checklists
  - [x] 15.1 Vehicles pages
    - `pages/VehicleList.tsx` — paginated `{ items, total }`; status badges; admin/driver variants.
    - `pages/VehicleDetail.tsx` — admin can edit allowlisted fields; driver can log odometer + hours; per-role field allowlist enforced client-side too.
    - _Implements Requirements: 6.1–6.4, 6.6, 7.1, 7.2, 7.5–7.8_

  - [x] 15.2 Drivers pages (admin-only)
    - `pages/DriverList.tsx`, `pages/DriverDetail.tsx` (assignments + activity link), `pages/DriverActivity.tsx` (date-range picker, summary cards, per-vehicle table, CSV download button).
    - _Implements Requirements: 5.1, 5.2, 5.3, 5.5–5.7, 5.9, 14.1–14.5_

  - [x] 15.3 Checklist pages
    - `pages/ChecklistTemplates.tsx` (admin) and `pages/ChecklistTemplateEdit.tsx` (admin): list templates, clone NZTA, set default, archive, edit items.
    - `pages/ChecklistSubmit.tsx`: driver flow — start, fill items, upload photos, complete; client predicate matches Property 23.
    - `pages/ChecklistKiosk.tsx` at route `/fleet/kiosk/checklist`: full-screen kiosk variant with ≥ 56 px targets.
    - `pages/ChecklistHistory.tsx`: admin sees all in fleet (filters); driver sees own.
    - _Implements Requirements: 8.3–8.5, 8.7, 9.1–9.12_

- [x] 16. Frontend — Reminders, bookings, quotes, invoices, dashboard
  - [x] 16.1 Reminder preferences page (admin)
    - `pages/ReminderPreferences.tsx`: per-vehicle table with toggles for WOF/COF/service-due, lead time selector, channel and recipient checkboxes; SMS option disabled when `sms_provider_configured=false`.
    - _Implements Requirements: 10.1, 10.2, 10.7, 10.8_

  - [x] 16.2 Booking pages
    - `pages/BookingRequestForm.tsx` and `pages/BookingList.tsx`. Disable submit until predicates pass (date today-or-later, slot selected, description ≥ 10 chars, vehicle in accessible set).
    - _Implements Requirements: 11.1, 11.2, 11.3, 11.6, 11.8_

  - [x] 16.3 Quote pages (admin)
    - `pages/QuoteRequestForm.tsx`, `pages/QuoteList.tsx`, `pages/QuoteDetail.tsx` with Accept/Decline; show "Expired" state when underlying quote is expired.
    - _Implements Requirements: 12.1–12.7_

  - [x] 16.4 Invoice pages (admin)
    - `pages/InvoiceList.tsx`, `pages/InvoiceDetail.tsx`, "Download PDF" action; status filter.
    - _Implements Requirements: 13.1–13.5, 13.7_

  - [x] 16.5 Dashboard
    - `pages/Dashboard.tsx`: admin variant (summary cards, recent failures, pending bookings/quotes panels) and driver variant (assigned vehicles, today's checklist status).
    - _Implements Requirements: 15.1–15.6_

- [x] 17. Frontend — Workshop_Admin console (`fleet-portal-admin/`)
  - [x] 17.1 Workshop_Admin pages mounted in `OrgLayout`
    - **Read `frontend/src/layouts/OrgLayout.tsx` and `frontend/src/App.tsx` first** (per `no-shortcut-implementations.md`) — match the existing nav-item and module-gating pattern exactly.
    - Create `frontend/src/fleet-portal-admin/pages/`: `FleetPortalDashboard.tsx`, `BookingQueue.tsx`, `QuoteQueue.tsx`, `FleetAccountList.tsx`, `ChecklistFailures.tsx`. (Tasks 4B.1 and 4B.2 add `PortalSecuritySettings.tsx` and `PortalAccountDetail.tsx`.)
    - Create `components/PortalAccessSection.tsx` to render on the existing `CustomerProfile` page when customer is business-type and the module is enabled. Use the existing customer-profile injection pattern.
    - Wrap each page in `<ModuleGate module="b2b-fleet-management">`.
    - Add a sidebar group "Fleet Portal" in `OrgLayout` with sub-items (Dashboard, Bookings, Quotes, Fleet Accounts, Checklist Failures, Security Policy). Add a count badge equal to `pending_bookings + pending_quotes` on the group.
    - Add routes in `App.tsx` under `/fleet-portal-admin/*` with `RequireOrgAdmin` guard.
    - "View as Portal User" button on `FleetAccountList.tsx` calls task 4A.9's start-impersonation endpoint, navigates to a new tab on the fleet portal host with the impersonation token, and shows the audit-trail link.
    - _Implements Requirements: 1.8, 4.1, 4.7, 16.1–16.7, 21.21_

  - [x] 17.2 Add Fleet Portal Activity dashboard widget
    - Follow `dashboard-widget-gating.md` to add a `FleetPortalActivityWidget` to `frontend/src/pages/dashboard/widgets/`.
    - Backend: add `get_fleet_portal_activity()` to `app/modules/organisations/dashboard_service.py` returning `{ pending_bookings, pending_quotes, recent_failures (last 5) }`. Wire into `get_all_widget_data()` with try/except.
    - Schema: add `FleetPortalActivityItem` and field on `DashboardWidgetsResponse`.
    - Frontend: add type, normalisation, widget component, and register in `WIDGET_DEFINITIONS` with `module: 'b2b-fleet-management'`.
    - _Implements Requirements: 16.5_

  - [x] 17.3 Write unit tests for sidebar visibility, role gating, and admin queues
    - Test: sidebar group hidden when module disabled (Requirement 1.8); fleet portal admin pages return 403 / hide UI when module not enabled; PortalAccessSection only shows on business customers; dashboard widget hidden when module disabled.
    - _Implements Requirements: 1.8, 4.1, 4.3, 16.5_

- [x] 18. Notifications, audit, and module-disable cascade
  - [x] 18.1 Wire `fleet_*` notification types into the existing in-app notification system
    - Register notification types `fleet_booking_request`, `fleet_quote_request`, `fleet_checklist_failure`, `fleet_booking_accepted`, `fleet_booking_declined`, `fleet_quote_quoted`, `fleet_quote_accepted`, `fleet_quote_declined`.
    - Each type maps to an existing email template variant and an in-app row.
    - _Implements Requirements: 9.7, 11.2, 11.4, 11.5, 12.2, 12.3, 12.5, 12.6_

  - [x] 18.2 Implement module-disable cascade
    - Hook into `ModuleService.disable_module('b2b-fleet-management', org_id)`: in the same transaction, delete all `portal_sessions` whose `portal_account_id` belongs to a `portal_accounts` row with `org_id=O` and `portal_user_role IN ('fleet_admin','driver')`.
    - Invalidate the existing Redis module cache key for that org.
    - Return a count of invalidated sessions for logging.
    - _Implements Requirements: 1.7, 1.8, 4.8, 5.7, 17.6_

- [x] 19. Checkpoint — Frontend and notifications
  - **Scoped test run** (only what tasks 12–18 touched):
    - Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/fleet_portal/test_request_state_machines_property.py tests/fleet_portal/test_pagination_property.py -v --no-header` — runs the booking/quote state-machine and pagination tests added in tasks 12–13.
    - Frontend tests for fleet portal SPA: `npx vitest run frontend/src/fleet-portal/` — runs every test file under the new fleet portal frontend directory only.
    - Frontend tests for fleet portal admin pages: `npx vitest run frontend/src/fleet-portal-admin/`.
    - Frontend tests for the new dashboard widget: `npx vitest run frontend/src/pages/dashboard/widgets/__tests__/FleetPortalActivityWidget.test.tsx` (only the new widget test, not the whole widgets suite).
    - Type check: `npx tsc --noEmit` from `frontend/`.
  - DO NOT run `pytest tests/` or `npm run test`.
  - Ensure all listed scoped tests pass; ask the user if questions arise.

- [x] 19L. Mobile dependency upgrade — Capacitor 7 → 8 (prerequisite for 19M)
  - **Why this is in the spec:** The fleet portal mobile work in 19M adds new Capacitor plugin usage (Camera for checklist photos, Push Notifications for booking/quote alerts, Biometric unlock, Preferences for auth-mode persistence). Building those features on Capacitor 7 and then migrating later means doing the work twice. The dependency audit in `docs/DEPENDENCY_AUDIT_2026_05.md` flagged this upgrade as the single CRITICAL item for mobile, and the only blocker was the abandoned `capacitor-native-biometric` v4.2.0 plugin (which only supports Capacitor 3 and 4 per its README). The fix is to swap it for the maintained `@capgo/capacitor-native-biometric` (v7.x with a published v7→v8 migration guide), then run the official Capacitor migration.
  - **Read first** (per `no-shortcut-implementations.md`): `mobile/package.json`, `mobile/capacitor.config.ts`, `mobile/android/app/build.gradle`, `mobile/android/variables.gradle`, `mobile/android/gradle/wrapper/gradle-wrapper.properties`, `mobile/src/contexts/BiometricContext.tsx`, and the existing biometric usages across `mobile/src/screens/auth/`, `mobile/src/screens/settings/`.

  - [x] 19L.1 Replace abandoned biometric plugin with maintained fork
    - Remove `capacitor-native-biometric` (v4.2.0, abandoned `epicshaggy/capacitor-native-biometric` per its README "Only supports Capacitor 3 and 4").
    - Install `@capgo/capacitor-native-biometric` (v7.x, has a published v7→v8 migration guide). Run `npm uninstall capacitor-native-biometric && npm install @capgo/capacitor-native-biometric`.
    - Update every import: `from 'capacitor-native-biometric'` → `from '@capgo/capacitor-native-biometric'`.
    - Verify the API surface matches: `isAvailable`, `verifyIdentity`, `getCredentials`, `setCredentials`, `deleteCredentials`. The fork keeps the same names but check return types and any new option fields per the capgo plugin docs.
    - Update `mobile/src/contexts/BiometricContext.tsx` and any `setCredentials` / `getCredentials` call sites to match.
    - Test biometric enrol → lock → unlock on a physical device (emulator does not have biometric hardware).
    - _Implements: prerequisite for 19L.3, 19M.8_

  - [x] 19L.2 Verify Node.js, Xcode, Android Studio prerequisites are met
    - Capacitor 8 requires Node.js 22+, Xcode 26+ (iOS), Android Studio Otter (2025.2.1+), Gradle 8.14.3, AGP 8.13.0, Android minSdk 24 / compile + target SDK 36.
    - Check `node --version` in dev container — if < 22, update the `Dockerfile` `FROM node:...` base image and the dev container.
    - For Android: `./gradlew --version` to confirm current Gradle, then update `android/gradle/wrapper/gradle-wrapper.properties` and `android/variables.gradle` per the migration guide.
    - For iOS: out of scope right now (project is Android-only per `mobile/package.json` scripts), but document the SPM-default change so a future iOS build picks the right path.
    - _Implements: prerequisite for 19L.3_

  - [x] 19L.3 Run the official Capacitor 8 migration
    - Use the **Capacitor CLI migrate command** (Option 1 from the [official upgrade guide](https://capawesome.io/blog/how-to-upgrade-your-capacitor-app-to-capacitor-8/)):
      ```bash
      cd mobile
      npm i -D @capacitor/cli@latest
      npx cap migrate
      ```
    - The CLI updates all `@capacitor/*` packages to v8, adjusts native project files, prompts for manual intervention where needed.
    - After the CLI run, verify each of the 13 Capacitor plugins now shows v8.x in `package.json`:
      `@capacitor/android`, `@capacitor/app`, `@capacitor/browser`, `@capacitor/camera`, `@capacitor/cli`, `@capacitor/core`, `@capacitor/geolocation`, `@capacitor/haptics`, `@capacitor/keyboard`, `@capacitor/network`, `@capacitor/preferences`, `@capacitor/push-notifications`, `@capacitor/share`, `@capacitor/splash-screen`, `@capacitor/status-bar`.
    - If the CLI skips any plugin (warning in output), upgrade it manually: `npm install @capacitor/<name>@latest`.
    - Manually verify the Capacitor 8 changes the CLI doesn't always handle:
      - `bridge_layout_main.xml` renamed to `capacitor_bridge_layout_main.xml` in `android/app/src/main/res/layout/`.
      - `density` added to `configChanges` in `android/app/src/main/AndroidManifest.xml`.
      - `android.adjustMarginsForEdgeToEdge` removed from `capacitor.config.ts` (replaced by the new System Bars core plugin behaviour, which is automatic).
      - `variables.gradle` has `minSdkVersion = 24`, `compileSdkVersion = 36`, `targetSdkVersion = 36`.
      - Gradle wrapper at 8.14.3, AGP at 8.13.0.
    - _Implements: prerequisite for 19M_

  - [x] 19L.4 Adopt the new System Bars plugin for edge-to-edge layout
    - Capacitor 8 introduces a built-in `SystemBars` core plugin that replaces the removed `adjustMarginsForEdgeToEdge` config option ([Capacitor 8 announcement](https://ionic.io/blog/announcing-capacitor-8)). It exposes status bar and navigation bar insets via CSS environment variables (`env(safe-area-inset-*)`).
    - In `mobile/src/index.css` (or the equivalent global CSS), confirm the existing `pb-safe` utility (Tailwind `padding-bottom: env(safe-area-inset-bottom)`) keeps working — Capacitor 8 sets these vars automatically with no extra JS call.
    - Test on an Android 14+ device with a punch-hole camera and a gesture-nav home pill; verify that the bottom tabs and headers don't collide with system UI.
    - _Implements Requirements: 19.7, 24.12_

  - [x] 19L.5 Adopt remaining mobile dep upgrades from the audit
    - Update mobile-side packages flagged in `docs/DEPENDENCY_AUDIT_2026_05.md` while we have the lockfile open:
      - `axios` 1.15.2 → 1.16.1 (HTTP client security patches — HIGH).
      - `firebase` 12.12.1 → 12.13.0 (auth provider — MEDIUM).
      - `react` + `react-dom` 19.2.5 → 19.2.6 (must match each other — MEDIUM).
      - `react-router-dom` 7.14.2 → 7.15.1 (routing fixes — MEDIUM).
      - `@stripe/react-stripe-js` 6.3.0 → 6.4.0 and `@stripe/stripe-js` 9.3.1 → 9.6.0 (payment SDK — MEDIUM).
      - `tailwindcss` + `@tailwindcss/postcss` 4.2.4 → 4.3.0 (CSS — MEDIUM).
      - `vite` 8.0.10 → 8.0.14, `vitest` 4.1.5 → 4.1.7, `typescript` 6.0.2 → 6.0.3, `@vitejs/plugin-react` 6.0.1 → 6.0.2, `postcss` 8.5.12 → 8.5.15, `fast-check` 4.7.0 → 4.8.0, `@types/node` 25.6.0 → 25.9.1, `@types/react` 19.2.14 → 19.2.15 (LOW — patch / dev only).
    - After all updates, run a **scoped** verification — NOT the full test suite:
      - `cd mobile && npm run build` (TypeScript + Vite production build; catches type errors and import mismatches caused by the upgrades).
      - `npx vitest run mobile/src/__tests__/auth-screens.test.tsx mobile/src/__tests__/portal-kiosk-screens.test.tsx mobile/src/__tests__/utils/portalLink.test.ts` (only the existing test files most likely to be touched by Capacitor / axios / Stripe / Firebase / react-router-dom / tailwindcss bumps).
      - `npx tsc --noEmit` from `mobile/` for a fast type check.
    - DO NOT run `npm run test` (the full mobile suite). Per the test-scoping policy, regressions surface in the scoped runs above; the full suite runs only in CI on the final commit.
    - _Implements: complementary to 19L.3_

  - [x] 19L.6 Verify all native features still work after the upgrade
    - End-to-end smoke test on a physical Android device (not emulator):
      1. App launches without crash; splash screen + status bar look correct on Android 14.
      2. Login flow works (staff credentials).
      3. Biometric enrol + unlock cycle works (`@capgo/capacitor-native-biometric`).
      4. Camera plugin captures a photo (existing compliance docs upload flow).
      5. Push notifications register and a test push is delivered.
      6. Network plugin reports online/offline transitions.
      7. Preferences plugin reads/writes the existing `selected_branch_id` and `auth_mode` keys.
      8. Share plugin opens the native share sheet (existing invoice share).
      9. Geolocation, Haptics, Keyboard, Browser, Status Bar, Splash Screen — quick sanity check each.
    - If any plugin breaks, file a follow-up task in the issue tracker before proceeding to 19M.
    - _Implements: prerequisite gate for 19M_

  - [x] 19L.7 Update the dependency audit doc with the new state
    - Edit `docs/DEPENDENCY_AUDIT_2026_05.md` to mark the Capacitor 8 row in "Phase 3" as complete (or move to a new "Completed" section).
    - Add the post-upgrade versions to the audit table.
    - Note that `capacitor-native-biometric` was replaced with `@capgo/capacitor-native-biometric` and remove the deferred-blocker note.
    - _Implements: docs hygiene_

- [x] 19M. Native mobile app — Fleet Portal sign-in and screens (Requirement 24)
  - [x] 19M.0 Update the mobile-app steering doc
    - Edit `.kiro/steering/mobile-app.md` to add a "Fleet Portal Users" audience alongside the existing "Organisation Users" audience.
    - Document the dual auth flow (`authMode: 'staff' | 'fleet'`), the separate API base URL (`/fleet/api`) and cookie-based auth (vs Bearer token for staff), and the role-specific bottom-tab navigation (Driver_User vs Fleet_Account_Admin).
    - Add a "Mobile screens for portal users" subsection listing the new screens under `mobile/src/screens/fleet-portal/`.
    - Update the "Never include in mobile" list — the existing exclusions (global admin, org admin destructive ops) still apply but are scoped to the staff side; portal-side exclusions are different (no quote creation, no invoice editing, no module management, no settings panels beyond profile + security).
    - _Implements Requirements: 24.1–24.18 (foundational)_

  - [x] 19M.1 Extend mobile auth context to support fleet portal mode
    - **Read `mobile/src/contexts/AuthContext.tsx` first** (per `no-shortcut-implementations.md`) so the new `authMode` state integrates with the existing staff JWT flow without breaking it.
    - Add `authMode: 'staff' | 'fleet'` state to `AuthContext`, persisted via `Capacitor Preferences` under key `auth_mode`.
    - Add `portalUser: PortalUser | null` state (separate from existing `user: AuthUser | null`).
    - Add `loginAsFleet(creds)` calling `POST /fleet/api/auth/login` with cookies (no Bearer token), `logoutFleet()` calling `POST /fleet/api/auth/logout`, `completeFleetMfa(code, method)` calling `POST /fleet/api/auth/mfa/verify`.
    - Detect MFA required / setup required in the response and surface flags `mfaPending` / `mfaSetupRequired` mirroring the staff pattern.
    - `isAuthenticated` becomes `!!staffUser || !!portalUser`.
    - On app launch, restore the active session: read `auth_mode` from Preferences; if `'fleet'`, call `GET /fleet/api/me` (uses the cookie) to revive the portal user; if no valid session, route to fleet login.
    - _Implements Requirements: 24.1, 24.2, 24.4, 24.5, 24.6, 24.14_

  - [x] 19M.2 Extend mobile API client to dual-target staff and fleet APIs
    - Create `mobile/src/api/fleetClient.ts` — separate axios instance with `baseURL: '/fleet/api'` (web) or `'https://devin.oraflows.co.nz/fleet/api'` (native), `withCredentials: true`, no Bearer-token interceptor (uses HttpOnly cookie).
    - Reuse the existing CSRF interceptor pattern (read `fleet_portal_csrf` cookie, send `X-CSRF-Token` header on POST/PUT/PATCH/DELETE).
    - On 401 from any fleet API call, clear `portalUser`, navigate to `/mobile/fleet/login`, show "Your session has expired" toast (Requirement 24.14).
    - Existing `apiClient.ts` (staff) is unchanged.
    - _Implements Requirements: 24.1, 24.14_

  - [x] 19M.3 Add fleet auth screens to mobile
    - `mobile/src/screens/auth/FleetLoginScreen.tsx` — Konsta UI: email + password fields, "Sign In" primary button, "Forgot password?" link, "Switch to Staff Login" footer link. Renders `KonstaNavbar` with "Fleet Portal Sign In" title.
    - `mobile/src/screens/auth/FleetForgotPasswordScreen.tsx` — email input, calls `POST /fleet/api/auth/forgot-password`, always shows generic confirmation.
    - `mobile/src/screens/auth/FleetMfaVerifyScreen.tsx` — 6-digit OTP input + method selector (TOTP / SMS / backup code).
    - `mobile/src/screens/auth/FleetMfaEnrollScreen.tsx` — TOTP QR code + 6-digit confirm input. Shows backup codes once on completion.
    - Update `mobile/src/screens/auth/LoginScreen.tsx` to add a "Sign in to Fleet Portal" footer link that navigates to `/mobile/fleet/login` (Requirement 24.13).
    - All forms use `?.` and `?? []` patterns; `useEffect` with `AbortController`; typed generics on every API call.
    - _Implements Requirements: 24.1, 24.5, 24.6, 24.13_

  - [x] 19M.4 Add Fleet_Portal_Mobile_Shell with role-based bottom tabs
    - Create `mobile/src/navigation/FleetPortalRoutes.tsx` — top-level switch: when `portalUser?.portal_user_role === 'fleet_admin'`, render admin tabs (Dashboard / Vehicles / Drivers / Bookings / More); when `'driver'`, render driver tabs (My Vehicles / Checklists / Hours / More).
    - Add `<FleetAuthGuard>` route wrapper that redirects to `/mobile/fleet/login` if `!portalUser`.
    - Update `mobile/src/App.tsx` (or root navigator) to detect `authMode === 'fleet'` and render `<FleetPortalRoutes>` instead of the existing staff routes.
    - Apply Konsta `Toolbar` for bottom tabs with proper safe-area inset (`pb-safe`), 44 × 44 px minimum touch targets, and the existing `HapticButton` pattern.
    - _Implements Requirements: 24.3, 24.4, 24.12_

  - [x] 19M.5 Implement Driver_User mobile screens
    - `FleetDashboardScreen.tsx` — summary cards (assigned vehicles count, today's checklist status, next shift); calls `GET /fleet/api/dashboard` (driver variant).
    - `MyVehiclesScreen.tsx` — list of assigned vehicles with WOF/COF/service-due badges (use existing `StatusBadge` Konsta component); pull-to-refresh via existing `PullRefresh` component; tap row to open detail.
    - `VehicleDetailScreen.tsx` — read-only vehicle fields, sticky "Log Odometer" and "Log Hours" buttons at bottom; modals call `POST /fleet/api/vehicles/{id}/odometer` and `POST /fleet/api/vehicles/{id}/hours`.
    - `ChecklistSubmitScreen.tsx` — start submission via `POST /fleet/api/checklists/start`; iterate items with pass/fail/na buttons; on fail, capture photo via Capacitor `Camera.getPhoto({ source: CameraSource.Camera, resultType: CameraResultType.Uri, quality: 80 })`, upload via `POST /fleet/api/checklists/{id}/items/{i}/photo`; complete via `POST /fleet/api/checklists/{id}/complete`. Sticky pass/fail buttons at bottom; full-screen single-column layout.
    - `ChecklistHistoryScreen.tsx` — paginated list of own submissions, filter chips for date range and result.
    - `HoursLogScreen.tsx` — list of recent driving-hour entries with vehicle rego + duration; "+ Log hours" opens a modal with vehicle picker + start/end date-time pickers.
    - `MoreScreen.tsx` (driver variant) — Profile, Notifications, My Security, About, Logout.
    - All screens wrap in Konsta `Page`; use `Block` and `BlockTitle` for sections; use `List`/`ListItem` for tabular data; use `Card` for summary tiles. Match the visual style of `mobile/src/screens/portal/PortalScreen.tsx`.
    - _Implements Requirements: 24.7, 24.10, 24.12_

  - [x] 19M.6 Implement Fleet_Account_Admin mobile screens
    - `FleetVehiclesScreen.tsx` — full fleet list (admin variant; shows all vehicles linked to the fleet account); same UI as MyVehiclesScreen but admin-scoped.
    - `DriversScreen.tsx` — list of drivers with assignment count and status; "+ Invite driver" button opens modal; tap driver row to open detail page with vehicle assignment toggles.
    - `BookingsScreen.tsx` — list of service booking requests (status chips); "+ New booking" form with vehicle picker, date picker, slot dropdown, description textarea.
    - `RemindersScreen.tsx` — per-vehicle WOF/COF/service-due/registration toggle rows; lead-time selector; channel checkboxes (email/sms); recipient checkboxes (admin/drivers).
    - `QuotesScreen.tsx` — list of quotation requests; tap to view quote detail with Accept/Decline buttons.
    - `InvoicesScreen.tsx` — read-only paginated list with status filter; tap to view; "Download PDF" button uses Capacitor `Filesystem.writeFile` + share intent for native share sheet.
    - `MoreScreen.tsx` (admin variant) — adds Drivers / Reminders / Quotes / Invoices to the driver More menu.
    - _Implements Requirements: 24.8, 24.10, 24.12_

  - [x] 19M.7 Implement My Security screen for Portal_Users
    - `MySecurityScreen.tsx` — sections: Change Password, MFA Methods (enrol/remove), Active Sessions, Recent Login Events.
    - Reuse `FleetMfaEnrollScreen` for in-app enrolment from the Security screen.
    - Backup codes view (one-time display on regenerate) uses Konsta `Sheet` modal with copy-to-clipboard.
    - Session list uses `List`/`ListItem` with revoke icon button; revoke confirmation via Konsta `Dialog`.
    - _Implements Requirements: 24.5, 21.16_

  - [x] 19M.8 Implement biometric unlock for fleet portal
    - **Read `mobile/src/contexts/BiometricContext.tsx` first** (existing pattern for staff biometric). Note that task 19L.1 has already swapped the underlying plugin from the abandoned `capacitor-native-biometric` to `@capgo/capacitor-native-biometric` — use that as the import.
    - Extend or duplicate the biometric context with a `fleet-portal-biometric` keychain entry (use `setCredentials` / `getCredentials` from `@capgo/capacitor-native-biometric` with a distinct `server` parameter so the two never cross).
    - On successful fleet login, prompt "Enable biometric unlock?" — on accept, store the session token under the fleet keychain entry.
    - On app launch with `authMode === 'fleet'` and biometric enabled, show biometric prompt; on success, restore the session.
    - _Implements Requirements: 24.11_

  - [x] 19M.9 Implement push notifications for portal users
    - **Verified prerequisite:** `app/modules/push_notifications/` does NOT currently exist (`fileSearch push_notifications` returns no Python module — only the mobile-side `mobile/src/hooks/usePushNotifications.ts`). The original mobile-app redesign explicitly deferred the backend FCM dispatcher with the note "Do NOT implement the backend FCM dispatcher in this task — only the device-side registration and listeners. Flag the backend work as a follow-up TODO." This spec creates the backend dispatcher.
    - Backend: create the new module `app/modules/push_notifications/` with `__init__.py`, `service.py` (`send_to_portal_account(db, *, portal_account_id, title, body, data)` and `send_to_user(db, *, user_id, title, body, data)`), `router.py`, `models.py` (only if a separate model is needed beyond `portal_account_devices`).
    - Backend: add `POST /fleet/api/devices/register` accepting `{ device_token, platform, app_version, os_version }`. Idempotent on `(portal_account_id, device_token)` via `INSERT ... ON CONFLICT DO NOTHING` (matches the existing `reminder_queue` pattern). On register, also update `last_seen_at = now()`.
    - Backend: add `DELETE /fleet/api/devices/{token}` for logout cleanup (404 if the token doesn't belong to the current portal_account).
    - Backend: implement the FCM HTTP v1 dispatch via Google's REST API (`https://fcm.googleapis.com/v1/projects/{project_id}/messages:send`) using a service-account JWT signed with the existing `cryptography` library. Read FCM credentials (project_id, service-account JSON) from `integration_configs` per the `integration-credentials-architecture.md` steering doc — same pattern as Stripe / CarJam.
    - Backend: **Android (FCM) only for the MVP**. iOS APNs is a follow-up; document this in task 19M.9 and in the issue tracker entry. The `platform` column on `portal_account_devices` accepts both values, but the dispatcher branches: Android → FCM, iOS → log-and-skip with a TODO comment.
    - Backend: **Fallback policy** — when FCM credentials are not configured for the org OR the FCM call fails, the push send is a no-op (with a warning log line); the in-app notification + email continue to fire as the primary surface (already wired in task 18.1). Push is best-effort, never the sole delivery mechanism.
    - Backend: emit push notifications for `fleet_booking_accepted`, `fleet_booking_declined`, `fleet_quote_quoted` events to the requester's portal account. The emit call site is in the corresponding service function (`booking_service.accept_booking_request`, `quote_service.link_quote`, etc.) — wrap in try/except so a failed push never breaks the primary action.
    - Mobile: on fleet login, register the FCM token via `PushNotifications.register()` then call the new register endpoint; on logout, call the delete endpoint.
    - Mobile: handle incoming push notifications via `PushNotifications.addListener('pushNotificationReceived', ...)` to show in-app banner when app is foreground; on tap, deep-link into the relevant screen (booking detail / quote detail) using the existing `useDeepLink` hook from the staff side.
    - _Implements Requirements: 24.10, 24.15_

  - [x] 19M.10 Implement version refresh + module-disabled detection on mobile
    - Mobile: add `useFleetVersionCheck()` hook that polls `GET /fleet/api/version` every 60 s while focused (use Capacitor `App` plugin's `appStateChange` event to pause when backgrounded).
    - When backend version differs from build-time meta, show Konsta `Notification` "New version available". Native users tap to open the App Store / Play Store update page (Capacitor `App.openUrl()`); web users get a hard reload.
    - On any 403 with detail "B2B Fleet Management module is not enabled for this organisation", clear `portalUser`, show full-screen Konsta `Page` with message + Logout button.
    - _Implements Requirements: 24.16, 24.17_

  - [x] 19M.11 Implement Kiosk mode for depot tablets
    - **Read `mobile/src/screens/kiosk/KioskScreen.tsx` first** to mirror the existing kiosk lock pattern.
    - Add a "Kiosk mode" toggle to the driver `MoreScreen`. Toggling on prompts for a 6-digit unlock PIN; persists `kiosk_locked = true` and `kiosk_pin_hash = bcrypt(pin)` in Capacitor Preferences.
    - When `kiosk_locked = true`, all routes redirect to `/mobile/fleet/kiosk/checklist` (a wrapper around `ChecklistSubmitScreen` with no nav bar).
    - Unlock requires entering the matching PIN; clears `kiosk_locked` and `kiosk_pin_hash`.
    - _Implements Requirements: 24.18_

  - [x] 19M.12 Mobile-app property tests for fleet portal
    - **Property 40: Auth-mode routing** — for any `(authMode, staffUser, portalUser)` state combination, the app routes to exactly one of: staff routes, fleet routes, login screen, or fleet login screen.
    - **Property 41: Touch targets in fleet portal mobile** — every interactive element on every fleet portal screen at viewport ≥ 320 px wide has bounding box ≥ 44×44 px.
    - **Property 42: API client target selection** — `apiClient` is used iff `authMode === 'staff'`; `fleetApiClient` is used iff `authMode === 'fleet'`.
    - File: `mobile/src/__tests__/fleet-portal-routing.property.test.ts` and `mobile/src/__tests__/fleet-portal-touch-targets.property.test.tsx`
    - _Implements Requirements: 24.3, 24.4, 24.12_

  - [x] 19M.13 Mobile-app integration tests
    - End-to-end: fleet login → driver dashboard → start checklist → fail an item → take photo → complete → see notification.
    - End-to-end: fleet admin login → invite driver → assign vehicle → driver receives push notification.
    - File: `mobile/src/__tests__/fleet-portal-e2e.test.tsx`

- [x] 19A. Security headers, version refresh, and deployment hygiene
  - [x] 19A.1 Apply security headers to fleet portal responses
    - Add a FastAPI middleware (or extend the existing `PortalCacheRoute`) for fleet portal routes that emits: `Cache-Control: no-store, Pragma: no-cache` on all `/fleet/api/...` responses; `X-Frame-Options: DENY`; `X-Content-Type-Options: nosniff`; `Referrer-Policy: same-origin`; `Permissions-Policy: camera=(self), microphone=(), geolocation=()`.
    - Update the nginx config (`nginx/conf.d/*`) to add `Strict-Transport-Security: max-age=31536000; includeSubDomains` for the fleet host and a strict `Content-Security-Policy` matching the staff app (no `unsafe-inline` for scripts, only `'self'` and required CDN origins).
    - Set the session cookie with `HttpOnly, Secure, SameSite=Lax, Path=/fleet` so it never leaks to the staff origin.
    - _Implements Requirements: 23.1, 23.2, 23.3_

  - [x] 19A.2 Implement version-refresh endpoint and frontend polling
    - **Read `frontend/vite.config.ts` first** (per `no-shortcut-implementations.md`) — if a version-injection plugin already exists, extend it; otherwise add a `transformIndexHtml` Vite plugin.
    - Backend: add `GET /fleet/api/version` returning `{ "version": app.__version__, "build_sha": settings.BUILD_SHA, "released_at": settings.BUILD_TIME }`. Source the build sha from a build-time env var injected into the Docker image (Dockerfile `ARG GIT_SHA` → `ENV BUILD_SHA`). Update `docker-compose.dev.yml` and `docker-compose.pi.yml` to pass `GIT_SHA` from the build host.
    - Frontend: at build time, write the build sha into `index.html` as `<meta name="x-app-version" content="<sha>">`. Add a `useVersionCheck()` hook that polls `/fleet/api/version` every 60 seconds while the document is focused (use `document.visibilitychange`), compares to the meta value, and shows a non-blocking toast with a "Reload now" action when they differ.
    - Add the manual "Check for updates" button on the Profile page.
    - Update nginx so `index.html` has `Cache-Control: no-store` and hashed assets have `Cache-Control: public, max-age=31536000, immutable` (matches the existing pattern in the project).
    - _Implements Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

  - [x] 19A.3 Bump app version and update changelog
    - Bump version in `app/__init__.py` `__version__`, in `frontend/package.json`, and in `mobile/package.json` (mobile is now in scope per Requirement 24).
    - Update `CHANGELOG.md` with the new version section: feature summary, new endpoints, new tables (15), mobile screens added, deployment notes.
    - _Implements Requirements: 22.1_

- [x] 20. Integration, smoke tests, and final wiring
  - [x] 20.1 Integration tests
    - CarJam vehicle lookup during `Add vehicle` (success + fallback) using the existing mock harness — _Requirements: 6.5_
    - Ad-hoc Connexus SMS send (success + gateway error) — _Requirements: 10.7_
    - Email delivery via failover provider chain across invite, reset, booking accept/decline, and reminder flows (3 examples) — _Requirements: 3.10, 4.2, 11.4, 11.5, 10.4_
    - File: `tests/fleet_portal/test_integrations.py`

  - [x] 20.2 Smoke tests
    - Module registry row exists with the right slug, `display_name`, `dependencies = ["vehicles"]`, `setup_question`, and `setup_question_description` (Requirement 1.1). **No `trade_family_required` column** — that approach was dropped in favour of `TRADE_FAMILY_REQUIRED_MODULES` constant in code.
    - `TRADE_FAMILY_REQUIRED_MODULES['b2b-fleet-management'] == 'automotive-transport'` in `app/core/modules.py`.
    - Setup-guide returns the new question for an `automotive-transport` org with the module not yet enabled; absent for non-automotive orgs.
    - `/fleet/login` serves the fleet portal SPA bundle and not `OrgLayout` (Requirements 2.1, 2.2).
    - Top-level router selection in `App.tsx` chooses `FleetPortalRouter` for fleet hosts/paths (Requirement 2.7).
    - OpenAPI document includes `fleet-portal` and `fleet-portal-admin` tags with the expected operation count (Requirement 18.5).
    - All 15 new tables exist with RLS enabled (`portal_accounts`, `portal_account_mfa_methods`, `portal_account_backup_codes`, `portal_account_password_history`, `portal_audit_log`, `portal_account_devices`, plus the 9 fleet domain tables; the `customer_vehicles.fleet_checklist_template_id` column was also added).
    - `GET /fleet/api/version` returns the current app version + build sha (Requirement 22.1).
    - Security headers present on `/fleet/api/*` and the SPA index (Requirement 23.1).
    - File: `tests/fleet_portal/test_smoke.py`

  - [x] 20.3 OpenAPI documentation pass
    - Confirm every new endpoint is tagged `fleet-portal` or `fleet-portal-admin`, has a description, request schema, and response schema referencing the Pydantic models from `schemas.py`.
    - _Implements Requirements: 18.4, 18.5_

  - [x] 20.4 End-to-end wiring sanity check
    - Verify all routers are mounted in `app/main.py`, all Pydantic models import cleanly, all SQLAlchemy models are imported from `app/modules/fleet_portal/models.py`, and the migration applies cleanly on a fresh database.
    - Confirm `frontend/src/App.tsx` correctly forks to `<FleetPortalRouter>` based on host/path and that `vite build` succeeds.
    - _Implements Requirements: 2.7, 18.4, 19.1_

- [x] 21. Final checkpoint — Ensure all relevant tests pass, deploy hygiene, issue tracker entry
  - **Scoped test run** (only what this spec touched, end-to-end):
    - Backend property tests for this spec: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/fleet_portal/ -v --no-header`.
    - Backend integration + smoke tests for this spec: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/fleet_portal/test_integrations.py tests/fleet_portal/test_smoke.py -v --no-header` (only if those files were created by tasks 20.1 / 20.2).
    - Existing reminder regression check: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/ -k "reminder_queue or wof_rego" --no-header -q` (touched by task 10.2's extension to `enqueue_customer_reminders`).
    - Existing portal CSRF regression check: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app pytest tests/test_portal_csrf.py -v --no-header` (touched by task 3.5's session/CSRF reuse — verifies the existing token-link portal still works).
    - Frontend: `npx vitest run frontend/src/fleet-portal/ frontend/src/fleet-portal-admin/` plus `npx tsc --noEmit` from `frontend/`.
    - Mobile: `npx vitest run mobile/src/__tests__/fleet-portal-routing.property.test.ts mobile/src/__tests__/fleet-portal-touch-targets.property.test.tsx mobile/src/__tests__/fleet-portal-e2e.test.tsx mobile/src/screens/fleet-portal/` plus `npx tsc --noEmit` from `mobile/`.
    - E2E: `npx playwright test tests/e2e/fleet_portal/` (the two flows specified in the design's End-to-End section).
  - **NOTE**: This is the only checkpoint that runs the full set of fleet-portal-related test files together. Even here, we do NOT run `pytest tests/` (full backend suite) or `npm run test` (full frontend suite) — those run in CI on the final commit, not during spec execution.
  - Ensure all listed scoped tests pass; ask the user if questions arise.
  - Add a single rolled-up entry to `docs/ISSUE_TRACKER.md` documenting the feature ship and any known limitations (per `issue-tracking-workflow.md`), e.g. `ISSUE-NNN: B2B Fleet Portal feature deployed — separate password portal, MFA parity, NZTA checklists, reminders, bookings/quotes integration. Migration 0191. Module: b2b-fleet-management. Notable: portal_accounts table created from scratch (was a future proposal).`.
  - Add deployment notes: before applying migration 0191 to prod, take a `pg_dump` backup; after applying, verify the table count increased by 15 (10 fleet + 5 portal-security/device tables, plus `portal_accounts` itself = 16 — recount and confirm) and the `b2b-fleet-management` row exists in `module_registry` with the right `dependencies` value; verify zero existing customer/vehicle/invoice records were altered. Mobile app version is bumped and the new build is published to TestFlight / Play Internal Testing for portal users to install before the backend cutover.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP. Core implementation tasks are mandatory.
- Each task references the requirements it implements for traceability.
- Property-based tests use `hypothesis` (backend) and `fast-check` (frontend) — both already in the project.
- All 34 design properties + 5 new security parity properties (35–39) are covered. Core property test files: tasks 3.2, 3.4, 3.7, 3.8, 3.9, 6.4, 6.5, 6.6, 6.7, 7.3, 8.3, 9.3, 10.4, 10.5, 10.6, 12.4, 13.4, 13.5, 14.4, 4A.10, 4B.5.
- All API responses wrap arrays in `{ items, total, limit, offset }`. Pagination uses `offset`/`limit`; `skip` is rejected with HTTP 422.
- After every `db.flush()`, services call `await db.refresh(obj)` before returning ORM objects. **Services and routers never call `db.commit()` or `db.rollback()`** — the `session.begin()` context manager handles it (ISSUE-024, ISSUE-040, ISSUE-044).
- Migration `0191_b2b_fleet_portal.py` (head is 0190) uses `IF NOT EXISTS` and `ON CONFLICT DO NOTHING` for idempotency. Run `alembic upgrade head` inside the dev container immediately after creating it (`database-migration-checklist.md`).
- Postgres RLS policies are added to every new table; the session dependency calls `_set_rls_org_id` and `_set_rls_fleet_account_id` per request. **Both use `set_config()` with bound parameters** (the ISSUE-007 fix already shipped — see `app/core/database.py:75-99`).
- Trade-family gating is enforced in code (`TRADE_FAMILY_REQUIRED_MODULES` constant), not via a DB column — matches the setup-guide spec's pattern.
- The `portal_accounts` table is created by this migration (it has never been migrated before — `docs/future/portal-password-login.md` was a proposal). Verified by `grepSearch portal_accounts` returning zero matches against `alembic/versions/`.
- Portal users get **full security parity** with org users: configurable MFA / password / lockout / session policy, audit log, HIBP breach check, password history, permanent lockout, admin-side unlock and impersonation. See Requirement 21 and tasks 4A.x / 4B.x.
- Frontend version refresh + cache busting: `<meta x-app-version>` + `/fleet/api/version` + 60-second poll + reload toast. See Requirement 22 and task 19A.2.
- Strict security headers + CSP applied via nginx + middleware. See Requirement 23 and task 19A.1.
- `gap-analysis.md` in this spec folder documents the audit findings that produced these spec updates.
- **Test scoping policy** (see top of this file): every checkpoint and verification step runs ONLY tests relevant to the changes in that task. The full backend suite (`pytest tests/`) and full frontend suite (`npm run test`) are NEVER run during spec execution — only in CI on the final commit. Each checkpoint task lists its exact scoped test commands so reviewers can re-run them deterministically.
