# Implementation Plan: E-Signature Integration

## Overview


This plan implements the `esignatures` module incrementally, foundation-first. It begins with the database migration (four org-scoped tables under RLS, including the per-organisation `esign_org_connections` connection record), ORM models, and the pure logic cores (status reducer, validators, constant-time secret-equality compare) that anchor most of the 27 correctness properties. It then adds the Documenso REST API v2 client and the **per-organisation** credential loader (each organisation calls its own Documenso Team with its own team-scoped token), service orchestration (send / void / list / detail) including signature-field placement and a connection gate on send, the per-org-routed shared-secret-authenticated webhook handler, signed-document retrieval with a scheduled retry sweep, the per-organisation Documenso connection management surface and per-org webhook-subscription provisioning, and finally the frontend-v2 surfaces (Agreements dashboard, send modal, contextual actions) plus the Global-Admin per-org connection settings surface. Each implementation step is immediately followed by its property and example tests so regressions surface early, and each terminal step wires the new code into routers, middleware, schedulers, and the sidebar so there is no orphaned code.

Backend is Python 3.11 / FastAPI / SQLAlchemy (async) / Alembic. Frontend is React 18 + TypeScript + Vite + Tailwind in `frontend-v2/`. Property-based tests use Hypothesis (min 100 examples each), tagged `# Feature: esignature-integration, Property {n}: {property_text}`. Mobile is out of scope.

## Tasks

- [x] 1. Database migrations: tables, RLS, seeds, and performance indexes
  - [x] 1.1 Migration A (rev `0232`): tables, CHECK constraints, RLS, inline indexes, and seeds
    - Create a new Alembic revision under `alembic/versions/` parented on current head `0231`, revision id `0232` (short id per ISSUE-029 width limit), an ordinary transactional migration, idempotent throughout. (Revisions `0226`–`0231` are already used by shipped specs; `0232`/`0233` are the next free ids — re-confirm `alembic heads` before authoring in case the head has advanced.)
    - `CREATE TABLE IF NOT EXISTS esign_envelopes` with columns per design (`id`, `org_id`, `agreement_type`, `originating_entity_type`, `originating_entity_id`, `documenso_document_id`, `status`, `signed_doc_status`, `signed_doc_file_key`, `last_error`, `created_at`, `updated_at`, `created_by`); add CHECK constraints (`agreement_type` ∈ 5 types, `originating_entity_type` ∈ invoice/quote/staff, `status` ∈ 8 statuses, `signed_doc_status` ∈ none/pending_retrieval/stored) via `DROP CONSTRAINT IF EXISTS` then `ADD CONSTRAINT`.
    - `CREATE TABLE IF NOT EXISTS esign_recipients` (cascade FK to `esign_envelopes`, `recipient_status` default `pending`, `signing_url` nullable, `signing_role` stored as the UPPERCASE Documenso role) and `esign_webhook_events` (with `dedupe_key TEXT NOT NULL UNIQUE` — the synthesized idempotency key, since the Documenso payload carries no native event id).
    - `CREATE TABLE IF NOT EXISTS esign_org_connections` — the per-organisation Documenso connection record — with columns `id`, `org_id` (UNIQUE — one connection per org), `base_url`, `documenso_team_id`, `service_token_encrypted BYTEA`, `webhook_secret_encrypted BYTEA`, `webhook_routing_id TEXT NOT NULL UNIQUE` (opaque per-org routing identifier embedded in the registered Documenso callback URL), `is_verified BOOL NOT NULL DEFAULT false`, `created_at`, `updated_at`, `created_by`. Declare the `UNIQUE(org_id)` and `UNIQUE(webhook_routing_id)` constraints **inline** in the `CREATE TABLE` body (or via `CREATE UNIQUE INDEX IF NOT EXISTS` in the same statement set); do **NOT** use `op.create_index(...)`.
    - Create only the indexes intrinsic to table creation **inline at `CREATE TABLE` time** on the empty tables — PK indexes, the `esign_recipients` → `esign_envelopes` FK index, the `esign_webhook_events` `UNIQUE(dedupe_key)` constraint, and the `esign_org_connections` `UNIQUE(org_id)` + `UNIQUE(webhook_routing_id)` constraints (declared in the `CREATE TABLE` body or via `CREATE UNIQUE INDEX IF NOT EXISTS` in the same statement set). Do **NOT** use `op.create_index(...)` and do **NOT** add any performance index here (those move to Migration B).
    - Enable RLS + `tenant_isolation` policies on all **four** tables using `current_setting('app.current_org_id', true)::uuid` (recipients scoped through parent envelope; `esign_org_connections` scoped directly by `org_id`), with `WITH CHECK` where applicable.
    - Seed the `module_registry` row for `esignatures` ('Agreements', category `documents`, `is_core=false`, no trade-family gating) **including `setup_question` and `setup_question_description`** (setup-guide columns) via `INSERT ... ON CONFLICT (slug) DO NOTHING` — this seed is **mandatory** (it drives per-org enablement and the sidebar).
    - **Optionally** seed a `feature_flags` catalogue/visibility row keyed `key='esignatures'` (the table is keyed by **`key`**, NOT `slug`) via `INSERT ... ON CONFLICT DO NOTHING`. This row is **catalogue/visibility only** (so the capability is visible to Global Admin); it is **NOT** the runtime gate and MUST NOT be added to `FLAG_ENDPOINT_MAP`. `ModuleService.is_enabled` does not consult `feature_flags`. The runtime gate is the module only (see Task 7.3).
    - Implement `downgrade()` to drop the `tenant_isolation` policies, disable RLS, drop all **four** tables (including `esign_org_connections`), and remove the **mandatory** `module_registry` seed; remove the `feature_flags` row **only if it was seeded**.
    - _Requirements: 1.1, 1.2, 2.1, 2.5, 3.2, 3.6, 6.1, 8.3, 8.4, 13.1, 13.2, 13.7_

  - [x] 1.2 Migration B (rev `0233`): performance indexes via `CREATE INDEX CONCURRENTLY`
    - Create a **separate** Alembic revision file `0233` parented on `0232`, following the canonical `0202_add_perf_indexes.py` template — all DDL inside `op.get_context().autocommit_block()` (mixing `CONCURRENTLY` with other DDL in one `upgrade()` is a banned pattern).
    - `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_esign_envelopes_org_updated ON esign_envelopes (org_id, updated_at DESC)` (dashboard ordering).
    - `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_esign_envelopes_documenso_doc ON esign_envelopes (documenso_document_id) WHERE documenso_document_id IS NOT NULL` (partial, webhook lookup).
    - `downgrade()` issues `DROP INDEX CONCURRENTLY IF EXISTS` for each index, also inside an `autocommit_block()`; the `IF NOT EXISTS`/`IF EXISTS` guards keep a partial-build INVALID index safely re-runnable.
    - _Requirements: 11.4, 8.5, 13.1_

  - [x] 1.3 Post-migration verification (run inside the app container)
    - Run `alembic upgrade head` inside the running dev app container (`docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head`) and confirm both revisions apply.
    - Verify the `agreement_type`, `originating_entity_type`, `status`, and `signed_doc_status` CHECK constraints accept their defined enum values (insert-and-rollback probes or `pg_constraint` inspection) so a `CheckViolationError` cannot surface at runtime.
    - _Requirements: 3.6, 6.1, 8.3, 8.4_

  - [x] 1.4 Migration and RLS isolation tests
    - Assert both migrations apply, revert, and are idempotent on re-run against a copy of head `0231`; assert the `esignatures` `module_registry` row is seeded (R2.1 smoke). If the optional `feature_flags` catalogue row is seeded, assert it is keyed `key='esignatures'` and is removed on downgrade.
    - RLS smoke: with `app.current_org_id` = org A, confirm org B's `esign_envelopes` / `esign_recipients` / `esign_webhook_events` / `esign_org_connections` rows are invisible.
    - _Requirements: 2.1, 13.2, 13.7_

