# Implementation Plan: Staff Onboarding Link

## Overview

This plan implements self-service staff onboarding via a secure, token-gated public link, following the design's reuse-first strategy (near-clone of the existing `StaffRosterViewToken` / `public_router.py` / `roster_tokens.py` / rate-limit-prefix pattern). Work proceeds bottom-up: schema → ORM → pure validators & token service → email delivery → admin endpoints → public endpoints → rate limit → frontend → cross-cutting tests and verification.

Backend is Python 3.11 / FastAPI / SQLAlchemy (async) / Alembic; frontend is the active `frontend-v2/` React + TypeScript + Vite SPA. Property tests use **Hypothesis** (≥100 iterations each, tagged with the design property number); example and integration tests use pytest; frontend tests use Vitest + React Testing Library (+ fast-check for client-side validator parity).

Pure, side-effect-free functions (NZ bank / IRD / emergency-contact / document validators, token-state classification, email composition, completion-percentage, lifecycle-label, humanized-error mapping) are extracted so the 27 correctness properties can be property-tested without a DB where possible. DB-touching properties (including draft save/load round-trip, save-never-consumes, draft purge on submit/revoke/expiry, and the completion side-effects on submit vs draft) use the existing async DB test session fixtures.

## Tasks

- [x] 1. Database migration — onboarding token table + compliance staff link
  - [x] 1.1 Create Alembic revision `0223` off head `0222`
    - New file `alembic/versions/2026_06_1x_xxxx-0223_staff_onboarding_tokens.py` with `revision="0223"`, `down_revision="0222"`
    - Structure the migration in two phases per design.md §Migration Plan: a **transactional phase** (table create, RLS, additive column) followed by a trailing **autocommit phase** (the CONCURRENTLY indexes) that runs **LAST** so its transaction-boundary change does not affect any earlier transactional op
    - Transactional phase — `CREATE TABLE IF NOT EXISTS staff_onboarding_tokens` mirroring `staff_roster_view_tokens` (migration `0203`): `id uuid PK`, `org_id uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE`, `staff_id uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE`, `token_hash varchar(64) NOT NULL`, `status varchar(20) NOT NULL DEFAULT 'pending'`, `created_at timestamptz NOT NULL DEFAULT now()`, `expires_at timestamptz NOT NULL`, `consumed_at timestamptz NULL`, plus the two nullable draft columns inline — `draft_data_encrypted bytea NULL` (whole-blob envelope-encrypted partial form payload, R12.6) and `draft_updated_at timestamptz NULL` (last-saved timestamp / `not_started`⇄`in_progress` discriminator, R12.1, R13.1) — plus `CONSTRAINT uq_staff_onboarding_tokens_hash UNIQUE (token_hash)`. **No new index for the draft columns** — drafts are always read via the same `token_hash` / `staff_id` lookups that already exist
    - Transactional phase — `ENABLE ROW LEVEL SECURITY` (not FORCE) + `DROP POLICY IF EXISTS tenant_isolation` + `CREATE POLICY tenant_isolation ... USING (org_id = current_setting('app.current_org_id', true)::uuid)` — identical posture to `staff_roster_view_tokens`
    - Transactional phase — `ALTER TABLE compliance_documents ADD COLUMN IF NOT EXISTS staff_id uuid NULL` (fast catalogue-only change, no default)
    - Autocommit phase (LAST) — build BOTH indexes with `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...` inside `op.get_context().autocommit_block()` (use the `_run_outside_tx` helper + statement list, mirroring the canonical template `alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py`): `ix_staff_onboarding_tokens_staff ON staff_onboarding_tokens (staff_id, status)` and `ix_compliance_documents_staff ON compliance_documents (staff_id)`. CONCURRENTLY is **mandatory** for `ix_compliance_documents_staff` because `compliance_documents` is an existing, potentially large table (a plain `CREATE INDEX` would take an `ACCESS EXCLUSIVE` lock and block all reads/writes for the build); `ix_staff_onboarding_tokens_staff` uses CONCURRENTLY too for consistency. Never use `op.create_index(...)` or plain `CREATE INDEX`
    - `downgrade()` first drops both indexes with `DROP INDEX CONCURRENTLY IF EXISTS` inside the same `op.get_context().autocommit_block()` (drop `ix_compliance_documents_staff` then `ix_staff_onboarding_tokens_staff`), THEN `DROP TABLE IF EXISTS staff_onboarding_tokens` (which removes the draft columns with it) and `ALTER TABLE compliance_documents DROP COLUMN IF EXISTS staff_id`
    - Keep `IF NOT EXISTS` / `IF EXISTS` guards on every statement for re-runnability (a failed CONCURRENTLY build leaves an INVALID index behind; guards make the migration safely retryable). Follows the **database-migration-checklist** steering
    - _Requirements: 2.2, 7.6, 11.2, 12.6_

- [x] 2. ORM model for onboarding tokens
  - [x] 2.1 Add `StaffOnboardingToken` to `app/modules/staff/models.py`
    - Define the model exactly as in the design (org-scoped, ON DELETE CASCADE, `token_hash String(64) unique`, `status` with `server_default="pending"`, `created_at`/`expires_at`/`consumed_at`), mirroring `StaffRosterViewToken`
    - Add the two draft columns: `draft_data_encrypted: Mapped[bytes | None]` (`LargeBinary`, nullable) and `draft_updated_at: Mapped[datetime | None]` (`DateTime(timezone=True)`, nullable), per the design — NULL until the first draft is saved, NULLed again on submit/revoke/expiry-purge
    - Add `StaffOnboardingToken` to the module `__all__` export
    - _Requirements: 2.1, 2.2, 2.5, 12.6_

