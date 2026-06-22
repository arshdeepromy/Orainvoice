# Implementation Plan: Organisation Employee Portal

## Overview

This plan implements the optional, org-branded Employee Portal as a deliberate near-clone of the existing B2B Fleet Portal (`app/modules/fleet_portal/`), reusing the org-settings service, the public staff roster data path, PII masking, the unified email sender, and the mobile Capacitor/AuthContext stack rather than reinventing them. Work proceeds bottom-up so each step builds on the last and ends wired into a runnable surface: migration → ORM → pure slug/auth/session helpers → staff-uniqueness alignment → portal services → admin API → portal/public API → middleware wiring → frontend-v2 → mobile → cross-cutting tests → version/changelog.

Backend is Python 3.11 / FastAPI / SQLAlchemy (async) / Alembic; the active web app is `frontend-v2/` (React 18 + TypeScript + Vite); mobile is the single Capacitor 7 app (`mobile/`, React 19 + TypeScript). Property tests use **Hypothesis** on the backend (≥100 iterations each, every test tagged with a comment in the form `Feature: organisation-employee-portal, Property {n}: {property_text}`) and **fast-check** for the mobile/web pure-logic properties (22, 23). Pure-helper properties (4, 5, 7, 8, 11, 14, 16, plus the dedup survivor selector for 2) are tested **without a DB**; DB-invariant properties (1, 3, 6, 9, 10, 12, 13, 15, 17, 18, 19, 20, 21) run against the transactional test database at `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro`.

Pure, side-effect-free functions (slug normalisation/format/reserved/availability classification, dedup survivor selection, the lockout state machine, the session-validity predicate, the password-length validator) are extracted into dedicated modules so the corresponding properties are property-testable in isolation, and so the mobile/web client mirrors stay in parity.

## Tasks