- [x] 2. ORM models and Pydantic schemas
  - [x] 2.1 Create `app/modules/esignatures/models.py`
    - Define `EsignEnvelope`, `EsignRecipient` (with nullable `signing_url` and `signing_role` stored UPPERCASE), `EsignWebhookEvent` (with `dedupe_key` TEXT NOT NULL UNIQUE — the synthesized idempotency key), and `EsignOrgConnection` (per-organisation connection: `org_id` UNIQUE, `base_url`, `documenso_team_id`, `service_token_encrypted`/`webhook_secret_encrypted` BYTEA, `webhook_routing_id` UNIQUE, `is_verified`, timestamps, `created_by`) mapped to the migration tables.
    - _Requirements: 1.1, 3.2, 4.1, 4.4, 8.3, 13.1, 13.7_

  - [x] 2.2 Create `app/modules/esignatures/schemas.py`
    - Define `RecipientIn` (name, `EmailStr`, signing_role), `EnvelopeCreate` (agreement_type Literal of 5 types, originating_entity_type/id, `recipients` min_length=1), `RecipientOut`, `EnvelopeOut` (with nullable `signed_document_url`), `EnvelopeListResponse` (`{ items, total }`), and `EsignError` (`message` + optional `code`).
    - `signing_role` is persisted as the UPPERCASE Documenso role (`SIGNER`/`VIEWER`); the API accepts lowercase (`signer`/`viewer`) and maps to uppercase when calling Documenso.
    - Ensure no schema carries plaintext credentials or signed-document bytes.
    - _Requirements: 3.3, 3.6, 11.5, 14.4, 15.3, 16.1, 16.2_

- [x] 3. Pure status reducer (`status.py`)
  - [x] 3.1 Implement `next_status(current, event, recipients_state) -> EnvelopeStatus | None`
    - Encode the lifecycle by mapping the REAL Documenso event names: `DOCUMENT_OPENED`/`DOCUMENT_VIEWED` → `viewed`; `DOCUMENT_RECIPIENT_COMPLETED` with ≥1 recipient still unsigned → `partially_signed`; `DOCUMENT_COMPLETED` → `completed` (including all-at-once and single-recipient cases); `DOCUMENT_RECIPIENT_REJECTED` → `declined`; `DOCUMENT_CANCELLED` (from a non-terminal envelope) → `voided`.
    - The signed/unsigned state is read from `recipients_state` (derived from the webhook payload's `recipients[...]` array), not a synthetic boolean.
    - Return `None` (no transition) when `current` is terminal (`completed`/`declined`/`voided`) and the event is non-void. Keep the function pure (no I/O).
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 3.2 Property test — terminal immutability
    - **Property 9: Terminal statuses are immutable under non-void events**
    - **Validates: Requirements 6.1, 6.6**

  - [x] 3.3 Property test — lifecycle transitions from non-terminal states
    - **Property 10: Lifecycle transitions are correct from non-terminal states**
    - Exercise the real Documenso event names (`DOCUMENT_OPENED`/`DOCUMENT_VIEWED` → `viewed`, `DOCUMENT_RECIPIENT_COMPLETED` → `partially_signed`, `DOCUMENT_COMPLETED` → `completed`, `DOCUMENT_RECIPIENT_REJECTED` → `declined`, `DOCUMENT_CANCELLED` → `voided`).
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5**

- [x] 4. Pure validators (`validation.py`)
  - [x] 4.1 Implement `is_pdf(...)`, `validate_recipients(...)`, and secret-compare helper
    - `is_pdf` checks PDF magic bytes; `validate_recipients` enforces ≥1 recipient and syntactic email validity atomically, identifying the first offending recipient; provide a constant-time secret-equality compare wrapper over `hmac.compare_digest` that compares the shared secret **string** verbatim (Documenso sends the secret as-is; it does NOT HMAC the body). All pure, no I/O.
    - _Requirements: 3.3, 3.4, 4.2, 4.3, 4.6, 8.1_

  - [x] 4.2 Property test — atomic, side-effect-free send validation
    - **Property 8: Send validation is atomic and side-effect-free** (pure-core portion: zero recipients / non-PDF / any-invalid-email rejection)
    - **Validates: Requirements 3.3, 3.4, 4.2, 4.3, 4.6**

- [x] 5. DocumensoClient and per-organisation connection loader (`app/integrations/documenso.py`)
  - [x] 5.1 Implement the per-org connection loader and exception types
    - Replace any global `get_documenso_base_url()/get_documenso_service_token()/get_documenso_webhook_secret()` helpers with a single per-organisation loader `get_documenso_connection(db, org_id) -> DocumensoConnection`: load that organisation's `esign_org_connections` row (org-scoped under RLS), decrypt `service_token_encrypted`/`webhook_secret_encrypted` at call time via `envelope_decrypt_str`, and return a `DocumensoConnection` value object carrying `base_url`, `documenso_team_id`, the raw team-scoped token, the webhook secret, `webhook_routing_id`, and `is_verified`. Optional short-TTL in-memory cache keyed **by `org_id`** (`_CACHE_TTL = 300`, invalidated when the org's connection is saved). Raise `DocumensoNotConfiguredError` when the organisation has no connection row. Never read these values from `.env` for API calls; never log token or webhook secret. Define `DocumensoError`, `DocumensoNotConfiguredError`, `DocumensoApiError(status=...)`.
    - _Requirements: 1.3, 1.9, 13.7, 15.1_

  - [x] 5.2 Implement `DocumensoClient` over async httpx (Documenso REST API **v2**), instantiated per organisation
    - Construct the client **per organisation** via `DocumensoClient.for_org(conn, http)` using that organisation's `DocumensoConnection`: the org's `base_url`, its raw team-scoped token, and `documenso_team_id` scoping. Every request issued by that instance carries **that organisation's own token** in the `Authorization: <raw_token>` header (the raw API token, **NO `Bearer` prefix**) and is scoped to that org's `documenso_team_id` (R13.7). All requests over HTTPS; reject a non-HTTPS configured base URL. Never log token or webhook secret.
    - Methods reflect the real multi-step flow:
      - `create_document(...)` → returns `{uploadUrl, documentId, recipients[]}` where each recipient carries a `token` and a `signingUrl`; recipient roles map lowercase `signer`/`viewer` → UPPERCASE Documenso `SIGNER`/`VIEWER`.
      - `upload_pdf(upload_url, pdf_bytes)` — uploads the PDF to the returned `uploadUrl`.
      - `place_signature_field(document_id, recipient_id, page_number, page_x, page_y, page_width, page_height)` — `POST /api/v2/documents/{id}/fields`.
      - `send_document(document_id)`.
      - `download_signed(document_id)`.
      - `cancel_document(document_id)` — issues `DOCUMENT_CANCELLED` for void.
      - `test_connection()`.
    - Capture each recipient's `signingUrl` (from `create_document`) onto the corresponding `esign_recipients` row.
    - **Resilience (performance-and-resilience §2/§3):** every call uses an explicit `httpx.Timeout` (never the unbounded default); retry transient failures (`httpx.TimeoutException`, 5xx `HTTPStatusError`) up to 3 attempts with exponential backoff (1s/2s/4s); non-transient failures (4xx, invalid payloads) raise `DocumensoApiError` immediately without retry.
    - **Managed client lifecycle:** the `httpx.AsyncClient` is created per call via `async with ... as client:` (or injected and closed by the caller) — never instantiated per request and left unclosed (no leaked connection pools). The per-org `for_org` construction holds only the org's connection data, not a long-lived global singleton.
    - _Requirements: 1.6, 7.2, 9.1, 9.5, 13.7, 15.4_

  - [x] 5.3 Property test — unconfigured integration fails every operation
    - **Property 4: Unconfigured integration fails every operation with a message** (including connection test)
    - **Validates: Requirements 1.9, 1.10**

  - [x] 5.4 Property test — HTTPS for all Documenso traffic
    - **Property 23: HTTPS for all Documenso traffic** (every Documenso v2 call uses an HTTPS base URL with the raw-token `Authorization` header)
    - **Validates: Requirements 15.4**

  - [x] 5.5 Property test — Documenso calls always use the calling org's own team-scoped token
    - **Property 26: Documenso calls always use the calling org's own team-scoped token** — across multiple organisations each with a distinct `base_url`/team-scoped `service_token`/`documenso_team_id`, every Documenso call OraInvoice makes on behalf of a given organisation is issued with that org's own token scoped to its own `documenso_team_id` and never another org's token (assert via a spy/recording client across multiple orgs).
    - **Validates: Requirements 13.7**

  - [x] 5.6 Implement the optional provisioning adapter (`app/integrations/documenso_provisioning.py`)
    - Create `app/integrations/documenso_provisioning.py` (aka `provisioning.py`) defining the `ProvisioningAdapter` Protocol (`create_team`, `mint_team_token`, `ensure_webhook`), the dataclasses `ProvisionedTeam`/`ProvisionedToken`, a humanized `ProvisioningError`, and `get_provisioning_adapter()` selected by the **platform-level** flag `ESIGN_PROVISIONING_MODE = off | trpc | db` (returns `None` when `off`).
    - `TrpcProvisioningAdapter` drives Documenso's **internal admin tRPC** layer (the endpoints its own web UI calls) to create a Team, mint a team API token, and create the Team's webhook subscription, authenticating with a **platform-level** Documenso admin session/credential held by OraInvoice as **envelope-encrypted platform config** (NOT a per-org credential). `DbProvisioningAdapter` writes **directly to Documenso's self-hosted PostgreSQL** via a **platform-config Documenso DB URL**: insert the `Team`, owner `TeamMember`, a **HASHED** API-token row, and a webhook-subscription row — generate the token itself, store only its hash, and return the plaintext **once** so OraInvoice can persist it envelope-encrypted.
    - **Isolation guarantee:** wrap **every** adapter call so any exception (tRPC error, DB error, schema mismatch, version drift) is caught and surfaced as a humanized `ProvisioningError`; an adapter failure **NEVER** corrupts or blocks the manual path. Mark both adapters **best-effort, unsupported, and upgrade-fragile** in code comments. Platform provisioning credentials are envelope-encrypted, are **never** stored on any org's `esign_org_connections` row, and are used **only** for provisioning — never for per-org Documenso API calls (those always use the org's own team-scoped token, R13.7).
    - _Requirements: 20.1, 20.4, 20.5_