- [x] 3. Schemas and pure validators
  - [x] 3.1 Extend staff schemas in `app/modules/staff/schemas.py`
    - Add request-only `send_onboarding_link: bool = False` to `StaffMemberCreate` (email field already exists)
    - Add advisory `onboarding_email_sent: bool | None = None` and `onboarding_email_error: str | None = None` to `StaffMemberResponse`
    - _Requirements: 1.3, 1.4, 3.6_
  - [x] 3.2 Add public prefill/submit/draft schemas
    - Add `OnboardingPrefillResponse` (`first_name`, `email`, `org_name`, `tax_code_options`, `residency_options`, `kiwisaver_rate_options`, `bank_account_required`) and `OnboardingSubmitResponse` (`ok`, `message`/`errors`/`warnings`) in `schemas.py`
    - Add `OnboardingDraftRequest` — an all-optional/partial schema (every field `| None = None`) covering `last_name`, `phone`, `emergency_contact_name`, `emergency_contact_phone`, `bank_account_number`, `ird_number`, `tax_code`, `student_loan`, `kiwisaver_enrolled`, `kiwisaver_employee_rate`, `residency_type`, `visa_expiry_date`, and `documents_staged_count: int | None`
    - Extend `OnboardingPrefillResponse` for resume: add a nullable `draft` object carrying non-sensitive fields in full plus **masked** `ird_number`/`bank_account_number` with `has_ird`/`has_bank` flags and `documents_staged_count`, plus top-level `completion_percentage: int | None` and `last_saved_at: datetime | None`
    - Add `OnboardingDraftResponse` (`ok: bool`, `completion_percentage: int`, `last_saved_at: datetime`)
    - Extend the admin status response (`OnboardingLinkStatusResponse`) with `state` (lifecycle label `not_started`/`in_progress`/`completed`/`expired`/`revoked`/`none`), `completion_percentage: int | None`, and `last_saved_at: datetime | None`
    - Reuse the existing `TaxCode` Literal, `ResidencyType` Literal, and `_KIWISAVER_EMPLOYEE_RATES` for option lists
    - _Requirements: 4.2, 6.1, 8.1, 11.6, 12.3, 12.4, 13.1, 13.2_
  - [x] 3.3 Implement side-effect-free validators in new `app/modules/staff/onboarding_validation.py`
    - `validate_nz_bank_account(s) -> bool`: regex `^\d{2}-\d{4}-\d{7}-\d{2,3}$` (2-4-7-2 / 2-4-7-3)
    - `validate_ird_length(s) -> bool`: strip separators, accept iff exactly 8 or 9 digits; expose `ird_mod11_ok(s)` advisory wrapper around `validate_ird_number` from `app/modules/ledger/service.py`
    - `validate_emergency_contact(name, phone) -> bool`: both-present-or-both-empty
    - `validate_documents(files) -> bool`: ≤3 files, each MIME ∈ {pdf, jpeg, png}, ≤10 MB
    - `validate_visa_expiry(residency_type, expiry_date) -> bool`: for work/student visa types, valid iff `expiry_date` is present AND strictly after today; missing/past/current-dated → invalid (blocking, R8.3). Non-visa residency types are always valid.
    - `compute_completion_percentage(draft) -> int`: five equally-weighted (20%) section predicates (`is_personal_complete` = last_name AND phone; `is_bank_complete` = bank account / `has_bank`; `is_ird_complete` = ird/`has_ird` AND tax_code; `is_residency_complete` = residency_type set, AND visa_expiry when a visa type; `is_documents_complete` = `documents_staged_count > 0`) summed × 20 → integer in `[0, 100]`; deterministic, total (defined for empty/partial drafts), bounded, and monotonic non-decreasing (R13.3, R13.4)
    - `onboarding_lifecycle_label(row, now) -> str`: pure admin lifecycle label evaluated in precedence order none → revoked → completed → expired → in_progress → not_started (`row is None`→`none`; `revoked`→`revoked`; `consumed`→`completed`; `expires_at <= now`→`expired`; `draft_updated_at is not None`→`in_progress`; else `not_started`); total and single-valued, kept separate from `classify_token_state` (R13.1)
    - `humanize_onboarding_error(code) -> str`: maps every token-state rejection (not-found/expired/revoked/consumed/staff-inactive), validation failure, encryption failure (`encryption_failed`), email-send failure (`send_failed`), and unexpected server error (`server_error`) to a non-empty human-readable sentence — never raw DB/exception text — mirroring the `humanize_restore_db_error` precedent (R14.1–R14.5)
    - All functions return structured results (no exceptions, no I/O) so they are property-testable and mirrorable client-side
    - _Requirements: 4.3, 5.2, 6.2, 6.3, 7.2, 7.3, 8.3, 13.1, 13.3, 13.4, 14.1, 14.2, 14.3, 14.4, 14.5_
  - [x] 3.4 Write property test for NZ bank account validation
    - **Property 8: NZ bank account format validation**
    - **Validates: Requirements 5.2** — Hypothesis ≥100 examples, generators include valid 2-4-7-2/2-4-7-3 and malformed strings
  - [x] 3.5 Write property test for IRD length validation
    - **Property 9: IRD number length validation**
    - **Validates: Requirements 6.2, 6.3** — ≥100 examples; generators include separators in IRD strings and non-8/9-digit lengths
  - [x] 3.6 Write property test for emergency-contact pairing
    - **Property 7: Emergency contact is all-or-nothing**
    - **Validates: Requirements 4.3** — ≥100 examples over (name, phone) presence combinations
  - [x] 3.7 Write property test for document upload constraints
    - **Property 10: Document upload constraints**
    - **Validates: Requirements 7.2, 7.3** — ≥100 examples; boundary sizes around 10 MB and exactly-3 vs 4 documents
  - [x] 3.8 Write property test for completion-percentage computation
    - **Property 22: Completion percentage is deterministic, total, bounded, and monotonic**
    - **Validates: Requirements 13.3, 13.4** — Hypothesis ≥100 examples over arbitrary partial/empty drafts; assert same input → same output (deterministic), defined for every draft (total), result ∈ `[0,100]`, and never decreases when more fields are filled (monotonic non-decreasing)
  - [x] 3.9 Write property test for admin lifecycle label
    - **Property 23: Admin lifecycle label is total and single-valued**
    - **Validates: Requirements 13.1** — ≥100 examples over all (status, expiry, draft_updated_at) combos plus `None`; assert exactly one of `not_started`/`in_progress`/`completed`/`expired`/`revoked`/`none` and the documented precedence holds (never blank/ambiguous)
  - [x] 3.10 Write property test for humanized-error totality
    - **Property 24: Every onboarding error carries a non-empty human-readable message**
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5** — ≥100 examples over every onboarding error code; assert `humanize_onboarding_error` returns a non-empty message for each and the emitted object carries both `message` and `code` with no raw DB/exception text