- [x] 1. Database migration — slug column, portal tables, staff dedup + uniqueness (revision `0224`)
  - [x] 1.1 Create Alembic revision `0224` chaining from head `0223_staff_onboarding_tokens`
    - New file `alembic/versions/2026_06_xx_xxxx-0224_employee_portal.py` with `revision="0224"`, `down_revision="0223"`. Follow the **database-migration-checklist** steering: a transactional phase for catalogue-only / table-create / data steps, and a trailing autocommit phase (`with op.get_context().autocommit_block():`) for every `CONCURRENTLY` index, run LAST. Every statement uses `IF NOT EXISTS` / `IF EXISTS` / `information_schema` guards so a re-run (and a retry after a failed CONCURRENTLY build that leaves an INVALID index) is a safe no-op (R17.6)
    - Step 1 — `ALTER TABLE organisations ADD COLUMN IF NOT EXISTS slug varchar(63) NULL` (nullable, no backfill, R17.1); then in the autocommit phase `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_organisations_slug_lower ON organisations (lower(slug)) WHERE slug IS NOT NULL` (global, case-insensitive uniqueness, R2.5, R2.8)
    - Step 2 — `CREATE TABLE IF NOT EXISTS employee_portal_users`, `employee_portal_sessions`, `employee_portal_audit_log` exactly per design.md §Data Models (org-scoped, `ON DELETE CASCADE`; `employee_portal_audit_log.portal_user_id`/`actor_user_id` nullable with `ON DELETE SET NULL`). For each: `ENABLE ROW LEVEL SECURITY` (not FORCE) + `DROP POLICY IF EXISTS tenant_isolation` + `CREATE POLICY tenant_isolation ... USING (org_id = current_setting('app.current_org_id', true)::uuid)` — identical posture to the fleet/roster tables. In the autocommit phase create the portal indexes CONCURRENTLY: `uq_emp_portal_users_org_email_active ON employee_portal_users (org_id, lower(email)) WHERE is_active` (R5.2), `idx_emp_portal_users_staff`, `uq_emp_portal_users_invite_hash WHERE invite_token_hash IS NOT NULL`, `uq_emp_portal_users_reset_hash WHERE reset_token_hash IS NOT NULL`, and a `session_token_hash` unique index for sessions
    - Step 3 — **dedup BEFORE constraint** (R1.7, R17.5): in the transactional phase, for each org find every group of **active** staff sharing `lower(btrim(email))` or non-empty `employee_id`; select the survivor as the row with the earliest `created_at` (tie → smallest `id`) using the same ordering rule as the extracted `select_dedup_survivor` helper (task 4.2); `UPDATE staff_members SET is_active = false` for every non-survivor; **flip `is_active` only — never delete, never touch already-inactive rows**. Write an audit record per resolved group capturing the survivor id and each de-duplicated id (R1.8). This data step runs in its own transaction so it commits and is auditable before any index DDL
    - Step 4 — **pre-constraint guard** (R17.7): re-scan for any remaining active duplicate group; if any remain (e.g. an interrupted dedup), `raise` to halt the migration **before** creating the staff unique indexes, leaving data unchanged so the constraint is never enforced over dirty data
    - Step 5 — only after the guard passes, in the autocommit phase create the staff partial unique indexes CONCURRENTLY: `uq_staff_active_email_per_org ON staff_members (org_id, lower(btrim(email))) WHERE is_active AND email IS NOT NULL AND btrim(email) <> ''` and `uq_staff_active_employee_id_per_org ON staff_members (org_id, employee_id) WHERE is_active AND employee_id IS NOT NULL AND btrim(employee_id) <> ''` (R1.2, R1.3, R1.6)
    - `downgrade()` drops all CONCURRENTLY indexes with `DROP INDEX CONCURRENTLY IF EXISTS` inside an autocommit block, then `DROP TABLE IF EXISTS` the three portal tables and `ALTER TABLE organisations DROP COLUMN IF EXISTS slug`. Never use `op.create_index` / plain `CREATE INDEX` on the existing `organisations`/`staff_members` tables (they take `ACCESS EXCLUSIVE` locks). Mirror the canonical autocommit template `alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7, 1.8, 2.5, 2.8, 5.2, 16.3, 17.1, 17.5, 17.6, 17.7_

- [x] 2. ORM models
  - [x] 2.1 Add the three portal models to `app/modules/employee_portal/models.py`
    - Define `EmployeePortalUser`, `EmployeePortalSession`, `EmployeePortalAuditLog` exactly as in design.md §Data Models (org-scoped FKs with cascade; lockout columns; SHA-256 `invite_token_hash`/`reset_token_hash`/`session_token_hash`; `csrf_token`; `last_seen_at`/`expires_at`; nullable `portal_user_id`/`actor_user_id` on the audit log). Mirror `app/modules/fleet_portal/models.py` for the security column shapes
    - Add all three to the module `__all__` export and register the module in the model import graph so Alembic/metadata see the tables
    - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.2, 6.9, 6.10, 16.5, 16.6_
  - [x] 2.2 Add the `slug` column to the `Organisation` ORM model in `app/modules/admin/models.py`
    - `slug: Mapped[str | None] = mapped_column(String(63), nullable=True)` matching the migration column (D5, R2)
    - _Requirements: 2.1, 2.5_

- [x] 3. Slug service (pure helpers)
  - [x] 3.1 Implement `app/modules/organisations/slug_service.py`
    - Pure, DB-free helpers exactly per design: `RESERVED_SLUGS` frozenset (must be a **superset** of every existing top-level route segment — includes `e`, `portal`, `fleet`, `public`, `book`, `pay`, `onboard`, `payments`, `staff-portal`, `new`, `edit`, plus platform/operational/brand terms), `normalise_slug(raw)` (trim + lowercase), `validate_slug_format(slug) -> (ok, message)` (length 3–63, `^[a-z0-9]+(?:-[a-z0-9]+)*$`), `is_reserved(slug)`
    - Add `classify_availability(candidate, *, requesting_org_id, holder_org_id) -> ("available"|"unavailable"|"invalid", reason)` — pure given the format result, reserved check, and the resolved holder org id: `invalid` (never available) for bad format; `unavailable` for reserved or other-org-held; `available` when free or held by the requesting org itself (R3.2–R3.6)
    - _Requirements: 2.2, 2.3, 2.4, 2.7, 2.8, 3.2, 3.3, 3.4, 3.5, 3.6, 8.4, 8.5_
  - [x] 3.2 Write property test for slug format acceptance
    - **Property 4: Slug format acceptance**
    - **Validates: Requirements 2.2, 2.3** — Hypothesis ≥100 examples; accept iff 3–63 chars and matches the slug regex; every rejection carries a human-readable reason and is never stored
  - [x] 3.3 Write property test for slug normalisation
    - **Property 5: Slug normalisation is idempotent and case-insensitive**
    - **Validates: Requirements 2.7, 2.8** — ≥100 examples; `normalise(normalise(x)) == normalise(x)`, any case variant normalises identically
  - [x] 3.4 Write property test for reserved-slug rejection
    - **Property 7: Reserved-slug superset and rejection**
    - **Validates: Requirements 2.4, 8.4, 8.5** — ≥100 examples; assert `RESERVED_SLUGS` contains every known top-level route segment and any reserved candidate is rejected on save and reported `unavailable` (never `available`)
  - [x] 3.5 Write property test for availability classifier totality
    - **Property 8: Availability classifier totality**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6** — ≥100 examples over candidate × (holder = none|self|other); assert exactly one of `{available, unavailable, invalid}`, `invalid` for bad format, `available` only when free or own current slug

- [x] 4. Staff identity uniqueness alignment + dedup helper
  - [x] 4.1 Align `StaffService._check_duplicates` in `app/modules/staff/service.py`
    - Change the email comparison to normalised, case-insensitive, active-scoped — `func.lower(func.btrim(StaffMember.email)) == value.strip().lower()` AND `is_active` — so the app check reaches an identical duplicate determination to `uq_staff_active_email_per_org`; apply the same active-scoped comparison to the employee-identifier branch; reject duplicate create/update with a human-readable "duplicate email" `{message, code}` leaving the existing staff member unchanged (R1.5, R1.9)
    - _Requirements: 1.1, 1.5, 1.9_
  - [x] 4.2 Extract pure dedup survivor-selection helper
    - Add `select_dedup_survivor(group, now) -> survivor` (and `partition_dedup_group`) as a pure, side-effect-free function (in `app/modules/staff/service.py` or a small `staff/dedup.py`): given a group of active staff sharing a normalised email/employee identifier, return the survivor (earliest `created_at`, tie → smallest `id`) and the losers; never mutates input. The migration's Step 3 (task 1.1) uses this exact ordering rule
    - _Requirements: 1.7_
  - [x] 4.3 Write property test for org-scoped active staff uniqueness
    - **Property 1: Org-scoped active staff identity uniqueness**
    - **Validates: Requirements 1.2, 1.3, 1.5, 1.6** — Hypothesis ≥100 examples over generated staff across orgs (async DB fixture); after applying uniqueness rules no two active staff in the same org share normalised email or non-empty employee id, the same email may be active in different orgs, and inactive duplicates are unconstrained
  - [x] 4.4 Write property test for dedup survivor selection
    - **Property 2: De-duplication survivor selection**
    - **Validates: Requirements 1.7** — ≥100 examples over arbitrary groups (pure, no DB); exactly one survivor (earliest `created_at`, tie → smallest id), every other member marked inactive, nothing outside the active scope deleted or altered
  - [x] 4.5 Write property test for app/DB duplicate-determination parity
    - **Property 3: Application duplicate-check equals database determination**
    - **Validates: Requirements 1.9, 5.2** — ≥100 examples over candidate email/identifier × existing population (async DB fixture); the app-level check returns "duplicate" iff the DB partial unique index would reject the insert (identical trim+lowercase normalisation)

- [x] 5. Employee portal auth core + session service
  - [x] 5.1 Implement `app/modules/employee_portal/auth.py`
    - Mirror `app/modules/fleet_portal/auth.py`: bcrypt password verify/hash helpers; a **pure** lockout state machine — `is_locked(failed_attempts, locked_until, now)`, `record_failed_attempt(...)` (5th consecutive failure → `locked_until = now + 15min`, R6.5), `reset_lockout(...)` (count → 0 once the 15-minute window elapses or on success, R6.6); a **pure** `validate_password_length(pw) -> (ok, message)` accepting iff `8 <= len <= 128` (R5.6, R14.7)
    - _Requirements: 5.5, 5.6, 6.5, 6.6, 14.4, 14.7_
  - [x] 5.2 Implement `app/modules/employee_portal/services/session_service.py`
    - Mirror the fleet session service: `create_session(db, user, ...)` mints a 32-byte `secrets.token_urlsafe(32)` raw token (stored as `sha256` hash) + CSRF token, `expires_at = created_at + 12h`; `destroy_session`; bulk-invalidation helpers (`delete_sessions_for_org`, `delete_sessions_for_user`) used by disable/revoke/deactivate/reset; and a **pure** `is_session_valid(created_at, last_seen_at, now) -> bool` — valid iff within 12h absolute AND within 30-min idle window (R6.10); a valid request touches `last_seen_at`
    - _Requirements: 6.1, 6.2, 6.9, 6.10_
  - [x] 5.3 Write property test for the lockout state machine
    - **Property 14: Lockout state machine**
    - **Validates: Requirements 6.5, 6.6** — ≥100 examples (pure, no DB); 5 consecutive failures → locked 15 min, attempts during the lock rejected as locked, count resets to 0 after the window
  - [x] 5.4 Write property test for the session validity window
    - **Property 16: Session validity window**
    - **Validates: Requirements 6.10** — ≥100 examples over (created_at, last_seen_at, now) (pure, no DB); valid iff within 12h absolute AND 30-min idle, invalid outside either bound
  - [x] 5.5 Write property test for password length acceptance and hashing
    - **Property 11: Password length acceptance and hashing**
    - **Validates: Requirements 5.5, 5.6, 14.4, 14.7** — ≥100 examples incl. boundary lengths 7/8/128/129; accepted iff 8..128, out-of-range leaves stored state unchanged, accepted password persisted only as a hash (DB fixture for the persistence assertion)

- [x] 6. Employee portal account service
  - [x] 6.1 Implement `app/modules/employee_portal/services/account_service.py`
    - `issue_access(db, org_id, staff)` — app-level dup check (`lower(btrim(email))` vs active users, R5.7) then INSERT `employee_portal_users` with `invite_token_hash = sha256(raw)`, `invite_sent_at = now`, `password_hash = NULL`; returns the created user + raw invite token (R5.3, R5.5, R5.8)
    - `accept_invite(db, raw_token, new_password)` — resolve by `sha256`, require fresh (≤7 days, not accepted, R5.9), validate length 8..128, set `password_hash = bcrypt(pw)`, `invite_accepted_at = now`, clear `invite_token_hash` (single-use, never stores plaintext)
    - `request_reset(db, org_id, email)` / `complete_reset(db, raw_token, new_password)` — `reset_token_hash = sha256(raw)`, `reset_token_expires_at = now + 3600s` (R14.3); on complete require unexpired+unused, validate length, set hash, clear `reset_token_hash` (single-use, R14.5), and DELETE all of the user's sessions (R14.8)
    - `revoke_access(db, org_id, staff_id)` and `revoke_portal_access_for_staff(db, org_id, staff_id)` — set `is_active = false` + delete the user's sessions in the same transaction (R5.10, R5.11)
    - Write `employee_portal_audit_log` rows for `credential_issued` / `access_revoked`; tokens generated with `secrets.token_urlsafe(32)` and stored only as hashes
    - _Requirements: 5.3, 5.5, 5.7, 5.8, 5.9, 5.10, 5.11, 14.3, 14.5, 14.6, 14.8_
  - [x] 6.2 Write property test for single-use credential token consumption
    - **Property 20: Single-use credential token consumption**
    - **Validates: Requirements 5.9, 14.5, 14.6** — ≥100 examples (async DB fixture); successful consumption updates the credential and invalidates the token (second use rejected); expired/used/unknown tokens are rejected and leave the stored hash unchanged
  - [x] 6.3 Write property test for portal-user / org-user store separation
    - **Property 10: Portal-user / org-user store separation**
    - **Validates: Requirements 5.1** — ≥100 examples (async DB fixture); a portal-user credential authenticates only at `/e/api/auth/*` and never at the global `/api/v*/auth` endpoints, and an org-user credential never authenticates as a portal user — disjoint identity stores

- [x] 7. Employee portal email delivery
  - [x] 7.1 Implement `app/modules/employee_portal/employee_portal_delivery.py`
    - Two never-raising helpers built on `app/integrations/email_sender.py` (`send_email` + `render_transactional_html`, multi-provider failover), mirroring the onboarding/roster delivery pattern: `send_credential_setup_email(*, staff_email, org_name, set_password_url, expiry_hint="7 days") -> SendResult` (org name + set-password CTA to the branded `/e/{slug}/accept-invite/{token}`, 7-day expiry copy, never includes a raw password) and `send_password_reset_email(*, staff_email, org_name, reset_url, expiry_hint="60 minutes") -> SendResult`
    - Both return a result object (never raise on provider failure); dispatched after DB commit by the API layer and folded into the response (R15.3)
    - _Requirements: 15.1, 15.2, 15.4, 15.5_

- [x] 8. Checkpoint — backend services + pure cores
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Admin API — settings, slug, enablement, credential issuance/revoke
  - [x] 9.1 Add `employee_portal_enabled` to the org-settings allow-list
    - Add `employee_portal_enabled` to `SETTINGS_JSONB_KEYS` and to the toggle-defaults map in `_load_org_settings_from_db` (default `False`) in `app/modules/organisations/service.py`, so existing orgs read as disabled (R4.1, R17.1)
    - _Requirements: 4.1, 17.1_
  - [x] 9.2 Implement `GET /api/v2/organisations/slug-availability` (JWT + `org_admin`)
    - On the authenticated organisations router: `?slug={candidate}` → `{result, reason}` using `slug_service.normalise_slug` + `validate_slug_format` + `is_reserved` + a `lower(slug)` holder lookup fed into `classify_availability`, returning within 1s; require `org_admin` of the target org (R4.2/R4.3)
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 4.2, 4.3_
  - [x] 9.3 Implement `PUT /api/v2/organisations/slug` (JWT + `org_admin`)
    - Normalise → validate format (`422 slug_invalid_format`) → reserved check (`422 slug_reserved`) → **save-time** uniqueness re-check (`409 slug_taken`, R3.9/R2.6) → `UPDATE organisations SET slug = :n` (stored normalised, R2.7) → `write_audit_log` (previous/new value) → `invalidate_org_settings_cache`. Hard cut-over (D2): an existing slug is replaced and the old value freed immediately; no immutability branch. `403` for non-admin/cross-org
    - _Requirements: 2.1, 2.6, 2.7, 2.9, 2.11, 3.9, 4.2, 4.3, 4.7_
  - [x] 9.4 Implement `PUT /api/v2/organisations/employee-portal` toggle (JWT + `org_admin`)
    - `{enabled}` → if enabling while `organisations.slug IS NULL`, reject `422 slug_required` leaving the flag disabled (R4.4); else `update_org_settings(employee_portal_enabled=enabled)` + `write_audit_log` (R4.7). On **disable**, `DELETE FROM employee_portal_sessions WHERE org_id=?` in the same `session.begin()` transaction (R4.6). A failed audit write rolls back the whole change (R4.8). `403` for non-admin
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_
  - [x] 9.5 Implement credential issuance/revoke on the staff router + auto-revoke on deactivation
    - `POST /api/v2/staff/{staff_id}/portal-access` → require `staff.email` (`422 email_required`, R15.6), `account_service.issue_access`, then **after commit** `employee_portal_delivery.send_credential_setup_email` folded into `{invite_sent, invite_error}` (all-providers-fail still returns `201` with the user preserved, R15.3); `DELETE /api/v2/staff/{staff_id}/portal-access` → `account_service.revoke_access` (R5.10). Add a `revoke_portal_access_for_staff(...)` sibling call into the existing `deactivate_staff` and the `update_staff` termination branch, in the same transaction as the `is_active=False` flip (R5.11). Module-gated, org-scoped, audit-logged
    - _Requirements: 5.3, 5.5, 5.7, 5.8, 5.10, 5.11, 15.1, 15.3, 15.6_
  - [x] 9.6 Write property test for global slug uniqueness
    - **Property 6: Global slug uniqueness**
    - **Validates: Requirements 2.5, 2.6** — ≥100 examples over slug-assignment sequences across orgs (async DB fixture); no two orgs ever hold the same normalised slug; assigning an other-org slug is rejected `taken` and stores nothing
  - [x] 9.7 Write property test for portal-enable requiring a valid slug
    - **Property 9: Enabling the portal requires a valid slug**
    - **Validates: Requirements 4.4** — ≥100 examples (async DB fixture); enable succeeds only with a valid slug set; otherwise the flag stays disabled and a human-readable "set a slug first" message is returned
  - [x] 9.8 Write property test for session invalidation
    - **Property 17: Session invalidation on disable / revoke / deactivate / logout / reset**
    - **Validates: Requirements 4.5, 4.6, 5.10, 5.11, 6.9, 14.8** — ≥100 examples (async DB fixture); after portal disable, access revoke, staff deactivation, logout, or password reset, no prior session for the affected scope remains valid

- [x] 10. Public portal auth API (`/e/api/auth/*`, cookie auth)
  - [x] 10.1 Implement `POST /e/api/auth/login` in `app/modules/employee_portal/router.py`
    - Resolve org by `normalise_slug(slug)`; require `employee_portal_enabled` (else neutral `403 portal_unavailable`, R4.5); unknown slug → neutral `404 portal_unavailable` (R6.11, no enumeration). Set RLS `app.current_org_id` from the resolved org (server-trusted). Look up the active portal user by `lower(email)`; honour lockout (`403 account_locked`); on bad email/password record a failed attempt (only when the user exists) + audit `login_failed` and return generic `401 invalid_credentials` (identical text regardless, R6.4/R16.6); on success reset lockout, `session_service.create_session`, audit `login_success`, and `Set-Cookie` `emp_portal_session` (HttpOnly, `path=/e`, Secure in staging/prod) + `emp_portal_csrf` (readable). Mount the router so cookies are path-scoped to `/e` (R6.1, R6.2)
    - _Requirements: 4.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.11, 16.6_
  - [x] 10.2 Implement `POST /e/api/auth/logout` and `GET /e/api/auth/me` in `router.py`
    - `logout` (CSRF-validated double-submit) destroys the current session row and clears both cookies (R6.9). `me` validates the session via `is_session_valid` (row exists, within 12h absolute, not idle >30 min), touches `last_seen_at`, and returns `{portal_user_id, email, first_name, staff_id, org_name, branding}`; `401 session_invalid` otherwise (R6.10). Enforce the CSRF double-submit (`X-CSRF-Token` == `emp_portal_csrf`) on all state-changing `/e/api` requests in the portal dependency layer (R6.7, R6.8)
    - _Requirements: 6.7, 6.8, 6.9, 6.10_
  - [x] 10.3 Implement accept-invite endpoints in `router.py`
    - `GET /e/api/auth/accept-invite/{token}` → `{status: valid|used|expired|not_found, org_name, email}`; `POST` → `account_service.accept_invite` returning `200 {ok}`, `410 invite_expired` (>7d, R5.9), `422 password_length` (R5.6), `404 invite_not_found`. No portal-user state changes on failure
    - _Requirements: 5.5, 5.6, 5.8, 5.9_
  - [x] 10.4 Implement password reset endpoints in `router.py`
    - `POST /e/api/auth/password/reset-request` resolves org by slug, issues a reset token for an active user when matched, dispatches `send_password_reset_email` **after** commit, and **always** returns a byte-for-byte identical `200` confirmation within 5s (anti-enumeration, R14.1, R15.5). `POST /e/api/auth/password/reset` → `account_service.complete_reset`: `400 reset_token_invalid` (expired/used/unknown, hash unchanged, R14.6), `422 password_length` (R14.7), `200 {ok}` on success (sessions deleted, R14.8)
    - _Requirements: 14.1, 14.5, 14.6, 14.7, 14.8, 15.5_
  - [x] 10.5 Write property test for single-organisation login resolution
    - **Property 12: Single-organisation login resolution**
    - **Validates: Requirements 6.3, 6.11** — ≥100 examples (async DB fixture); a login with a slug resolves the user within exactly that org and never authenticates a user of another org; an unresolvable slug yields a neutral not-found with no session
  - [x] 10.6 Write property test for anti-enumeration response invariance
    - **Property 13: Anti-enumeration response invariance**
    - **Validates: Requirements 6.4, 14.1, 16.6** — ≥100 examples (async DB fixture); two login/reset requests differing only in whether the email matches an active user produce identical status/code/message, and a failed unknown-email login still writes an audit row with a null portal-user reference
  - [x] 10.7 Write property test for CSRF double-submit enforcement
    - **Property 15: CSRF double-submit enforcement**
    - **Validates: Requirements 6.7, 6.8** — ≥100 examples (integration against the portal app); a state-changing `/e/api` request is processed iff the `X-CSRF-Token` header equals the `emp_portal_csrf` cookie; missing/mismatched → rejected with no state change

- [x] 11. Public branding, mobile resolution, and authenticated portal data
  - [x] 11.1 Implement `GET /e/api/branding/{slug}` in `router.py`
    - Case-insensitive slug match; `200 {org_name, logo_url|null, primary_colour|null, secondary_colour|null}` only when the slug resolves AND the portal is enabled; otherwise neutral `404 portal_unavailable` (no existence leak, R8.3). Returns name + branding only, no other org data (R13.4)
    - _Requirements: 8.1, 8.2, 8.3, 13.1, 13.4_
  - [x] 11.2 Implement `GET /api/v2/public/portal-resolve` (public, no auth)
    - `?q={1..100}&portal_type={employee|fleet}`: exact slug match first (single result), else name `ILIKE` match filtered to orgs with the requested portal type enabled, cap 10 candidates, branding-only fields. `200 {match}` for exactly one + enabled (R9.1); `200 {candidates}` for multiple name matches (R9.4, never auto-resolve); `404 not_found` for none or disabled (R9.3, R9.8, no enumeration). For `employee`, "enabled" = `employee_portal_enabled` + slug set; for `fleet`, the fleet module gate. No auth (R9.2)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.8, 8.3_
  - [x] 11.3 Implement `GET /e/api/profile` in `router.py`
    - Session required; sources `staff_members` for the session's `staff_id`, RLS-scoped to the session's `org_id`; PII masked via `mask_ird` / `mask_bank_account` from `app/modules/staff/security.py`; `409 not_linked` when the portal user has no linked staff (R7.7). Own record only — foreign/not-owned → `404`/`403` with no fields and no existence disclosure (R7.5, R16.4)
    - _Requirements: 7.1, 7.5, 7.7, 16.3, 16.4_
  - [x] 11.4 Implement `GET /e/api/roster` in `router.py`
    - Session required; reuse the existing staff roster data path (`app/modules/staff/public_router.py` / scheduling) rather than duplicating it (R7.4), scoped to the session's `staff_id` + `org_id` (R7.1). Own roster only
    - _Requirements: 7.1, 7.2, 7.4_
  - [x] 11.5 Write property test for slug-resolution minimal exposure
    - **Property 21: Slug-resolution minimal exposure**
    - **Validates: Requirements 9.3, 9.4, 9.5, 9.8, 8.3** — ≥100 examples (async DB fixture); responses contain only org name + branding, at most 10 candidates, never auto-resolve an ambiguous name, and reveal nothing (not even branding) for non-matching or disabled-portal orgs
  - [x] 11.6 Write property test for tenant and owner isolation
    - **Property 19: Tenant and owner isolation**
    - **Validates: Requirements 7.1, 7.5, 16.3, 16.4** — ≥100 examples (async DB fixture); every record returned by an authenticated portal request belongs to both the session's org and its linked staff member; out-of-scope requests are denied with no fields and no existence signal
  - [x] 11.7 Write property test for cookie scoping and cross-portal rejection
    - **Property 18: Cookie scoping and cross-portal rejection**
    - **Validates: Requirements 6.1, 6.2, 16.7, 16.8** — ≥100 examples (integration); the session cookie is HttpOnly, `path=/e`, Secure in staging/prod; a customer/fleet/staff session or CSRF cookie never validates as an employee portal credential (structural — separate `employee_portal_sessions` table)

- [x] 12. Middleware, CSRF, and rate-limit wiring
  - [x] 12.1 Wire JWT-bypass and CSRF exemption for the portal API
    - Add `/e/api/` to `PUBLIC_PREFIXES` in `app/middleware/auth.py` (cookie auth, not JWT — mirrors `/fleet/api/`); add `/e/api/auth/` to `_CSRF_EXEMPT_PREFIXES` in `app/middleware/security_headers.py` so the portal's own double-submit CSRF is not blocked by the global staff CSRF check
    - _Requirements: 6.2, 6.7, 6.8, 16.7, 16.8_
  - [x] 12.2 Add the four rate-limit prefix blocks in `app/middleware/rate_limit.py`
    - Add constants + enforcement blocks mirroring the existing `_PUBLIC_STAFF_ROSTER_*` / `_PASSWORD_RESET_PATHS` blocks (per-IP sliding window via `_check_rate_limit`, `429` + `Retry-After`, no action on exceed): login `/e/api/auth/login` 10/min, slug-availability `/api/v2/organisations/slug-availability` 30/min, portal-resolve `/api/v2/public/portal-resolve` 30/min, password-reset `{/e/api/auth/password/reset-request, /e/api/auth/password/reset}` 5/min. Place the login block alongside the auth-endpoint blocks so the stricter limit applies before generic limits
    - _Requirements: 3.1, 9.6, 9.7, 16.1, 16.2_
  - [x] 12.3 Add the nginx `/e/api/` proxy location to every active gateway config
    - The portal API at `/e/api/` does **not** match the existing `location /api/` block, so without a dedicated location it falls through to `location /` and is served the SPA `index.html` instead of reaching the backend — exactly why the fleet portal has its own `location /fleet/api/`. Add an analogous `location /e/api/ { proxy_pass http://backend; ... }` block (copy the `proxy_set_header`/upstream settings from the existing `/fleet/api/` block) to **`nginx/nginx.dev-v2.conf`** (local dev), **`nginx/nginx.pi-v2.conf`** (Pi prod, behind Cloudflare), and the canonical **`nginx/nginx.conf`**. Do NOT add a block for the SPA routes `/e/{slug}` and `/e/{slug}/...` — they correctly fall through to `location /` → `frontend_v2`. Verify with `curl` that `/e/api/branding/{slug}` reaches the backend (JSON, not HTML) in dev before marking done
    - _Requirements: 8.1, 8.6, 17.2, 17.3_

- [x] 13. Checkpoint — backend portal fully wired
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Frontend-v2 — branded login, portal app, org settings panel
  - [x] 14.1 Create `frontend-v2/src/pages/employee-portal/EmployeePortalLogin.tsx` (`/e/:slug`)
    - Reads `:slug`, fetches `GET /e/api/branding/{slug}` via **raw `import axios from 'axios'`** (not the shared `apiClient`, which redirects to `/login` on 401 and injects staff auth headers — same rule the onboarding/roster public pages follow); renders the branded login or the neutral "portal unavailable" page on `404` (R8.3); injects `<meta name="robots" content="noindex">` (R8.7); logo falls back to a default if missing or slow >2s (R13.2, R13.3). Posts to `POST /e/api/auth/login` with `withCredentials: true`
    - _Requirements: 8.1, 8.3, 8.7, 13.1, 13.2, 13.3_
  - [x] 14.2 Create `frontend-v2/src/pages/employee-portal/EmployeePortalApp.tsx` (`/e/:slug/*`)
    - Authenticated shell (profile + roster MVP) calling `/e/api/*` with `withCredentials: true` and echoing the `emp_portal_csrf` cookie as `X-CSRF-Token` on writes; profile view renders masked PII + handles `not_linked`; roster view renders the own-roster entries; logout calls `/e/api/auth/logout`; injects `noindex` on authenticated pages (R8.7)
    - Per the **frontend-feature-completeness** steering, every authenticated view (profile, roster) MUST implement the full state set: a **loading skeleton** during fetch, an **empty state** with a helpful message (e.g. roster with no entries for the week), and an **error state with a retry action** on fetch failure — never a blank screen; a `401 session_invalid` routes back to the branded login. Use an `AbortController` in every fetch `useEffect` and safe consumption (`res.data?.x ?? default`, typed generics, no `as any`)
    - _Requirements: 7.1, 7.2, 7.7, 8.7, 13.1_
  - [x] 14.3 Register the portal routes in `frontend-v2/src/App.tsx`
    - Add `<Route path="/e/:slug" element={<EmployeePortalLogin />} />` and `<Route path="/e/:slug/*" element={<EmployeePortalApp />} />` **above** the `<Route path="*" element={<PublicPageRenderer />} />` catch-all and outside `RequireAuth`/`GuestOnly`, so score-based matching resolves them before the marketing catch-all (R8.4); leave `PublicPageRenderer` unchanged (R17.3)
    - _Requirements: 8.4, 17.3_
  - [x] 14.4 Add the Org Settings → Employee Portal panel
    - In the organisation settings page, add a panel with a slug input wired to **live availability**: debounce ≥300ms after typing stops, call `GET /api/v2/organisations/slug-availability`, display exactly one of available/unavailable/invalid before save, and on timeout/error show "could not complete" and never "available" (R3.1, R3.2, R3.7, R3.8); a Save action calls `PUT /api/v2/organisations/slug` and retains the entered value on a save-time `409` (R3.9); an enable toggle calls `PUT /api/v2/organisations/employee-portal`, surfacing the `slug_required` message when enabling without a slug (R4.4). Safe API consumption (`?.`, `?? default`), typed generics
    - _Requirements: 3.1, 3.2, 3.7, 3.8, 3.9, 4.1, 4.2, 4.4_
  - [x] 14.5 Write frontend-v2 unit tests
    - Vitest + React Testing Library: branded-login renders branding and the neutral unavailable page on `404`, `noindex` meta present (R8.7); settings panel debounced availability states (available/unavailable/invalid + "could not complete" on error, never "available"), save-time `409` retains input, enable-without-slug message; profile masked-PII + `not_linked` rendering
    - _Requirements: 3.2, 3.7, 3.8, 3.9, 4.4, 7.7, 8.3, 8.7, 13.2_

- [x] 15. Mobile — portal selection, lookup, branded login, version surface
  - [x] 15.1 Create `mobile/src/contexts/PortalSelectionContext.tsx`
    - Owns the persisted `PortalSelection` (`{portal_type: 'org'|'employee'|'fleet', org_id?, slug?, api_base}`) via Capacitor **Preferences** key `"portal_selection"` (JSON, survives restart); `load()` returns "no selection" (cleared) for absent/malformed/garbage blobs rather than crashing; `save(sel)`; `clear()`. Guard all Capacitor calls with `isNativePlatform()` + try/catch
    - _Requirements: 11.1, 11.4_
  - [x] 15.2 Add portal-aware API base resolution + generalise `AuthContext`
    - Extend `mobile/src/api/client.ts` base resolution to be portal-aware from `PortalSelection.api_base`: `org → …/api/v1` (JWT, unchanged), `employee → …/e/api` (cookie + CSRF), `fleet → …/fleet/api` (cookie + CSRF) — deterministic on restart (R11.8); generalise `mobile/src/contexts/AuthContext.tsx` so cookie portals use `withCredentials` + the CSRF header instead of a Bearer token, leaving the existing org-user JWT flow unchanged (R17.4). If the base cannot be resolved/reached, clear the selection, show an error, and return to the selector (R11.9); a rejected persisted employee session routes to that org's branded login, not the selector (R12.5); a disabled portal shows "portal unavailable" + a "switch portal" action (R11.6, R11.7, R12.6)
    - _Requirements: 11.6, 11.7, 11.8, 11.9, 12.5, 12.6, 17.4_
  - [x] 15.3 Create `mobile/src/screens/portal-select/PortalTypeSelector.tsx`
    - First-run screen shown when no selection is persisted and no session exists; exactly three 44×44px choices (R10.1, R10.8). "Organisation" → existing org-user login + persist `{type:'org'}` so the selector is not shown again (R10.2); "Employee/Staff" or "Fleet" → route to `OrgLookupScreen`
    - _Requirements: 10.1, 10.2, 10.8_
  - [x] 15.4 Create `mobile/src/screens/portal-select/OrgLookupScreen.tsx`
    - Name-or-slug input (1..100 chars, R10.3); on submit call `GET /api/v2/public/portal-resolve?q=&portal_type=` with a 10s timeout and a loading spinner that disables submit (R10.5); single match → branded login; multiple → disambiguation list (re-resolve by org); none/disabled → inline error retaining input (R10.6, R12.1, R12.2); timeout/failure → error + retry retaining input (R10.7, R12.3); offline with no persisted selection → "network required" message, never blank (R12.4); use `AbortController` in the effect
    - _Requirements: 10.3, 10.5, 10.6, 10.7, 12.1, 12.2, 12.3, 12.4_
  - [x] 15.5 Create `mobile/src/screens/portal-select/EmployeePortalLoginScreen.tsx`
    - Renders branding from the resolve response (R13.5); falls back to neutral default if branding missing or slow >5s while keeping the form usable (R13.6); on successful login persist the selection (R11.1); if persistence fails, finish the session but warn and show the selector next start (R11.2). Calls `POST /e/api/auth/login` via the portal-aware base with `withCredentials`
    - _Requirements: 10.4, 11.1, 11.2, 13.5, 13.6_
  - [x] 15.6 Surface the app version on the mobile More/Settings screen
    - Display the app semantic version (`MAJOR.MINOR.PATCH`) ≥ the release introducing the Portal_Type_Selector, reusing the existing version display surface (R19.4)
    - _Requirements: 19.4_
  - [x] 15.7 Write property test for portal-selection persistence round-trip
    - **Property 22: Mobile portal-selection persistence round-trip**
    - **Validates: Requirements 11.1, 11.4** — fast-check ≥100 runs over generated `PortalSelection` values incl. malformed/garbage blobs; save→load returns an equal selection (survives restart), and absent/malformed loads return "no selection" so the selector is shown rather than crashing
  - [x] 15.8 Write property test for per-portal API base resolution
    - **Property 23: Mobile per-portal API base resolution**
    - **Validates: Requirements 11.8** — fast-check ≥100 runs; resolving the API base from a persisted portal type is deterministic and yields the correct surface (`org → …/api/v1`, `employee → …/e/api`, `fleet → …/fleet/api`)
  - [x] 15.9 Write mobile UI-state unit tests
    - Vitest + RTL: selector shows three 44px choices; lookup spinner disables submit; none/disabled and timeout/failure errors retain input and never blank; offline "network required"; branded login default-branding fallback keeps the form usable (R10.5, R10.8, R12.1–R12.4, R13.6)
    - _Requirements: 10.5, 10.8, 12.1, 12.2, 12.3, 12.4, 13.6_

- [x] 16. Checkpoint — full stack wired
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Integration, example, and smoke tests + final verification
  - [x] 17.1 Write example & edge-case unit tests
    - Slug set/availability happy path + own-org-slug-available branch (R3.5) + save-time race rejection (R3.9); invite/reset boundary lengths (7/8/128/129) and token-expiry boundaries (7-day invite, 3600s reset); login generic-message identity for existing vs non-existing email; profile PII masking + unlinked `not_linked`; onboarding-completion → portal as login destination (R5.4)
    - _Requirements: 3.5, 3.9, 5.4, 5.5, 5.8, 5.9, 7.7, 14.3_
  - [x] 17.2 Write integration test for concurrent duplicate staff insert
    - Two concurrent active inserts with the same normalised email in one org → exactly one persists, the other rejected with a duplicate error, no partial record
    - _Requirements: 1.4_
  - [x] 17.3 Write integration test for disable-portal session teardown
    - Disabling the portal removes all active sessions for the org by the next request (R4.6 end-to-end)
    - _Requirements: 4.5, 4.6_
  - [x] 17.4 Write integration test for credential + reset email dispatch
    - Credential-setup and reset emails dispatched through `send_email` failover (R15.1, R15.5); the all-providers-fail path preserves the created portal user (R15.3)
    - _Requirements: 15.1, 15.3, 15.5_
  - [x] 17.5 Write integration test for cross-portal cookie rejection
    - Present a `fleet_portal_session` cookie to `GET /e/api/auth/me` → rejected (R16.8)
    - _Requirements: 16.7, 16.8_
  - [x] 17.6 Write integration test for rate-limit enforcement
    - Drive each of the four configured limits past threshold and assert `429` + `Retry-After` with no action/session (login 10/min, slug-availability 30/min, portal-resolve 30/min, password-reset 5/min)
    - _Requirements: 9.6, 9.7, 16.1, 16.2_
  - [x] 17.7 Write integration test for migration ordering + idempotency
    - Seed active duplicates, run the migration, assert dedup-before-constraint ordering, the halt-on-remaining-duplicates guard (R17.7), the per-group audit record (R1.8), and that a second run is a no-op (R17.6)
    - _Requirements: 1.7, 1.8, 17.5, 17.6, 17.7_
  - [x] 17.8 Write regression test for untouched customer/fleet portals
    - Assert the customer portal (`/portal/{token}`) and fleet portal (`/fleet/...`) behave unchanged after deploy (R17.3)
    - _Requirements: 17.3_
  - [x] 17.9 Write smoke checks for HTTPS redirect and noindex
    - Assert HTTP→HTTPS redirect handling at the proxy tier for `/e/*` (R8.6) and that the `noindex` robots meta is present on the branded login and authenticated pages (R8.7)
    - _Requirements: 8.6, 8.7_
  - [x] 17.10 Write the mandatory end-to-end test script (`scripts/test_organisation_employee_portal_e2e.py`)
    - Per the always-on **feature-testing-workflow** steering ("no feature ships without a passing test script"), add an httpx-based script in `scripts/` (run via `docker exec invoicing-app-1 python scripts/test_organisation_employee_portal_e2e.py`, base `http://localhost:8000`) that emulates the real user journey end-to-end: org_admin sets a slug (live availability → save) and enables the portal; issues portal access for a staff member; accept-invite sets a password; portal login establishes the session cookie + CSRF; profile + roster fetch own-records-only; password reset request→complete; revoke/disable tears down sessions
    - Include the OWASP checks from the steering: unauthenticated `/e/api` access rejected; cross-org IDOR (org A session cannot read org B records → 404/403, no fields); anti-enumeration (identical login + reset responses for existing vs unknown email); cross-portal cookie rejection (`fleet_portal_session` → `/e/api/auth/me` rejected); rate-limit 429s on the four limits; no secrets/stack traces leaked in error bodies
    - Track every created resource id and **clean up all of it in a `finally` block** (portal users, sessions, audit rows, the org slug, staff/test users), using the `TEST_E2E_` naming prefix; verify cleanup left no residue and report any leftover as a failure
    - _Requirements: 4.5, 4.6, 5.3, 6.1, 6.4, 7.1, 7.5, 14.1, 16.1, 16.4, 16.8_
  - [x] 17.11 Final verification
    - Run the backend suite (pytest incl. Hypothesis ≥100 examples) and frontend/mobile checks (`tsc --noEmit`, `vitest --run`, fast-check); run `alembic upgrade head` against `postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro` to confirm `0224` applies cleanly; run the Task 17.10 e2e script and confirm it passes with clean teardown; verify `curl http://localhost/e/api/branding/{slug}` returns backend JSON (not SPA HTML) confirming the nginx `/e/api/` block (Task 12.3); run `get_diagnostics` on the spec files and fix any reported issues
    - _Requirements: all_

- [x] 18. Version bump and changelog
  - [x] 18.1 Bump version and add a CHANGELOG entry (MINOR feature)
    - Per the **versioning-and-changelog** steering, this new feature is a MINOR bump (x.Y.0) above the current `1.13.0` (R19.1, R19.2); bump the backend version in `app/__init__.py` and the `frontend-v2/package.json` version (reconcile `pyproject.toml`/mobile version surface so the mobile semver is ≥ the release that introduced the Portal_Type_Selector, R19.4); add a top (newest-first) `CHANGELOG.md` entry under `### Added` summarising the Employee Portal (org slug + branded `/e/{slug}` login, credential issuance/invite/reset, enable/disable toggle, mobile Portal_Type_Selector). If the changelog write fails the release halts (R19.3)
    - _Requirements: 19.1, 19.2, 19.3, 19.4_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific granular requirements for traceability; property-test sub-tasks additionally cite the design property they validate and are tagged in code with `Feature: organisation-employee-portal, Property {n}: {property_text}`.
- All 23 correctness properties are implemented as property-based tests (Hypothesis on the backend, fast-check for the mobile/web pure logic), ≥100 iterations each, placed close to the implementation they validate to catch errors early.
- Pure helpers (slug normalisation/format/reserved/availability classifier, dedup survivor selection, lockout state machine, session-validity predicate, password-length validator) are extracted as side-effect-free functions and property-tested without a DB; DB-invariant properties use the transactional test database.
- Reuse-first throughout: the portal mirrors `app/modules/fleet_portal/` (router, session/CSRF cookies, lockout, audit log); enablement uses the org-settings allow-list + cache; the roster view reuses `app/modules/staff/public_router.py`; profile PII uses `app/modules/staff/security.py`; emails use `app/integrations/email_sender.py`; mobile reuses the Capacitor Preferences + AuthContext stack.
- Checkpoints provide incremental validation after the backend services, after the backend portal is wired, and after the full stack is wired.
- This workflow produces planning artifacts only; implementation is performed when executing the tasks.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4", "3.5", "4.1", "4.2", "5.1", "5.2", "7.1"] },
    { "id": 3, "tasks": ["4.3", "4.4", "4.5", "5.3", "5.4", "5.5", "6.1", "9.1"] },
    { "id": 4, "tasks": ["6.2", "6.3", "9.2", "9.5", "10.1"] },
    { "id": 5, "tasks": ["9.3", "10.2"] },
    { "id": 6, "tasks": ["9.4", "10.3"] },
    { "id": 7, "tasks": ["9.6", "9.7", "9.8", "10.4", "12.1", "12.2", "12.3"] },
    { "id": 8, "tasks": ["10.5", "10.6", "10.7", "11.1", "11.2"] },
    { "id": 9, "tasks": ["11.3", "11.5"] },
    { "id": 10, "tasks": ["11.4", "11.6", "11.7"] },
    { "id": 11, "tasks": ["14.1", "14.2", "14.4", "15.1"] },
    { "id": 12, "tasks": ["14.3", "15.2", "15.3", "15.4", "15.5", "15.6"] },
    { "id": 13, "tasks": ["14.5", "15.7", "15.8", "15.9", "17.1", "17.2", "17.3", "17.4", "17.5", "17.6", "17.7", "17.8", "17.9", "17.10"] },
    { "id": 14, "tasks": ["17.11"] },
    { "id": 15, "tasks": ["18.1"] }
  ]
}
```