- [x] 6. Checkpoint - Ensure all foundation tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Error humanization helper and module gating dependencies
  - [x] 7.1 Implement `humanize_esign_error(exc) -> EsignError` and shared FastAPI dependencies
    - Central mapper to the `{ message, code }` shape per the Error Handling table; never leak raw DB/exception text. Implement `require_esign_sender` as `require_role(ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER)` from `app/modules/auth/rbac.py` (the `manager` role does **not** exist in this codebase) → else 403, and a module-gate dependency that returns 403 when `esignatures` is disabled.
    - **Slug consistency:** the gate dependency MUST call `ModuleService.is_enabled(org_id, "esignatures")` using the slug `esignatures` — the same slug used everywhere (see Task 7.3); do not introduce a split between an endpoint-map value and an `is_enabled`/registry slug.
    - _Requirements: 2.2, 12.1, 12.2, 12.3, 15.5, 16.1, 16.2, 16.3_

  - [x] 7.2 Property test — error responses are human-readable and leak nothing
    - **Property 24: Error responses are human-readable and leak nothing**
    - **Validates: Requirements 15.5, 16.1, 16.2, 16.3**

  - [x] 7.3 Wire the concrete module gate (middleware entry + router dependency)
    - The runtime gate is the **module only**. Add the entry `"/api/v2/esign": "esignatures"` to `MODULE_ENDPOINT_MAP` in `app/middleware/modules.py` (a prefix entry covering all esign endpoints) so `ModuleMiddleware` returns 403 when the module is disabled — without this entry the middleware never inspects esign paths.
    - Because `ModuleMiddleware` fails **open** on internal errors, **also** add a router-level dependency (mirroring the staff module's `_require_staff_management_module`) that calls `ModuleService.is_enabled(org_id, "esignatures")` and raises 403 when disabled. The middleware entry + router dependency give defence-in-depth for R2.2.
    - **Slug consistency:** the slug `esignatures` MUST be identical in all four places — the `MODULE_ENDPOINT_MAP` value (`"/api/v2/esign": "esignatures"`), the `module_registry` seed slug (Task 1.1), the router-level `ModuleService.is_enabled(org_id, "esignatures")` dependency, and the frontend `isEnabled('esignatures')` (Tasks 16.2/18.x) — and MUST NOT replicate the staff module's latent split (endpoint-map value `staff` vs registry/`is_enabled` slug `staff_management`).
    - **Gate status:** the staff router gate returns HTTP 404 `not_enabled`, but this spec deliberately uses **403** for the esign gate — mirror only the dependency PATTERN of `_require_staff_management_module`, not its status code (keep 403).
    - Do **NOT** consult `feature_flags` and do **NOT** add any "enabled if either `org_modules` OR `feature_flags`" logic — `ModuleService.is_enabled` does not query `feature_flags`; `org_modules` is the single source of truth.
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 7.4 Property/example test — module-disabled endpoints return 403 via the module gate
    - Assert requests under `/api/v2/esign` return 403 when the `esignatures` module is disabled, enforced by the `MODULE_ENDPOINT_MAP` entry **and** the router-level `ModuleService.is_enabled` dependency; assert they pass when the module is enabled. Do not assert any `feature_flags`/"either source" behaviour.
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 8. Service: create and send envelope (`service.py`)
  - [x] 8.1 Implement `create_and_send_envelope(...)`
    - Authorize role + module; **step 0 — load the organisation's connection** via `get_documenso_connection(db, org_id)`: if the org has no connection row or `is_verified = false`, **block the send** with a humanized 503 (`integration_not_configured`) and make **NO** Documenso call (R19.3/19.4). Build the org's client with `DocumensoClient.for_org(conn, http)` so the whole flow uses that org's token + `documenso_team_id` (R13.7). Then run pure PDF/recipient validation (no Documenso call on failure); call the multi-step flow `create_document` → `upload_pdf` → `place_signature_field` (per signer recipient) → `send_document`; on success insert `esign_envelopes` (org_id, agreement_type, originating-entity ref, documenso_document_id, status `sent`) + one `esign_recipients` row per recipient (status `pending`, capturing each recipient's `signingUrl`); use `flush()` then `await db.refresh()` before serialising; on Documenso error insert envelope with status `error` and return humanized 502.
    - Set originating entity from the calling surface (invoice/quote id or staff id).
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 4.4, 10.3, 10.4, 12.1, 13.7, 19.3, 19.4_

  - [x] 8.2 Wire audit log + in-app notification on send (best-effort)
    - Write `write_audit_log` + `create_in_app_notification` on successful send and on failed-send attempts; wrap so failures are logged and never roll back the envelope row.
    - **Audit nuance:** `create_in_app_notification` never raises (self-guarding), but `write_audit_log` (`app/core/audit.py`) does **NOT** swallow exceptions — so the best-effort try/except wrapping around `write_audit_log` (log, never roll back the envelope transaction) is **MANDATORY**, not optional.
    - _Requirements: 3.7, 3.8, 14.3_

  - [x] 8.3 Property test — successful send persists a faithful envelope
    - **Property 7: Successful send persists a faithful envelope**
    - **Validates: Requirements 3.2, 3.6, 4.4, 10.3, 10.4, 13.1**

  - [x] 8.4 Property test — send validation atomic and side-effect-free (service layer)
    - **Property 8: Send validation is atomic and side-effect-free** (service portion: no envelope/recipient rows persisted, no Documenso call)
    - **Validates: Requirements 3.3, 3.4, 4.2, 4.3, 4.6**

  - [x] 8.5 Property test — Documenso failure records an error envelope
    - **Property 18: Documenso failure records an error envelope**
    - **Validates: Requirements 3.5**

  - [x] 8.6 Example test — send orchestration order
    - Assert `create_document` → `upload_pdf` → `place_signature_field` (per signer) → `send_document` are invoked in that order with a mocked client on valid input.
    - _Requirements: 3.1_

  - [x] 8.7 Ensure a signature field per signer before send (R17)
    - Before requesting `send_document`, ensure at least one SIGNATURE field is placed for **each signer** recipient — via `place_signature_field` (`POST /api/v2/documents/{id}/fields`) per signer, or by sending from a Documenso template that already carries signer fields. If any signer would have no signature field, **block the send** (no `send_document` call), return a humanized validation error identifying that signer, and record envelope status `error`.
    - MVP default placement: one SIGNATURE field per signer on the **last page** at the documented default coordinates (`pageX≈65`, `pageY≈85`, `pageWidth≈25`, `pageHeight≈8`); viewer recipients get no field; a send with **zero signers** is a validation error.
    - _Requirements: 17.1, 17.2_

  - [x] 8.8 Property test — every signer has a signature field before send
    - **Property 25: Every signer has a signature field before send** — for any successful send, every signer recipient has ≥1 SIGNATURE field before `send_document`; for any send where a field cannot be placed for some signer, the send is rejected (no `send_document` call) with a human-readable error identifying that signer.
    - **Validates: Requirements 17.1, 17.2**

  - [x] 8.9 Property test — sends are blocked while the org's connection is missing or unverified
    - **Property 27: Sends are blocked while the org's connection is missing or unverified** — for any send attempted while the org's `esign_org_connections` row is missing or `is_verified = false`, the send is blocked with a human-readable error and **no** Documenso API call is made; a send proceeds only when the org's connection is present and verified.
    - **Validates: Requirements 19.3, 19.4**