- [x] 4. Onboarding token service
  - [x] 4.1 Create `app/modules/staff/onboarding_tokens.py`
    - Mirror `roster_tokens.py`: `_TOKEN_NBYTES = 32`, `_TOKEN_TTL_DAYS = 7`, `_hash_token(raw)` = SHA-256 hexdigest
    - `mint(db, *, org_id, staff_id) -> str`: revoke any prior pending token for the staff, insert fresh `pending` row storing `token_hash`, `expires_at = now + 7d`, `flush` + `refresh`, return the RAW token
    - `resolve(db, raw) -> StaffOnboardingToken | None`: lookup by `token_hash == _hash_token(raw)`
    - `consume(db, row)`: set `status="consumed"`, `consumed_at=now`, **NULL `draft_data_encrypted` and `draft_updated_at` in the same write** (purge draft on submit, R12.8), flush
    - `revoke_active(db, *, org_id, staff_id) -> int`: bulk `UPDATE ... SET status='revoked', draft_data_encrypted=NULL, draft_updated_at=NULL WHERE staff_id=? AND org_id=? AND status='pending'` (purge draft on revoke/resend/deactivation, R12.9), return affected count
    - `save_draft(db, row, payload)`: serialize the whole partial payload to JSON, `envelope_encrypt(json)` → `draft_data_encrypted`, set `draft_updated_at = now()`; **never touch `status`/`consumed_at`** (saving never consumes, R12.7), flush
    - `load_draft(row) -> dict | None`: `envelope_decrypt_str` the stored blob and parse JSON; `None` when no draft saved
    - `purge_draft(db, row)`: NULL both draft columns, flush
    - Add lazy expiry-purge: on any access that classifies a token as expired (pending + `expires_at <= now`), NULL the draft columns so no partial draft outlives its token (R12.9)
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 10.2, 12.6, 12.7, 12.8, 12.9_
  - [x] 4.2 Extract pure token-state classification function
    - `classify_token_state(row, now, staff_is_active) -> TokenState` evaluating in order: none → revoked → consumed → expired → staff_inactive → valid; side-effect-free, the single source of truth for both public router and admin status endpoint
    - Add a derived label helper for the admin status endpoint (`pending`/`expired`/`consumed`/`revoked`/`none`)
    - _Requirements: 2.4, 2.6, 10.1, 11.3, 11.4_
  - [x] 4.3 Write property test for token generation
    - **Property 1: Token generation is well-formed and time-bounded**
    - **Validates: Requirements 2.1, 2.2, 2.3** — ≥100 examples; assert ≥32 bytes entropy, uniqueness, single row, `expires_at == created_at + 7d` (uses async DB fixture)
  - [x] 4.4 Write property test for token-state classification
    - **Property 3: Token state classification is total and distinct**
    - **Validates: Requirements 2.4, 2.6, 10.1, 11.3, 11.4** — ≥100 examples over all (status, expiry, is_active) combos; exactly one distinct outcome, never blank/ambiguous
  - [x] 4.5 Write property test for draft save/load round-trip
    - **Property 19: Draft save/load round-trip with encrypted-at-rest secrets**
    - **Validates: Requirements 12.1, 12.3, 12.5, 12.6** — ≥100 examples over arbitrary partial/empty/submit-invalid payloads; `save_draft` then `load_draft` reproduces every non-sensitive field, stored `draft_data_encrypted` bytes are ciphertext NOT containing IRD/bank plaintext, and decryption reproduces the original payload (async DB fixture)
  - [x] 4.6 Write property test for save-never-consumes
    - **Property 20: Saving a draft never consumes the token**
    - **Validates: Requirements 12.7** — ≥100 examples; for any pending token + partial payload, `save_draft` leaves `status="pending"` and `consumed_at` null and only mutates `draft_data_encrypted`/`draft_updated_at` (async DB fixture)
  - [x] 4.7 Write property test for draft purge
    - **Property 21: Drafts are purged on submit, revoke, and expiry**
    - **Validates: Requirements 12.8, 12.9** — ≥100 examples; after `consume` (submit), `revoke_active` (revoke/resend/deactivation), and on expiry-classified access, both `draft_data_encrypted` and `draft_updated_at` are NULL (async DB fixture)