- [x] 9. Service: void, list, and detail
  - [x] 9.1 Implement `void_envelope(...)`
    - Allow void only when non-terminal: call `DocumensoClient.cancel_document` (issues `DOCUMENT_CANCELLED`), set status `voided`, audit + notify (best-effort). Reject a terminal envelope with a humanized 409 and make no Documenso call.
    - _Requirements: 5.4, 7.1, 7.2, 7.3, 7.4, 12.3_

  - [x] 9.2 Implement `list_envelopes(...)` and `get_envelope_detail(...)`
    - List org-scoped envelopes wrapped `{ items, total }`, ordered by `updated_at DESC`, optional `?status=` filter; on an unapplyable filter return empty items + humanized `filter_unavailable` (fail-closed). Detail returns per-recipient status and `signed_document_url` only when a signed doc is stored; cross-org read → 404.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 13.3, 13.4, 13.5_

  - [x] 9.3 Property test — void allowed exactly when non-terminal
    - **Property 12: Void is allowed exactly when non-terminal**
    - **Validates: Requirements 5.4, 7.1, 7.2, 7.3**

  - [x] 9.4 Property test — dashboard filter, ordering, and detail correctness (fail-closed)
    - **Property 21: Dashboard filter, ordering, and detail are correct and fail-closed**
    - **Validates: Requirements 11.2, 11.3, 11.4, 11.5, 11.6**

  - [x] 9.5 Property test — multi-tenant isolation on read and list
    - **Property 20: Multi-tenant isolation on read and list**
    - **Validates: Requirements 11.1, 13.3, 13.4, 13.5, 13.6**

- [x] 10. Routes and module-gate/RBAC wiring (`router.py`)
  - [x] 10.1 Implement `/api/v2/esign` endpoints and register the router
    - `POST /envelopes` (multipart PDF + JSON, `require_esign_sender`), `GET /envelopes`, `GET /envelopes/{id}`, `POST /envelopes/{id}/void` (`require_esign_sender`), `GET /envelopes/{id}/signed-document` (org-checked). Apply the module-gate dependency (403 when disabled) to all non-webhook routes; register in `app/main.py`.
    - _Requirements: 2.2, 11.1, 12.1, 12.2, 12.3, 13.4, 13.5_

  - [x] 10.2 Property test — module-disabled endpoints rejected
    - **Property 5: Module-disabled endpoints are rejected**
    - **Validates: Requirements 2.2**

  - [x] 10.3 Property test — RBAC for send and void
    - **Property 22: Role-based access control for send and void** — send/void permitted iff the user holds `org_admin`, `branch_admin`, or `location_manager` (via `require_role(ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER)`); all other roles (e.g. `salesperson`, `staff_member`) → HTTP 403.
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [x] 10.4 Example test — no trade-family gating
    - **Property 6: No trade-family gating** (enabling `esignatures` permitted for any trade family)
    - **Validates: Requirements 2.5**

- [x] 11. Checkpoint - Ensure all service/route tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Webhook handler (`webhook_router.py` + `service.apply_webhook`)
  - [x] 12.1 Implement per-org-routed, shared-secret-gated webhook ingestion
    - Mount `POST /api/v2/esign/webhook/{routing_id}` as a public (no-JWT) route. Run with system DB context (`RESET app.current_org_id`) and resolve the organisation by `webhook_routing_id` (cross-org lookup on `esign_org_connections`); load **that organisation's** decrypted webhook secret and do a constant-time `hmac.compare_digest(X-Documenso-Secret header value, that org's stored webhook secret)` of the SECRET STRING (Documenso sends the configured secret verbatim; it does NOT HMAC the body) BEFORE any parse/DB write. An unknown `routing_id` (maps to no org) OR a secret mismatch → 401 + modify nothing. Register the public router in `app/main.py`.
    - _Requirements: 8.1, 8.2_

  - [x] 12.2 Implement idempotent apply + per-recipient update (scoped to the resolved org)
    - After resolving the org by `routing_id` and verifying its secret, set the RLS context to the resolved `org_id`. Synthesize `dedupe_key = SHA-256(event_type + documenso_document_id + recipient identifier/status + createdAt)` from the payload (which has NO native event id); insert the `dedupe_key` into `esign_webhook_events` (unique) with insert-on-conflict → an existing key means acknowledge 200 no-op; a `documenso_document_id` unmapped **within the resolved org** → 200 no-op; otherwise update per-recipient status, compute `next_status`, apply if non-`None` (terminal-safe), stamp the resolved `org_id` onto the recorded event/data; audit + notify on transition; on `completed` trigger signed-document retrieval.
    - **Audit nuance:** `create_in_app_notification` never raises (self-guarding), but `write_audit_log` (`app/core/audit.py`) does **NOT** swallow exceptions — so the best-effort try/except wrapping around `write_audit_log` (log, never roll back the applied transition) is **MANDATORY**, not optional.
    - _Requirements: 4.5, 6.7, 8.3, 8.4, 8.5, 13.6, 14.1, 14.2_

  - [x] 12.3 Property test — per-org webhook routing and shared-secret verification gates all processing
    - **Property 13: Per-org webhook routing and shared-secret verification gates all processing** — for any webhook to `/api/v2/esign/webhook/{routing_id}`, if the `routing_id` maps to no organisation OR the `X-Documenso-Secret` header value != the resolved organisation's stored secret (constant-time compared), the request is rejected 401 and no connection, envelope, recipient, or event row is created or modified.
    - **Validates: Requirements 8.1, 8.2**

  - [x] 12.4 Property test — webhook processing is idempotent
    - **Property 14: Webhook processing is idempotent** — duplicates identified by the synthesized `dedupe_key` are acknowledged 200 without re-applying state.
    - **Validates: Requirements 8.3, 8.4**

  - [x] 12.5 Property test — webhooks for unmapped documents are no-ops
    - **Property 15: Webhooks for unmapped documents are no-ops**
    - **Validates: Requirements 8.5**

  - [x] 12.6 Property test — per-recipient status reflects latest event
    - **Property 11: Per-recipient status reflects the latest recipient event**
    - **Validates: Requirements 4.5**

  - [x] 12.7 Property test — transition records audit and notification
    - **Property 16: Every applied transition records audit and notification**
    - **Validates: Requirements 3.7, 3.8, 6.7, 7.4, 9.6, 14.1, 14.2, 14.4**

  - [x] 12.8 Property test — audit/notification side-effects are best-effort
    - **Property 17: Audit and notification side-effects are best-effort**
    - **Validates: Requirements 14.3**

  - [x] 12.9 Wire the webhook into the public middleware surface and system DB context
    - Register the **prefix** `/api/v2/esign/webhook/` in `PUBLIC_PREFIXES` in `app/middleware/auth.py` (NOT the exact-path `PUBLIC_PATHS` set — the routing id makes each org's webhook path distinct, so a prefix is required) so JWT is skipped for every per-org routing URL. **`request.state` reality:** the auth middleware (`AuthMiddleware`) sets DISCRETE attributes `request.state.user_id` / `request.state.org_id` / `request.state.role` (there is NO `request.state.user` object); downstream/webhook code reads them defensively via `getattr(request.state, "org_id", None)` etc. On the public webhook path these are `None` (expected) and the handler resolves the org from `routing_id` after `RESET app.current_org_id`. Security-hardening §1: never assume `request.state` carries user context — always `getattr(..., None)`.
    - Add the **prefix** `/api/v2/esign/webhook/` to `_CSRF_EXEMPT_PREFIXES` in `app/middleware/security_headers.py` (NOT the exact-path `_CSRF_EXEMPT_PATHS` set), since a server-to-server callback carries no CSRF token or session cookie. No nginx change is needed — the existing `/api/` proxy location already fronts it — and `ModuleMiddleware` naturally skips it (no resolved `org_id`).
    - Add the explicit RLS system-context step in the handler: `RESET app.current_org_id` before resolving the connection by `routing_id` and the cross-org envelope lookup, then stamp the resolved/mapped envelope's `org_id` onto the recorded event/stored rows (R13.6).
    - _Requirements: 8.1, 8.2, 13.6_

  - [x] 12.10 Property/integration test — webhook reaches the handler through the middleware stack
    - Assert a valid signed webhook POSTed to the org's routing URL `/api/v2/esign/webhook/{routing_id}` reaches the handler through the full middleware stack (not blocked by auth/CSRF); AND a webhook with a wrong/absent `X-Documenso-Secret` for the resolved org, or an unknown `routing_id`, returns 401.
    - _Requirements: 8.1, 8.2, 13.6_

- [x] 13. Signed-document retrieval, storage, and scheduled sweep (`signed_document.py`)
  - [x] 13.1 Implement retrieve + encrypted-pipeline store + attach
    - On `completed`: `download_signed` over HTTPS; **always** store ONLY via the encrypted uploads pipeline (`envelope_encrypt` on the bytes + `StorageManager`, category `esign_signed/<org_id>/...`, returning a `file_key`), never the plaintext compliance store — uniformly for **all** originating-entity types **including staff**. Persist `signed_doc_status='stored'` + `signed_doc_file_key` on the envelope; write audit (no contents).
    - **Staff origin: do NOT create a `ComplianceDocument`.** The staff Documents tab is backed by `ComplianceDocument` + `ComplianceFileStorage`, which store files **unencrypted on disk** (conflicts with R9.2/R15.2). The signed staff PDF lives only on the envelope's encrypted `file_key`; it is surfaced via the staff documents listing merge (Task 13.2) and downloaded through the org-checked esign endpoint. Invoice/quote → reference the envelope + `file_key` on that entity (unchanged; still the encrypted pipeline).
    - **Fresh session after commit (ISSUE-005/048 pattern):** because retrieval is triggered after the webhook handler's transaction has already committed and closed, do all post-webhook DB work on a fresh session from `async_session_factory()` with the envelope's `org_id` set on the new RLS context — never the already-committed webhook session.
    - On retrieval/storage failure keep status `completed`, set `signed_doc_status='pending_retrieval'` + humanized `last_error`, write nowhere else/temporarily.
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 9.7, 13.6, 15.2_

  - [x] 13.2 Extend the staff documents listing to merge esign signed docs (Staff → Documents tab)
    - Extend `GET /api/v2/staff/{id}/documents` (`app/modules/staff/router.py`) to **merge in** the org's `esignatures` signed documents for that staff member (envelopes whose originating entity is the staff id with `signed_doc_status='stored'`) alongside the existing `ComplianceDocument` rows, org-scoped. Each merged esign row points its download link at the org-checked `GET /api/v2/esign/envelopes/{id}/signed-document` (which streams from the encrypted pipeline, decrypting at read time) — **not** at a plaintext compliance path.
    - **Schema extension required:** the existing endpoint returns `StaffDocumentListResponse` of `StaffDocumentItem` with fields ONLY (`id`, `document_type`, `description`, `file_name`, `file_size`, `created_at`, `expiry_date`) — no download-link or source field. So the merge requires EXTENDING `StaffDocumentItem` (and its mapping in `app/modules/staff/router.py`) with (a) a source discriminator (e.g. `source: "compliance" | "esign"`) and (b) a fetch handle (e.g. nullable `esign_envelope_id` or `download_url`) so the frontend routes esign rows to `GET /api/v2/esign/envelopes/{id}/signed-document`.
    - Keep the response envelope shape consistent (`{ items, total }`), org scoping, and the `_require_staff_management_module` gate (slug `staff_management`); do not expose `file_key` or signed-document bytes directly.
    - _Requirements: 9.3, 13.4, 13.5_

  - [x] 13.3 Implement scheduled retry sweep
    - A lightweight scheduled task scans `completed` envelopes with `signed_doc_status != 'stored'` and retries retrieval/storage; wire into the existing scheduler.
    - **Scheduler wiring:** the scheduler is a custom asyncio loop in `app/tasks/scheduled.py` driven by a `_DAILY_TASKS` list of `(task_fn, interval_seconds, name)` entries, with a Redis `SETNX` leader lock + node-role checks. Register the retry sweep as a `_DAILY_TASKS` entry AND mark it a **WRITE** task so it is skipped on standby nodes (runs only on the primary).
    - _Requirements: 5.4, 9.5, 9.7_

  - [x] 13.4 Property test — signed documents stored only via encrypted pipeline
    - **Property 19: Signed documents are stored only via the encrypted pipeline** — for staff origin, the signed PDF is stored only on the envelope's encrypted `file_key` (no `ComplianceDocument` row) and surfaced via the merged staff documents listing, served through `GET /api/v2/esign/envelopes/{id}/signed-document`; for invoice/quote it is referenced on the entity. In all cases nothing is written to the plaintext compliance store.
    - **Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.7, 15.2**

  - [x] 13.5 Example test — retrieval invoked on completed transition
    - Assert reaching `completed` triggers signed-document retrieval (`download_signed`) with a mocked client.
    - _Requirements: 9.1_

- [x] 14. Per-organisation Documenso connection service and endpoints (`connection_service.py`)
  - [x] 14.1 Implement the per-org connection service (`app/modules/esignatures/connection_service.py`)
    - Create a new `connection_service.py` operating on the per-organisation `esign_org_connections` record. **Do NOT** touch `valid_names` / `_SAFE_FIELDS` / `_MASKED_FIELDS` in `app/modules/admin/service.py` — those applied only to the removed single global `integration_configs[documenso]` row and no longer apply under the per-org Teams model.
    - `save_connection(db, org_id, ...)` upserts that org's row: store `base_url` and `documenso_team_id` as-is; envelope-encrypt the `service_token` and `webhook_signing_secret` into `service_token_encrypted` / `webhook_secret_encrypted` (writes use `envelope_encrypt(str)`; reads use `envelope_decrypt_str(blob)` — `envelope_encrypt_str` does **not** exist). Generate an opaque, URL-safe, unique `webhook_routing_id` on first create. Compute masked projections (`service_token_last4`, `webhook_secret_last4`) for responses, and apply the `_MASK_PATTERN` round-trip so saving back a masked value retains the stored secret while a non-masked value replaces it. **Clear `is_verified` to false on any update** until a subsequent connection test succeeds (R19.5).
    - `test_connection(db, org_id)` builds `DocumensoClient.for_org(conn, http)` and calls `test_connection()`; **set the org's `is_verified` flag** according to success/failure (R19.2); return a humanized "configure first" error when the org has no connection row (R1.10).
    - Write `esign.connection_updated` / `esign.connection_tested` audit entries without plaintext credential values (R1.7).
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.7, 1.8, 15.1, 19.2, 19.5_

  - [x] 14.2 Implement the per-org connection management endpoints (Global Admin)
    - Add Global-Admin connection endpoints carrying the target org id in the path: `GET`/`PUT /api/v2/admin/organisations/{org_id}/esign/connection` and `POST /api/v2/admin/organisations/{org_id}/esign/connection/test`. `GET` returns the org's connection **masked** (`base_url`, `documenso_team_id`, `is_verified`, masked `service_token`/`webhook_signing_secret`, the org's webhook URL + `webhook_subscription_status`); `PUT` saves/updates via `save_connection` (masked round-trip); `POST .../test` calls `connection_service.test_connection`, sets `is_verified`, and returns valid/invalid (humanized "configure first" when absent). Restrict with `require_role("global_admin")` (there is no `require_global_admin` helper; mirror the admin router's `dependencies=[require_role("global_admin")]`). These routes are added to the admin router (or a dedicated esign-admin router mounted at `/api/v2/admin`).
    - **Why the admin path:** a Global Admin has no active org context, so the org id must be in the path. `/api/v2/admin/` is already a global-admin-only, tenant-context-exempt prefix (`_ADMIN_ONLY_PREFIXES` in `app/middleware/auth.py`) and is OUTSIDE the `/api/v2/esign` `MODULE_ENDPOINT_MAP` prefix, so these connection endpoints are intentionally NOT module-gated (connection setup works regardless of module-enabled state). The `/organisations/{org_id}` segment matches the existing admin router's organisation sub-resource naming (e.g. `PUT /organisations/{org_id}`, `GET /organisations/{org_id}/detail`). The org-USER endpoints (`/api/v2/esign/envelopes...`) stay module-gated.
    - _Requirements: 1.1, 1.4, 1.6, 1.10, 19.1, 19.2_

  - [x] 14.3 Property test — credential storage round-trip
    - **Property 1: Credential storage round-trip** (per-org `esign_org_connections`)
    - **Validates: Requirements 1.2, 15.1**

  - [x] 14.4 Property test — masked credentials never returned in plaintext
    - **Property 2: Masked credentials are never returned in plaintext** (per-org connection responses)
    - **Validates: Requirements 1.4, 15.3**

  - [x] 14.5 Property test — saving a masked value retains the stored secret
    - **Property 3: Saving a masked value retains the stored secret** (per-org connection)
    - **Validates: Requirements 1.5**

  - [x] 14.6 Example/integration tests — connection UI, team_id round-trip, connection test, credential-source guard
    - Assert the org's connection is returned masked (R1.1/R1.4) and `documenso_team_id` round-trips (R1.8); the connection test returns valid/invalid for 200/401 and sets `is_verified` accordingly (R1.6/R19.2); CI-style guard asserts the auth path uses `get_documenso_connection(...)` (the per-org loader) not `settings.*`/`.env` (R1.3).
    - _Requirements: 1.1, 1.3, 1.6, 1.8, 19.2_

  - [x] 14.7 Surface the org's webhook URL + subscription status and document manual per-org registration (R18/R19)
    - In the connection response (Task 14.2 `GET`), surface that organisation's webhook URL `/api/v2/esign/webhook/{routing_id}` and `webhook_subscription_status` (whether that org's Documenso connection + webhook subscription are configured and verified) so a Global_Admin can copy the routing URL into the Documenso UI per org per environment.
    - Document the manual per-org provisioning step: a Global_Admin registers, in the Documenso UI, that organisation's Documenso Team webhook subscription targeting the org's `/api/v2/esign/webhook/{routing_id}` with that org's `webhook_signing_secret`, independently per organisation and per environment (Documenso's REST API exposes no team/token/webhook-subscription creation endpoints, so this is a one-time manual step).
    - _Requirements: 18.1, 18.2, 18.3, 19.1_

  - [x] 14.8 Example test — connection lifecycle
    - Assert a successful connection test sets the org's `is_verified = true` and a failed test sets it `false`; assert updating the connection clears `is_verified` until re-tested; assert the connection response surfaces the org's webhook URL + `webhook_subscription_status`.
    - _Requirements: 1.6, 19.2, 19.5_

  - [x] 14.9 Implement `auto_provision_connection(db, org_id)` (optional best-effort orchestration)
    - Add `auto_provision_connection(db, org_id)` to the connection service: an idempotent / re-runnable orchestration that **persists progress at each step** so any failure is always manually-completable. (0) **Mode gate** — if `get_provisioning_adapter()` returns `None` (`ESIGN_PROVISIONING_MODE=off`), return a humanized "auto-provisioning unavailable; configure manually" result and leave the manual path unaffected (R20.5). (1) Generate the org's `webhook_routing_id` + a fresh `webhook_secret` **first**, reusing them if a prior partial run already recorded them. (2) `adapter.create_team` (skip + reuse when the org already records a `documenso_team_id`), persisting `base_url` + `documenso_team_id` immediately. (3) `adapter.mint_team_token`, persisting it envelope-encrypted into `service_token_encrypted` immediately. (4) `adapter.ensure_webhook(team_id, routing_url, secret)`, persisting `webhook_secret_encrypted` + `webhook_routing_id`. (5) Run the existing connection test and set `is_verified` from the result (R20.2), surfacing the org's webhook URL. (6) On a `ProvisioningError` at any step, **persist whatever was already created** (valid, reusable partial state — never broken), set `is_verified=false`, and return a humanized error directing the admin to complete the connection manually (R20.1, R20.3). Re-runs reuse already-created artefacts rather than duplicating them.
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 19.6_

  - [x] 14.10 Implement the auto-provision endpoint (Global Admin only)
    - Add `POST /api/v2/admin/organisations/{org_id}/esign/auto-provision`, **Global Admin only** (`require_role("global_admin")` — there is no `require_global_admin` helper), that runs `service.auto_provision_connection(db, org_id)` for the target org and returns the resulting connection in the **same masked shape** as the connection `GET` (`*_last4`, never plaintext — R1.4/R15.3) plus a `status` of `provisioned` / `partial` / `unavailable`. On any adapter failure, return the humanized error together with the partially-populated, manually-completable connection.
    - **Why the admin path:** like Task 14.2, a Global Admin has no active org context so the org id is in the path; `/api/v2/admin/` is global-admin-only, tenant-context-exempt (`_ADMIN_ONLY_PREFIXES`) and OUTSIDE the `/api/v2/esign` `MODULE_ENDPOINT_MAP` prefix, so this endpoint is intentionally NOT module-gated. The `/organisations/{org_id}` segment matches the existing admin router's organisation sub-resource naming, and this route is added to the admin router (or a dedicated esign-admin router mounted at `/api/v2/admin`).
    - _Requirements: 19.6, 20.1, 20.2, 20.3, 20.5_

  - [x] 14.11 Property test — failed auto-provisioning never leaves broken state and preserves the manual path
    - **Property 28: Failed auto-provisioning never leaves broken state and preserves the manual path** — for any auto-provision attempt that fails at any step (team create / token mint / webhook create / verifying connection test), the org's `esign_org_connections` row is left **either** fully provisioned + verified **or** manually-completable (never partially-applied broken): created artefacts (`documenso_team_id`, team token, webhook secret, `webhook_routing_id`) are persisted + reusable, `is_verified=false` whenever not fully successful, the manual save/edit/test path still works on that same row, and a non-empty human-readable error is returned. MUST use a mocked/fake `ProvisioningAdapter` — NEVER hit real Documenso internals (tRPC or DB).
    - **Validates: Requirements 20.1, 20.3, 20.4**

- [x] 15. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 16. Frontend: API client and sidebar entry (`frontend-v2/`)
  - [x] 16.1 Implement typed esign API client functions
    - Typed generics for list/detail/send/void/download against `/api/v2/esign`; consume safely (`res.data?.items ?? []`, `res.data?.total ?? 0`); `AbortController` in every `useEffect`.
    - _Requirements: 11.1, 11.5_

  - [x] 16.2 Add "Agreements" sidebar entry gated on the `esignatures` module
    - Show/hide via module context; no trade-family gate.
    - _Requirements: 2.3, 2.4, 2.5_

  - [x] 16.3 Vitest — sidebar gating
    - Assert "Agreements" entry renders when module enabled and is hidden when disabled.
    - _Requirements: 2.3, 2.4_

- [x] 17. Frontend: SendForSignatureModal and Agreements dashboard
  - [x] 17.1 Implement reusable `SendForSignatureModal`
    - PDF upload/select, agreement-type select for the five types, recipient rows (name/email/role); inline validation; surfaces server `{ message, code }` errors; binds originating entity passed in by the caller.
    - The **Send** button shows a loading/disabled state while the request is in flight and re-enables on error so the user can correct and retry.
    - _Requirements: 3.6, 4.1, 16.1_

  - [x] 17.2 Implement `AgreementsDashboardPage`
    - List via `GET /envelopes` with status filter chips, recency order, and a detail drawer showing per-recipient status + signed-document download link when present. Register the route.
    - Implement explicit **loading skeleton** (`animate-pulse` rows, never a blank screen), **error state** with a human-readable message + **Retry** button that re-issues the request, and **empty state** (icon + message + guidance) when the org has no envelopes or the active filter matches none. Safe consumption (`res.data?.items ?? []`, `res.data?.total ?? 0`), typed generics, `AbortController` cleanup.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 17.3 Vitest — send modal rendering
    - Assert the modal offers all five agreement types, renders recipient rows, and binds the originating entity; safe consumption + typed generics asserted.
    - _Requirements: 3.6, 10.3, 10.4_

  - [x] 17.4 Implement Void confirmation modal (destructive action)
    - Confirmation modal ("Void this agreement? This cannot be undone.") with Cancel + Confirm; the Confirm button is **disabled and shows a spinner** while `POST /envelopes/{id}/void` is in flight, surfaces the server `{ message, code }` on failure (e.g. the R7.3 already-terminal message), and refreshes the dashboard row on success. Wire it to the dashboard void action.
    - _Requirements: 7.1, 7.3, 11.1_

  - [x] 17.5 Vitest — void confirmation + dashboard states
    - Assert the void confirmation modal disables/spins Confirm during the request and surfaces server `{ message, code }` on failure; assert the dashboard renders empty and error-with-retry states.
    - _Requirements: 7.1, 7.3, 11.1, 11.5_

- [x] 18. Frontend: contextual send actions and Global-Admin connection settings
  - [x] 18.1 Add "Send for signature" actions on invoice pages, quote pages, and Staff → Documents tab
    - Each opens `SendForSignatureModal` pre-bound to the originating entity (invoice/quote id or staff id); all hidden when the module is disabled.
    - **Note:** the org-user surfaces (Agreements dashboard, send modal, contextual actions in Tasks 16–18) are unchanged by the per-org Teams model — they never expose Documenso connection credentials. Per-org connection management is a **Global-Admin / per-org integration settings surface** (Task 18.3), not an org-user surface.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 18.2 Vitest — contextual action gating
    - Assert the action shows/hides on invoice, quote, and Staff → Documents surfaces based on the module flag.
    - _Requirements: 10.1, 10.2, 10.5_

  - [x] 18.3 Implement the Global-Admin per-org Documenso connection settings view
    - A Global-Admin / per-org integration settings surface (not org-user) where a Global_Admin enters that organisation's `base_url`, `documenso_team_id`, `service_token`, and `webhook_signing_secret`, sees the masked stored values, the org's webhook URL + `webhook_subscription_status` + `is_verified` status, and a **Test** button. Calls `GET`/`PUT /api/v2/admin/organisations/{org_id}/esign/connection` and `POST /api/v2/admin/organisations/{org_id}/esign/connection/test`; safe consumption (`res.data?.… ?? …`), typed generics, `AbortController` cleanup; the Save/Test buttons show loading/disabled state and surface server `{ message, code }` errors.
    - **View location:** the connection management view lives in `frontend-v2/src/pages/admin/OrganisationDetail.tsx`, reached by opening an org from `frontend-v2/src/pages/admin/Organisations.tsx` (R19.7), mirroring the existing Organisations row-action + modal pattern (there is no pre-existing Global-Admin per-org integration page to mirror).
    - This view is the **manual path** (enter/edit `base_url`/`team_id`/`service_token`/`webhook_secret`, masked on read + masked round-trip on save) and is **reached by opening an organisation from the Global-Admin Organisations list** (R19.7); it is the guaranteed manual fallback, always available regardless of `ESIGN_PROVISIONING_MODE`.
    - _Requirements: 1.1, 1.4, 1.6, 19.1, 19.2, 19.7_

  - [x] 18.4 Vitest — connection settings page
    - Assert the page renders masked stored secrets (never plaintext), shows the org's webhook URL + verify status, and the Test button triggers `POST /api/v2/admin/organisations/{org_id}/esign/connection/test` and reflects the resulting `is_verified` state.
    - _Requirements: 1.4, 1.6, 19.2_

  - [x] 18.5 Add the Global-Admin Organisations-list "Provision e-signature" per-row action
    - On the Global-Admin **Organisations list** page (`frontend-v2/src/pages/admin/Organisations.tsx`), add a per-row "Provision e-signature" action — slotted into the existing per-row actions column, mirroring the existing row-action pattern — that calls `POST /api/v2/admin/organisations/{org_id}/esign/auto-provision` for that org. Show **progress** during the best-effort run; on **success** the row reflects the verified connection (`is_verified=true`) and surfaces the org's webhook URL to confirm/register; on **failure** show the humanized server `{ message, code }` plus a **"configure manually"** link that opens that org's E-Signature connection management view in `OrganisationDetail.tsx` (Task 18.3) pre-populated with whatever partial state was recorded; when `ESIGN_PROVISIONING_MODE=off`, the action indicates auto-provisioning is **unavailable** and points to manual config (R20.5).
    - Safe consumption (`?.`, `?? []` / `?? 0`), typed generics, `AbortController` cleanup, and loading/disabled button states. This is a **Global-Admin admin-area** surface, distinct from the unchanged org-user dashboard/modal/contextual actions.
    - _Requirements: 19.6, 19.7, 20.1, 20.2, 20.3, 20.5_

  - [x] 18.6 Vitest — Organisations-list provision action states
    - Assert the per-row "Provision e-signature" action handles the **progress**, **success** (row shows `is_verified=true` + the org's webhook URL), **failure** (humanized `{ message, code }` + "configure manually" link opening the connection management view), and **unavailable** (`ESIGN_PROVISIONING_MODE=off`) states; safe consumption + typed generics asserted.
    - _Requirements: 19.6, 19.7, 20.1, 20.2, 20.3, 20.5_

- [x] 19. External-signing smoke test and end-to-end script
  - [x] 19.1 Smoke test — one-time links, no account, no Documenso UI exposure
    - Assert a send yields Documenso one-time signing links without creating OraInvoice accounts and that no route exposes the Documenso admin/org UI.
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 19.2 Mandatory end-to-end script (`scripts/test_esignature_e2e.py`)
    - Create `scripts/test_esignature_e2e.py` to run inside the app container against `BASE=http://localhost:8000`, emulating the full flow: Global_Admin saves + tests the org's Documenso connection (`PUT`/`POST /api/v2/admin/organisations/{org_id}/esign/connection`, setting `is_verified`) → org_admin sends an envelope → simulate/replay a shared-secret-signed webhook to the org's routing URL `/api/v2/esign/webhook/{routing_id}` (`X-Documenso-Secret` header) → verify status transitions and signed-document storage.
    - Include OWASP checks: no-token request → 401; cross-org envelope access → 404 (IDOR); non-admin send → 403; webhook with wrong secret or unknown routing id → 401; SQL/XSS payloads in recipient fields are stored safely (no injection/reflected execution).
    - **Mandatory cleanup:** delete every created record in a `finally` block; prefix all test-created data with `TEST_E2E_`.
    - _Requirements: 3.1, 8.1, 8.2, 12.2, 13.5_