- [x] 5. Onboarding email delivery
  - [x] 5.1 Create `app/modules/staff/onboarding_delivery.py`
    - `send_onboarding_email(...) -> OnboardingDeliveryResult` mirroring `send_roster_email`/`RosterDeliveryResult`: compose `EmailMessage` with subject `Complete your onboarding — {org_name}`, body greeting with first name, CTA via `render_transactional_html(... cta_url=/onboard/{token}, cta_label=...)`, 7-day-expiry copy
    - Dispatch via `send_email` (multi-provider failover + DLQ); **never raise** on provider failure — return a result object with `success: bool` and an error code
    - Add `send_onboarding_confirmation_email(*, staff_email, staff_first_name, org_name) -> DeliveryResult` (R15): best-effort thank-you to the staff member composed via `render_transactional_html`, including the org name and a friendly thank-you greeting addressed to the staff member (R15.2); wrapped in try/except so any send failure is logged and swallowed (R15.4) — never raises
    - Add `notify_org_onboarding_complete(db, *, org_id, staff) -> None` (R16): (a) create the in-app notification via `create_in_app_notification(db, org_id=..., category="staff_onboarding", severity="success", title=..., body="{first_name} completed their onboarding", audience_roles=["org_admin","branch_admin"], link_url="/staff/{staff_id}", entity_type="staff_member", entity_id=staff.id)`; and (b) resolve recipients by querying the `User` model in `app/modules/auth/models.py` (`users` table) filtered by `org_id == token.org_id` AND `role IN ("org_admin","branch_admin")` AND `is_active IS TRUE`, selecting `email`, deduped by email, and email each one that the staff member completed onboarding with a link to the staff detail page (R16.3); the notification is ORG-scoped only — `StaffMember` has NO scalar `branch_id` column (staff↔branch linkage lives in the `staff_location_assignments` table) and `create_in_app_notification` has no branch parameter, so org-scoping to `token.org_id` satisfies R16.4 and branch-level targeting is out of scope; note `branch_admin` is a real built-in role gated behind the `branch_management` module (orgs without that module have no `branch_admin` users, so only `org_admin` is emailed — correct); every email send wrapped in try/except so a failure is logged and swallowed (R16.6) — never raises
    - Recipient resolution and email composition are extracted as side-effect-free helpers where practical so they are testable with the sender mocked
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 15.1, 15.2, 15.4, 16.1, 16.2, 16.3, 16.4, 16.6_
  - [x] 5.2 Write property test for email composition
    - **Property 5: Onboarding email composition contains the required elements**
    - **Validates: Requirements 3.2, 3.3, 3.4** — ≥100 examples over org name / first name / token; assert subject equality, greeting presence, CTA links to `/onboard/{token}`
  - [x] 5.3 Write property test for confirmation email composition
    - **Property 25: Confirmation email composition contains org name and thank-you**
    - **Validates: Requirements 15.2** — Hypothesis ≥100 examples over org name / staff first name; assert the composed staff confirmation email contains the organisation name and a friendly thank-you greeting addressed to the staff member

- [x] 6. Admin endpoints (authenticated `/api/v2/staff` router)
  - [x] 6.1 Extend `POST /api/v2/staff` (`create_staff` in `app/modules/staff/router.py`)
    - After existing `create_staff` insert+flush: when `send_onboarding_link` is set, gate on non-empty email (`422 onboarding_email_required`, R1.2 belt-and-braces), then `onboarding_tokens.mint(...)`
    - Send via `onboarding_delivery.send_onboarding_email` **after** DB writes; fold result into response (`onboarding_email_sent` / `onboarding_email_error`) — do NOT raise on send failure (preserves record per R3.6); clean return auto-commits staff+token atomically (R3.7)
    - The `send_onboarding_link` flag is independent of the frontend-only 'Also create as a user' invite (which fires a separate `POST /api/v2/org/users/invite` call from `StaffList.tsx`, not a `StaffMemberCreate` field) — both may be active for the same create without special backend handling (R1.5)
    - _Requirements: 1.3, 1.4, 1.5, 3.6, 3.7_
  - [x] 6.2 Add onboarding-link management endpoints to `router.py`
    - `GET /staff/{staff_id}/onboarding-link` → latest token row, returning the lifecycle `state` via `onboarding_lifecycle_label(row, now)`; when `state == "in_progress"`, also return `completion_percentage` (call `load_draft` then `compute_completion_percentage`) and `last_saved_at` (= `draft_updated_at`) (R10.1, R13.1, R13.2, R13.5)
    - `POST /staff/{staff_id}/onboarding-link/resend` → `revoke_active` (purges the prior draft) + `mint` + send; `422 onboarding_email_required` when no email; fold email result into response (R10.2, R12.9)
    - `POST /staff/{staff_id}/onboarding-link/revoke` → `revoke_active` (purges the draft in the same write), idempotent no-op when none active (R10.3, R12.9)
    - All admin error responses use the humanized `{message, code}` shape via `humanize_onboarding_error` (no raw DB/exception text) (R14.2, R14.3, R14.5)
    - All module-gated (`_require_staff_management_module`), org-scoped, audit-logged
    - _Requirements: 10.1, 10.2, 10.3, 12.9, 13.1, 13.2, 13.5, 14.2, 14.3, 14.5_
  - [x] 6.3 Auto-revoke active tokens on deactivate/terminate
    - Add `_revoke_active_onboarding_tokens(...)` sibling to the existing `_revoke_active_roster_tokens` call in `deactivate_staff` (same transaction as `is_active=False`), emitting a single `onboarding.tokens_revoked` audit row when count > 0; it delegates to `revoke_active`, which NULLs the draft columns in the same UPDATE (purges draft on auto-revoke, R12.9)
    - Add the same call to the termination path in `update_staff` (the `is_termination_event` branch)
    - _Requirements: 10.4, 12.9_
  - [x] 6.4 Write property test for onboarding-email destination gate
    - **Property 6: Onboarding email requires a destination address**
    - **Validates: Requirements 1.2** — ≥100 examples incl. whitespace-only emails; accepted only with non-empty email, otherwise no token minted
  - [x] 6.5 Write property test for revocation across revoke/resend/deactivate
    - **Property 4: Revocation invalidates all active links for a staff member**
    - **Validates: Requirements 10.2, 10.3, 10.4** — ≥100 examples; all pending tokens → revoked; resend yields exactly one new pending token (async DB fixture)