- [x] 20. Version bump and changelog
  - [x] 20.1 Bump MINOR version and add changelog entry
    - Bump the MINOR version in `pyproject.toml` and `frontend-v2/package.json`, and add a `CHANGELOG.md` entry describing the e-signature (Agreements) integration.
    - _Requirements: 2.1_

- [x] 21. Operational prerequisites (go-live gates, non-code)
  - [x] 21.1 Confirm per-org/per-environment provisioning, prod signing certificate, webhook delivery, and secret rotation
    - **Per-org, per-environment manual provisioning:** for each organisation in each environment, manually provision that org's Documenso Team, its team-scoped API token, and its webhook signing secret in the Documenso UI, then record them in OraInvoice via the per-org connection settings (Task 18.3 / `PUT /api/v2/admin/organisations/{org_id}/esign/connection`) and register that org's webhook subscription targeting its routing URL `/api/v2/esign/webhook/{routing_id}` — independently per organisation and per environment (separate Documenso instances/URLs provision separately).
    - Before prod go-live, confirm a real production signing certificate is provisioned in Documenso (the dev certificate is self-signed with an empty passphrase and must not be used in prod).
    - Test webhook delivery from inside the Documenso container early (per documenso#1303) to confirm each org's `/api/v2/esign/webhook/{routing_id}` callback is reachable for the active environment.
    - Ensure prod Documenso secrets (per-org tokens + webhook secrets) are freshly generated (NOT reused from the committed dev `documenso/.env`), and rotate the committed dev Gmail app password.
    - **`ESIGN_PROVISIONING_MODE` deployment note:** recommended default `off`; when set to `trpc` or `db`, the required platform-level Documenso admin credential (tRPC) or Documenso DB URL (db) must be provisioned as **envelope-encrypted platform config** (never on any org's `esign_org_connections` row). Auto-provisioning is **best-effort / unsupported / upgrade-fragile** (drives Documenso internals); the manual per-org connection path remains the guaranteed fallback at all times.
    - _Requirements: 18.1, 18.3, 19.1, 20.4, 20.5_

- [x] 22. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation sub-tasks are never optional.
- Each task references specific requirement sub-clauses and, for test tasks, the exact design property number for traceability.
- The database work is split across two migrations: Migration A (`0232`, transactional — **four** org-scoped tables including the per-org `esign_org_connections` connection record, CHECK constraints, RLS, inline indexes incl. `esign_org_connections` `UNIQUE(org_id)` + `UNIQUE(webhook_routing_id)`, the mandatory `module_registry` seed + an optional `feature_flags` catalogue/visibility row keyed `key='esignatures'`) and Migration B (`0233`, `CREATE INDEX CONCURRENTLY` in an `autocommit_block`). They are separate files because mixing `CONCURRENTLY` with other DDL is a banned pattern; Task 1.3 verifies them in the app container. (`0226`–`0231` are already taken by shipped specs, so this feature parents on head `0231` and uses `0232`/`0233`.)
- The runtime gate is the **module only** (Task 7.3): the `MODULE_ENDPOINT_MAP` entry `"/api/v2/esign": "esignatures"` plus a router-level `ModuleService.is_enabled` dependency (mirroring staff's `_require_staff_management_module`). `is_enabled` does **not** consult `feature_flags`; the optional `feature_flags` row is catalogue/visibility only and is **not** added to `FLAG_ENDPOINT_MAP`.
- **Per-org connection model:** Documenso is provisioned **per organisation** — each org has its own Documenso Team, team-scoped token, and webhook secret, stored envelope-encrypted in its own `esign_org_connections` row (Tasks 1.1/2.1/14.1). There is no single global Documenso `integration_configs` row, so `admin/service.py`'s `valid_names`/`_SAFE_FIELDS`/`_MASKED_FIELDS` are **not** touched. Credentials load via the per-org loader `get_documenso_connection(db, org_id)` (Task 5.1) and the client is built per org with `DocumensoClient.for_org(conn, http)` (Task 5.2) so every call uses the calling org's own token scoped to its `documenso_team_id` (R13.7, Property 26). Sends are gated on a present + verified connection (Task 8.1, Property 27).
- **Optional auto-provisioning (R20) is an addition layered on top of the per-org manual model — it never replaces it.** A platform-level `ESIGN_PROVISIONING_MODE = off | trpc | db` flag selects an optional `ProvisioningAdapter` (`app/integrations/documenso_provisioning.py`, Task 5.6) that best-effort creates an org's Documenso Team + team token + webhook via Documenso **internals** (admin tRPC or direct PostgreSQL writes — Documenso's public REST API exposes none of these), authenticated by **envelope-encrypted platform-level** provisioning credentials (never per-org, never on `esign_org_connections`). `service.auto_provision_connection` (Task 14.9) orchestrates it idempotently, persisting progress at each step and always recovering to a manually-completable state on failure (Property 28, Task 14.11); the `POST .../auto-provision` endpoint (Task 14.10) returns the masked connection + `provisioned`/`partial`/`unavailable` status. The Global-Admin Organisations-list "Provision e-signature" action (Task 18.5) drives it with progress/success/failure-with-"configure manually"/unavailable states, and the manual connection management view (Task 18.3, reached by opening an org from the Organisations list per R19.7) is the guaranteed fallback at all times (Task 21.1 records the deployment note).
- The webhook public-surface wiring (Task 12.9) registers the **prefix** `/api/v2/esign/webhook/` in `PUBLIC_PREFIXES` (`app/middleware/auth.py`) and `_CSRF_EXEMPT_PREFIXES` (`app/middleware/security_headers.py`) — NOT the exact-path sets, because the per-org `routing_id` makes each org's webhook path distinct — guards user context defensively via `getattr(request.state, "org_id", None)` etc. (the auth middleware sets discrete `request.state.user_id`/`org_id`/`role`, not a `request.state.user` object; on the public webhook path these are `None`), and resets `app.current_org_id` to resolve the org by `routing_id` (cross-org lookup on `esign_org_connections`) before stamping the resolved envelope's `org_id`. No nginx change is needed; `ModuleMiddleware` skips it (no `org_id`).
- Signed staff agreements are stored only on the envelope's encrypted `file_key` (never as a plaintext `ComplianceDocument`) and surfaced by extending the staff documents listing `GET /api/v2/staff/{id}/documents` (Task 13.2) to merge them in, downloaded via the org-checked `GET /api/v2/esign/envelopes/{id}/signed-document`.
- `DocumensoClient` (Task 5.2) targets the Documenso REST API **v2** (`/api/v2/...`) with a raw-token `Authorization` header (no `Bearer`), uses explicit timeouts, exponential-backoff retry on transient failures, and a managed (never-leaked) client lifecycle; it is instantiated **per organisation** via `DocumensoClient.for_org(conn, http)` from the per-org loader `get_documenso_connection` (Task 5.1). The send flow is multi-step: `create_document` → `upload_pdf` → `place_signature_field` (per signer) → `send_document`; void uses `cancel_document` (`DOCUMENT_CANCELLED`); signed-doc retrieval uses `download_signed`. Post-webhook DB work (Task 13.1) runs on a fresh `async_session_factory()` session because the webhook session is already committed.
- Webhook auth is per-org **routing + shared secret**: each org's webhook arrives at `/api/v2/esign/webhook/{routing_id}`; the handler resolves the org by `routing_id`, loads that org's webhook secret, and does a constant-time `hmac.compare_digest` of the `X-Documenso-Secret` header against it before any parse/DB write (Tasks 12.1/12.9) — Documenso sends the configured secret verbatim (it does NOT HMAC the body). Webhook idempotency uses a synthesized `dedupe_key` (`SHA-256` of event type + document id + recipient identifier/status + `createdAt`) because the payload carries no native event id (Tasks 1.1/2.1/12.2).
- Property-based tests use Hypothesis with a minimum of 100 examples each and the comment tag `# Feature: esignature-integration, Property {n}: {property_text}`. Pure-core properties (3.x, 4.x) run without I/O; service-level properties use a real test Postgres (`postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro` on host) with a mocked `DocumensoClient`.
- Task 19.2 is a mandatory end-to-end script with OWASP checks and mandatory `finally`-block cleanup (`TEST_E2E_` prefix); Task 20.1 bumps the MINOR version and updates the changelog. Task 21.1 captures non-code go-live gates (per-org/per-environment manual provisioning, prod signing certificate, in-container webhook delivery test, secret/Gmail-password rotation).
- Checkpoints provide incremental validation at the boundaries of foundation, service/routes, backend completion, and full feature.
- All 28 correctness properties are covered: P1/P2/P3 (14.x, per-org connection), P4/P23/P26 (5.x), P5/P6/P22 (10.x), P7/P8/P18/P27 (8.x), P8 pure-core (4.2), P9/P10 (3.x), P11/P13/P14/P15/P16/P17 (12.x), P12/P20/P21 (9.x), P19 (13.x), P24 (7.x), P25 (8.8), P28 (14.11). Signature-field placement (R17) is implemented in Task 8.7; the per-org connection lifecycle and webhook-subscription surfacing (R18/R19) in Tasks 14.1/14.2/14.7; the connection gate on send (R19.3/19.4) in Task 8.1; optional best-effort auto-provisioning (R20 + R19.6) in the provisioning adapter (Task 5.6), `auto_provision_connection` (Task 14.9), the auto-provision endpoint (Task 14.10), and the Global-Admin Organisations-list action (Task 18.5).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "2.2", "3.1", "4.1", "5.1"] },
    { "id": 2, "tasks": ["1.3", "1.4", "3.2", "3.3", "4.2", "5.2", "7.1"] },
    { "id": 3, "tasks": ["5.3", "5.4", "5.5", "5.6", "7.2", "7.3", "8.1", "14.1"] },
    { "id": 4, "tasks": ["7.4", "8.2", "9.1", "9.2", "14.2", "14.3", "14.4", "14.5", "14.6", "14.9"] },
    { "id": 5, "tasks": ["8.3", "8.4", "8.5", "8.6", "8.7", "8.9", "9.3", "9.4", "9.5", "10.1", "14.7"] },
    { "id": 6, "tasks": ["8.8", "10.2", "10.3", "10.4", "12.1", "14.8", "14.10", "14.11"] },
    { "id": 7, "tasks": ["12.2", "13.1"] },
    { "id": 8, "tasks": ["12.3", "12.4", "12.5", "12.6", "12.7", "12.8", "12.9", "13.2", "13.3", "13.4", "13.5"] },
    { "id": 9, "tasks": ["12.10", "16.1", "16.2"] },
    { "id": 10, "tasks": ["16.3", "17.1", "17.2"] },
    { "id": 11, "tasks": ["17.3", "17.4", "18.1", "18.3"] },
    { "id": 12, "tasks": ["17.5", "18.2", "18.4", "18.5", "19.1", "19.2"] },
    { "id": 13, "tasks": ["18.6", "20.1", "21.1"] }
  ]
}
```