- [x] 7. Checkpoint — backend service + admin layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Public onboarding endpoints (`/api/v2/public/staff-onboarding/{token}`)
  - [x] 8.1 Implement prefill `GET /{token}` in `app/modules/staff/public_router.py`
    - Resolve via `onboarding_tokens.resolve` + `classify_token_state`; return distinct `404 onboarding_token_not_found` / `410 onboarding_token_{revoked,consumed,expired,staff_inactive}` per state, each wrapped in the humanized `{message, code}` shape via `humanize_onboarding_error` (R11.4, R14.1)
    - On valid: `200` returning ONLY `first_name`, `email`, `org_name`, static option lists, and `bank_account_required` from org config — no other identity PII (R11.6)
    - Also return the saved **draft** for resume when present (else `draft: null`): non-sensitive fields in full; IRD and bank **masked** via `mask_ird` / `mask_bank_account` with `has_ird` / `has_bank` booleans (never plaintext, R11.6); `documents_staged_count`; plus top-level `completion_percentage` (from `compute_completion_percentage`) and `last_saved_at` (= `draft_updated_at`) (R12.3)
    - Decrypt the draft server-side via `load_draft` (`envelope_decrypt_str`); still expose only `first_name`/`email` of the staff identity (R11.6)
    - _Requirements: 4.2, 11.3, 11.4, 11.6, 12.3, 12.4, 14.1_
  - [x] 8.2 Implement submit `POST /{token}` (multipart) in `public_router.py`
    - Re-validate token (must be pending/unexpired/staff-active) first
    - **Set RLS org context BEFORE any field validation/writes:** immediately after token re-validation, call `await _set_rls_org_id(db, str(token.org_id))` (from `app/core/database.py`) to scope every subsequent write to the token's org. The `org_id` comes from the trusted server-side token row, **never** the client. The public request arrives with no `app.current_org_id` (no JWT/middleware scoping), so this is required to write the RLS-protected `staff_members`/`compliance_documents` tables correctly; the binding is transaction-local (`is_local=true`) so it resets automatically when the transaction ends (no cross-request leakage), and it keeps these writes correct now and after the planned FORCE-RLS cutover (per design.md Security → "RLS on the public write path")
    - Then collect ALL field errors via the `onboarding_validation` validators → `422 {ok:false, errors:{field:{message,code}}, message}` with a top-level human `message` plus per-field `{message, code}` entries (R9.1, R9.2, R14.1); IRD mod-11 failure is a non-blocking `warnings.ird_number`; a missing/past/current-dated visa date for a visa residency type is a **blocking** `errors.visa_expiry_date` (code `visa_expiry_invalid`) that rejects submission (R8.3)
    - Encrypt IRD/bank via `envelope_encrypt` wrapped in try/except → on failure `422 {ok:false, errors:{_global:{message,code:"encryption_failed"}}, message}` (humanized via `humanize_onboarding_error`) and raise so `session.begin()` rolls back (no plaintext/partial write, token stays pending with draft intact, R9.7)
    - Write provided fields into existing `staff_members` columns (last_name, phone, emergency_*, tax_code, student_loan, kiwisaver_*, residency_type, visa_expiry_date, encrypted IRD/bank); never mutate `first_name`/`email`; omit untouched optional columns (R5.3, 6.5, 11)
    - Store ≤3 docs via `ComplianceService.upload_document_with_file` with `{document_type:"working_rights", staff_id}` (enforce PDF/JPEG/PNG allow-list + count before delegating)
    - **Inside the submit transaction** (before/at token consume): call `create_in_app_notification(...)` for the `org_admin`/`branch_admin` audience (`audience_roles=["org_admin","branch_admin"]` — matched against the viewer's JWT role by the inbox visibility filter), org-scoped to `token.org_id`, `entity_type="staff_member"`, `entity_id=staff.id`, `link_url="/staff/{staff_id}"` (the existing staff-detail route, navigable from the inbox `InboxItemCard`) — it never raises and commits atomically with the submit (R16.1, R16.2, R16.4)
    - Mark token consumed ONLY on full success via `consume`, which also NULLs the draft columns in the same transaction (purge draft on submit, R12.8); clean return auto-commits (R2.5, 9.6); return `200` confirmation message (R9.5)
    - **Write an `onboarding.completed` audit row in the same transaction** via `write_audit_log(session=db, org_id=token.org_id, action="onboarding.completed", entity_type="staff_member", entity_id=staff.id, ip_address=<request IP>, after_value={...non-sensitive summary...})` — never include plaintext IRD/bank values (R9.9); mirrors the existing `onboarding.link_resent` / `onboarding.link_revoked` / `onboarding.tokens_revoked` audit pattern in `router.py`
    - **After the transaction commits** (best-effort, must not affect submit outcome): dispatch the staff `send_onboarding_confirmation_email` (R15) and the `notify_org_onboarding_complete(db, org_id=token.org_id, staff=staff)` org_admin/branch_admin emails (R16.3), each wrapped in try/except so failures are logged and swallowed and never roll back or block the submission (R15.4, R16.6); these fire ONLY on a successful submit, never on a draft save (R15.1, R15.3)
    - All error responses use the humanized `{message, code}` shape with no raw DB/exception text; unexpected exceptions caught at the handler boundary return `{message, code:"server_error"}` (R14.1, R14.5)
    - _Requirements: 4.1, 4.3, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 7.6, 8.2, 8.3, 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.9, 11.3, 11.4, 12.8, 14.1, 14.5, 15.1, 15.3, 15.4, 16.1, 16.2, 16.3, 16.4, 16.6_
  - [x] 8.3 Implement save/update draft `PUT /{token}/draft` (JSON) in `public_router.py`
    - Re-validate the token (must be pending/unexpired/staff-active) via `resolve` + `classify_token_state`; token-state rejections reuse the humanized `{message, code}` mapping (R14.1)
    - **Set RLS org context BEFORE the write:** call `await _set_rls_org_id(db, str(token.org_id))` (org_id from the trusted server-side token row) so the draft write is correctly org-scoped for the unauthenticated caller
    - Accept partial/optional data (`OnboardingDraftRequest`, incl. `documents_staged_count`) with only basic shape/size guards (e.g. friendly `{message, code:"draft_too_large"}`) — **NO submit-time field validation** (R12.5)
    - Persist via `save_draft` (whole-blob `envelope_encrypt(json)` → `draft_data_encrypted`, set `draft_updated_at=now()`) (R12.6); **never consume the token** — `status` stays `pending` (R12.7)
    - **No completion side-effects on draft:** the draft endpoint does NOT send the staff confirmation email and does NOT create any org completion notification (in-app or email) — drafts never trigger completion side-effects (R15.5, R16.5)
    - Return `200 {ok:true, completion_percentage, last_saved_at}` (percentage from `compute_completion_percentage`)
    - Inherits the existing `/api/v2/public/staff-onboarding/` 30/min rate-limit prefix + HTTPS — no extra constant needed (R12.10)
    - _Requirements: 12.1, 12.2, 12.5, 12.6, 12.7, 12.10, 14.1, 15.5, 16.5_
  - [x] 8.4 Write property test for single-use consumption
    - **Property 2: Tokens are single-use and consumed only by successful submission**
    - **Validates: Requirements 2.5, 9.6** — ≥100 examples; consumed exactly once on success, subsequent use rejected, no expiry/revoke/deactivation path sets `consumed`
  - [x] 8.5 Write property test for optional-field omission
    - **Property 11: Optional fields may be omitted**
    - **Validates: Requirements 5.3, 6.5, 7.5** — ≥100 examples; omitting bank/IRD/tax/docs leaves prior column values unchanged
  - [x] 8.6 Write property test for configured-required bank account
    - **Property 12: Bank account becomes mandatory when configured required**
    - **Validates: Requirements 5.4** — ≥100 examples; empty rejected, format-valid accepted when org requires it
  - [x] 8.7 Write property test for visa-expiry blocking
    - **Property 13: Visa types require a valid future expiry date (blocking)**
    - **Validates: Requirements 8.3** — ≥100 examples; for work/student visa types a missing/past/current-dated value is rejected with a blocking `errors.visa_expiry_date` (code `visa_expiry_invalid`), a strictly-future date is accepted, and non-visa residency types are always accepted regardless of the date
  - [x] 8.8 Write property test for persistence + identity preservation
    - **Property 14: Successful submission persists provided data and preserves identity fields**
    - **Validates: Requirements 4.2, 9.3** — ≥100 examples; mutable fields equal submitted values (IRD/bank via decryption), `first_name`/`email` unchanged
  - [x] 8.9 Write property test for IRD/bank encryption round-trip
    - **Property 15: IRD and bank account encryption round-trip**
    - **Validates: Requirements 9.4** — ≥100 examples; stored bytes ≠ plaintext and `envelope_decrypt_str` reproduces original
  - [x] 8.10 Write property test for no-partial-write on rejection
    - **Property 16: Rejected submissions never partially write**
    - **Validates: Requirements 9.2, 9.7** — ≥100 examples; validation failure and encryption failure (patch `envelope_encrypt` to raise) leave columns unchanged and token pending
  - [x] 8.11 Write property test for document storage + linkage
    - **Property 17: Working-rights documents are stored and linked**
    - **Validates: Requirements 7.6** — ≥100 examples (≤3 valid docs); each persisted with `staff_id`, correct `org_id`, working-rights type, and retrievable
  - [x] 8.12 Write property test for minimal prefill exposure
    - **Property 18: Public prefill exposes only first name and email**
    - **Validates: Requirements 11.6** — ≥100 examples over fully populated staff records; response keys never include IRD/bank/phone/position/other PII (sensitive draft fields returned masked only)
  - [x] 8.13 Write property test for completion side-effects on submit vs draft
    - **Property 26: Successful submit fires the completion side-effects; a draft save fires none**
    - **Validates: Requirements 15.1, 15.5, 16.1, 16.2, 16.3, 16.4, 16.5** — Hypothesis ≥100 examples (sender/notifier mocked; async DB fixture); a successful submit produces **exactly one** correctly-targeted, org-scoped in-app notification (audience `["org_admin","branch_admin"]`, `entity_type="staff_member"`, `entity_id=staff.id`, link to the staff detail page), attempts exactly one staff confirmation email, and emails each distinct active `org_admin`/`branch_admin` user of that org deduped by email (never another org's users); a draft save fires **none** of these
  - [x] 8.14 Write property test for completion side-effect failure isolation
    - **Property 27: Completion side-effect failures never roll back or block a submission**
    - **Validates: Requirements 15.4, 16.6** — ≥100 examples; patch `create_in_app_notification` and the completion email sender to raise, then assert the submit still succeeds — staff fields persisted, token marked `consumed`, draft purged, and the on-screen confirmation still returned (async DB fixture)

- [x] 9. Rate limiting for public onboarding
  - [x] 9.1 Add onboarding rate-limit prefix to `app/middleware/rate_limit.py`
    - Add `_PUBLIC_STAFF_ONBOARDING_PATH_PREFIX = "/api/v2/public/staff-onboarding/"` and `_PUBLIC_STAFF_ONBOARDING_RATE_LIMIT = 30`, mirroring the existing `_PUBLIC_STAFF_ROSTER_*` block verbatim (per-IP sliding window, `429` + `Retry-After`)
    - The same prefix already covers the new `PUT .../{token}/draft` endpoint — no extra constant required (R12.10)
    - _Requirements: 11.2, 12.10_
  - [x] 9.2 Write integration test for rate-limit 429
    - Drive >30 requests/min against a public onboarding endpoint; assert `429` + `Retry-After` (example/integration, not PBT)
    - _Requirements: 11.2_

- [x] 10. Frontend (frontend-v2)
  - Note: No new frontend work is required for R15/R16 — R16's in-app surface reuses the existing in-app notification inbox UI already present in frontend-v2 (`InboxPage` at `/notifications/inbox`, `InboxItemCard`, and the TopBar bell unread-count badge), so no new notifications component is needed.
  - [x] 10.1 Add "Send onboarding link" checkbox + email blocking to `frontend-v2/src/pages/staff/StaffList.tsx`
    - `sendOnboardingLink` state alongside `createAsUser`; sibling checkbox reusing existing markup/classes. There is **no** `resetForm()` helper in `StaffList.tsx` — modal state is reset inline inside `openAdd()`, so add `setSendOnboardingLink(false)` inside `openAdd()` alongside the existing `setCreateAsUser(false)` line
    - Block `handleSave` with inline validation when checked and email empty (R1.2); include `send_onboarding_link` in create payload
    - Capture the create response — `const res = await apiClient.post('/staff', payload, { baseURL: '/api/v2' })` — and, on success with the flag set, surface `formError` when `res.data?.onboarding_email_sent` is false, following the existing invite-failure handling pattern (`setSaving(false); fetchStaff(); return`)
    - _Requirements: 1.1, 1.2, 1.3, 1.5_
  - [x] 10.2 Add Onboarding-link card to `frontend-v2/src/pages/staff/tabs/OverviewTab.tsx`
    - On mount `GET /staff/{id}/onboarding-link` via the extended `api/staff.ts` status helper; render the lifecycle `state` (`not_started`/`in_progress`/`completed`/`expired`/`revoked`/`none`) with Resend / Revoke / Send buttons; safe consumption (`res.data?.state ?? 'none'`)
    - When `state === "in_progress"`, show a progress bar / `{completion_percentage}%` and a "Last saved {last_saved_at}" line
    - Resend → POST resend (error toast when send fails); Revoke → POST revoke then refetch
    - _Requirements: 10.1, 10.2, 10.3, 13.1, 13.2, 13.5_
  - [x] 10.3 Create public page `frontend-v2/src/pages/public/OnboardingFormPage.tsx`
    - Modelled on `StaffRosterPublicView.tsx`. **Transport:** the page MUST use raw `import axios from 'axios'` for BOTH the prefill GET and the multipart submit POST — mirroring `StaffRosterPublicView.tsx` — and MUST NOT use the shared `apiClient` (whose 401 response interceptor calls `window.location.replace('/login')` and which injects a `/api/v1` baseURL plus auth/branch/CSRF headers — all wrong for a logged-out public visitor)
    - On mount `GET /api/v2/public/staff-onboarding/{token}` via raw `axios`, inside a `useEffect` that uses an `AbortController`; error handling mirrors `StaffRosterPublicView` — `axios.isAxiosError(err)`, read `err.response?.status` + `err.response?.data?.detail`, map 404/410 codes to distinct friendly messages (R11.4); render `first_name`/`email` read-only (R4.2)
    - Sectioned cards (Personal, Bank, IRD & Tax, Residency, Documents); KiwiSaver rate shown only when enrolled AND no other validation errors are present (R6.4); visa expiry field only for work/student visa, where a missing/past/current-dated value shows a blocking error that prevents submission until a valid future date is entered (R8.2, R8.3); document picker accept `application/pdf,image/jpeg,image/png`, max 3, name+remove, client reject >10 MB (R7.4)
    - Submit via raw `axios` POST; the body MUST be a `FormData` object (append fields + up to 3 files) and let axios set the `multipart/form-data` Content-Type/boundary automatically (no hardcoded `application/json`); map `422 errors` to inline messages without clearing inputs (R9.2); swap to thank-you confirmation on `200` (R9.5); mirror server validators client-side (server authoritative)
    - Add a "Save as draft" button and debounced (~800ms) autosave-on-blur — both issue `PUT /api/v2/public/staff-onboarding/{token}/draft` via raw `axios` (never `apiClient`), sending the partial fields plus `documents_staged_count` (R12.1, R12.2); show a subtle "Saved {time}" indicator from the response `last_saved_at`; draft-save errors surface the server `message` quietly (non-blocking). Draft saves are NOT subject to submit-time client validation (R12.5)
    - On resume, repopulate from the prefill `draft`: non-sensitive fields directly, and treat masked IRD/bank via the existing `isMaskedIrd` / `isMaskedBank` heuristic so a field left showing the masked placeholder is NOT re-sent unless the user retypes it (R12.3)
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 6.1, 6.4, 7.1, 7.4, 8.1, 8.2, 8.3, 9.2, 9.5, 11.3, 11.4, 12.1, 12.2, 12.3, 12.5_
  - [x] 10.4 Register `/onboard/:token` route in `frontend-v2/src/App.tsx`
    - Add `<Route path="/onboard/:token" element={<OnboardingFormPage />} />` outside `RequireAuth`/`GuestOnly`, next to existing public token routes
    - _Requirements: 11.1_
  - [x] 10.5 Add API client functions
    - **Authenticated helpers** (get onboarding-link status / resend / revoke) go in `frontend-v2/src/api/staff.ts`, using the shared `apiClient` with absolute `/api/v2/staff/...` paths, typed generics (never `as any`), defensive consumption (`res.data?.x ?? default`), and an optional `AbortSignal` parameter — matching that module's existing conventions
    - Extend the status helper return type to carry `state`, `completion_percentage`, and `last_saved_at` (consumed by the OverviewTab card in task 10.2)
    - **Public transport** (the prefill GET + multipart submit POST + the `PUT .../draft` autosave) uses raw `axios` per task 10.3 — either inlined in `OnboardingFormPage` or in a separate raw-axios public helper — and is intentionally **NOT** added to `api/staff.ts`
    - Note: Task 10.2's OverviewTab card consumes the `api/staff.ts` helpers rather than calling `apiClient` inline
    - _Requirements: 10.1, 10.2, 10.3, 11.6_
  - [x] 10.6 Write frontend unit tests
    - StaffList checkbox + email-blocking; OverviewTab resend/revoke/status rendering plus lifecycle-state + completion-percentage card rendering (in_progress shows progress bar/`%` + last-saved); OnboardingFormPage conditional KiwiSaver-rate and visa-expiry visibility, document picker limits, inline-error mapping, save-as-draft button firing a `PUT`, debounced autosave-on-blur firing a `PUT`, and masked-resume (masked IRD/bank not re-sent unless retyped) (Vitest + RTL; fast-check for client validator parity)
    - _Requirements: 1.1, 1.2, 6.4, 8.2, 8.3, 9.2, 10.1, 12.1, 12.2, 12.3, 13.1, 13.2, 13.5_

- [x] 11. Checkpoint — full stack wired
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Integration tests and final verification
  - [x] 12.1 Write public no-auth reachability integration test
    - Assert `/api/v2/public/staff-onboarding/{token}` is reachable without a JWT (covered by `PUBLIC_PREFIXES`) and returns the correct token-state status codes
    - _Requirements: 11.1, 11.3, 11.4_
  - [x] 12.2 Write humanized-error-shape integration test
    - Drive every error path (token-state rejections, validation failure, encryption failure, email-send failure, server error) across the public and admin onboarding endpoints; assert each error response carries a non-empty human-readable `message` plus a machine `code` and contains no raw DB/exception text (example/integration, not PBT)
    - _Requirements: 14.1, 14.2, 14.5_
  - [x] 12.3 Write completion side-effects integration test
    - Assert a successful submit returns the `200` thank-you AND attempts the staff confirmation email (R15.3); plus an integration test for the actual multi-provider dispatch of both completion emails — the staff confirmation email and the org_admin/branch_admin notification emails (email provider dispatch is integration, not PBT)
    - Assert a successful submit writes exactly one `onboarding.completed` audit_log row (org-scoped, `entity_type="staff_member"`, `entity_id=staff.id`, submitter IP captured) and that the row contains no plaintext IRD/bank values (R9.9)
    - _Requirements: 9.9, 15.3, 16.3_
  - [x] 12.4 Final verification
    - Run backend test suite (pytest incl. Hypothesis property tests, ≥100 examples) and frontend checks (`tsc --noEmit`, `vitest --run`); run `alembic upgrade head` to confirm `0223` applies cleanly; run `get_diagnostics` on the spec files and fix any reported issues
    - _Requirements: all_

- [x] 13. Version bump and changelog
  - [x] 13.1 Bump version and add CHANGELOG entry (MINOR feature)
    - Per the **versioning-and-changelog** steering, this is a new feature → MINOR bump (x.Y.0)
    - Bump the backend version in `app/__init__.py` (`__version__`) and the frontend-v2 version in `frontend-v2/package.json` (`version`); verify these are the canonical version files for the active app (backend runtime version lives in `app/__init__.py`; `frontend-v2/` is the active SPA per project-overview — reconcile with `pyproject.toml` if the versions have drifted)
    - Add a new `CHANGELOG.md` entry at the top (newest-first) under `### Added` describing the staff onboarding link feature (admin "Send onboarding link" checkbox, secure token-gated public `/onboard/:token` self-service form, resend/revoke + auto-revoke on deactivation)
    - _Requirements: all_

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific granular requirements for traceability; property-test sub-tasks additionally cite the design property they validate.
- All 27 correctness properties are implemented as Hypothesis property tests (≥100 iterations each, tagged with the property number), placed close to the implementation they validate to catch errors early.
- Pure validators, token-state classification, email composition, completion-percentage, lifecycle-label, and humanized-error mapping are extracted as side-effect-free functions so they can be property-tested without a DB; DB-touching properties (incl. draft save/load round-trip, save-never-consumes, draft purge, and the completion side-effects on submit vs draft) use the existing async DB session fixtures, and encryption-failure injection patches `app.core.encryption.envelope_encrypt`.
- Completion side-effects on a successful submit: the org in-app notification is created **in-transaction** (commits atomically with the submit and never raises), while the staff confirmation email (R15) and the org_admin/branch_admin notification emails (R16.3) are **best-effort, dispatched after commit** and wrapped so failures are logged and swallowed; none of these fire on a draft save (R15.5, R16.5).
- Checkpoints provide incremental validation at the service/admin boundary and after full-stack wiring.
- This workflow produces planning artifacts only; implementation is performed when executing the tasks.

- [x] 14. Post-ship deltas — spec decisions made after the initial build
  These three changes were added to the spec after the feature first shipped and have now been implemented and verified (backend property + integration tests, frontend unit tests, `tsc`).
  - [x] 14.1 Visa expiry blocks submission (R8.2, R8.3)
    - Renamed `visa_expiry_warning` → `validate_visa_expiry` in `app/modules/staff/onboarding_validation.py` (valid iff non-visa type, or visa type with a strictly-future date)
    - `public_router.py` submit handler now adds a **blocking** `errors.visa_expiry_date` (code `visa_expiry_invalid`) instead of a warning
    - `frontend-v2/src/pages/public/OnboardingFormPage.tsx` `validateForSubmit()` blocks on a missing/past/current-dated visa date and renders an inline `FieldError`; removed the old amber non-blocking warning
    - Rewrote Property 13 (`tests/properties/test_staff_onboarding_visa_expiry_properties.py`) and the frontend visa test for the blocking semantics
    - _Requirements: 8.2, 8.3_
  - [x] 14.2 Completion audit entry (R9.9)
    - `public_router.py` submit handler writes an in-transaction `onboarding.completed` `write_audit_log` row (org-scoped, `entity_type="staff_member"`, submitter IP via `request.client`, non-sensitive `after_value` summary — no plaintext IRD/bank)
    - Added a Part-3 audit assertion to `tests/test_onboarding_completion_sideeffects_integration.py`
    - _Requirements: 9.9_
  - [x] 14.3 KiwiSaver rate hidden while validation errors present (R6.4)
    - `OnboardingFormPage.tsx` gates the rate field on `kiwisaver_enrolled && Object.keys(fieldErrors).length === 0`
    - _Requirements: 6.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "3.3"] },
    { "id": 2, "tasks": ["3.2", "4.1"] },
    { "id": 3, "tasks": ["4.2", "5.1", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"] },
    { "id": 4, "tasks": ["6.1", "4.3", "4.4", "4.5", "4.6", "4.7", "5.2", "5.3"] },
    { "id": 5, "tasks": ["6.2"] },
    { "id": 6, "tasks": ["6.3", "6.4", "6.5"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2"] },
    { "id": 9, "tasks": ["8.3"] },
    { "id": 10, "tasks": ["9.1", "10.1", "10.2", "10.3", "10.4", "10.5"] },
    { "id": 11, "tasks": ["8.4", "8.5", "8.6", "8.7", "8.8", "8.9", "8.10", "8.11", "8.12", "8.13", "8.14", "9.2", "10.6"] },
    { "id": 12, "tasks": ["12.1", "12.2", "12.3"] },
    { "id": 13, "tasks": ["12.4"] },
    { "id": 14, "tasks": ["13.1"] },
    { "id": 15, "tasks": ["14.1", "14.2", "14.3"] }
  ]
}
```
