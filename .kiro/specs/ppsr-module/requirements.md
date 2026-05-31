# PPSR Module — Requirements

## Overview

A standalone module that lets org users run PPSR (Personal Property Securities Register) checks on NZ vehicles, including money-owing status, financing-statement details, ownership history, and warning flags. Built on top of the existing CarJam integration that already powers basic vehicle lookups — **no new third-party credentials**, no dependencies on other staff-management modules.

**Source:** CarJam API documentation supplied by the user 2026-05-31 (`https://www.carjam.co.nz/api/car/`).

**Trade-family scope:** Universal (any business that owns or transacts vehicles can find PPSR checks useful — automotive workshops resell stock, builders buy work utes, hospitality buys delivery vehicles). Module is **opt-in** for any org regardless of trade family. Frontend nav placement defaults under "Tools" for non-automotive trades and under "Vehicles" for automotive.

**Status:** Draft.

**Dependencies:** None. Reuses the existing CarJam integration (`app/integrations/carjam.py`) and credentials storage (`integration_configs[name='carjam']`).

## Steering compliance

- **Module registration** per `setup-guide-for-new-modules.md`: ships with `setup_question` + `setup_question_description` so it appears in the new-org wizard automatically. Not in `TRADE_GATED_MODULES` (universal opt-in).
- **Credentials** per `integration-credentials-architecture.md`: reuses the existing `integration_configs[name='carjam']` row; never reads from env vars; uses the existing `_load_carjam_client(db, redis)` factory pattern from `app/modules/vehicles/service.py:28`.
- **Migrations** per `database-migration-checklist.md`: every index via `CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside `op.get_context().autocommit_block()`. Zero `op.create_index(...)` calls.
- **RLS** per migration 0008 pattern: every new table has `ENABLE ROW LEVEL SECURITY` + `tenant_isolation` policy from creation.
- **API contract** per `frontend-backend-contract-alignment.md`: all list responses wrap arrays as `{ items: [...], total: N }`; new fields added to Pydantic response schemas (not just service dicts).
- **Safe API consumption** per `safe-api-consumption.md`: every frontend `?.` + `?? []` + `?? 0`; every `useEffect` API call has AbortController cleanup; no `as any`.
- **No env vars** introduced (per `implementation-completeness-checklist.md` Rule 3): all config in DB.
- **No "Coming soon" placeholders** (Rule 4): every page ships with real form + error/empty/loading states.
- **PII handling** per `security-hardening-checklist.md`: PPSR responses contain financial information about debtors and (when s241-authorised) personal info about owners. Stored as encrypted JSONB; never returned in raw form to lower roles.
- **Module gating** per `app/core/modules.py::ModuleService.is_enabled`: every endpoint gated.
- **Cache** + rate-limit per `performance-and-resilience.md`: PPSR responses cached briefly in Redis (5-minute TTL by default; configurable per-org); the existing CarJam global rate limiter still applies.
- **Audit logging** via `app/core/audit.py::write_audit_log` — every search written, with the searcher's `user_id`, the `rego`, the requested options, and the search outcome.

## Requirements

### R1. Module Registration

**User story:** As a new org going through the setup wizard, I see a yes/no question about checking vehicle finance status, and answering yes enables PPSR checks for my org.

**Acceptance criteria:**

1. THE SYSTEM SHALL insert one row into `module_registry` (idempotent `ON CONFLICT (slug) DO NOTHING`) with:
   - `slug='ppsr'`
   - `display_name='PPSR Vehicle Checks'`
   - `description='Run PPSR money-owing and ownership checks on NZ vehicles via CarJam.'`
   - `category='vehicles'` (or `'tools'` — design picks based on the existing category naming)
   - `is_core=false`
   - `dependencies='[]'::jsonb` (no module dependencies)
   - `incompatibilities='[]'::jsonb`
   - `status='available'`
   - `setup_question='Do you need to check if a vehicle has money owing on it (PPSR) or look up ownership history?'`
   - `setup_question_description='Run finance-status, ownership, and warning checks on any NZ-registered vehicle. Uses the same CarJam connection as vehicle lookups.'`

2. THE SYSTEM SHALL insert a mirror row into `feature_flags` per Rule 8 of `implementation-completeness-checklist.md`, using the **actual column shape** verified at [app/modules/feature_flags/models.py:18-80](app/modules/feature_flags/models.py#L18-L80): `id, key, display_name, description, category, access_level, dependencies, default_value, is_active, targeting_rules, created_at, updated_at`. There is **no** `default_enabled` and **no** `scope` column — those names appear in steering text only and would crash on INSERT. Mirror the [0203_staff_phase1_schema.py:254-276](alembic/versions/2026_05_31_0900-0203_staff_phase1_schema.py#L254-L276) pattern exactly: `key='ppsr'`, `display_name='PPSR Vehicle Checks'`, `category='operations'`, `access_level='all_users'`, `dependencies='[]'::jsonb`, `default_value=true`, `is_active=true`, `targeting_rules='[]'::jsonb`. (`default_value=true` follows the policy from migration 0171 — module gate is the real lever; the flag mirror is passive.)

3. THE SYSTEM SHALL update all unarchived subscription plans' `enabled_modules` JSONB to include `'ppsr'` (idempotent set-union per [0203_staff_phase1_schema.py:229-240](alembic/versions/2026_05_31_0900-0203_staff_phase1_schema.py#L229-L240) — `WHERE is_archived = false`, **not** a `name ILIKE` heuristic). This resolves PPSR-001 the same way Phase 1 resolved STAFF-001.

4. THE SYSTEM SHALL NOT add `ppsr` to `TRADE_GATED_MODULES` in `app/modules/setup_guide/router.py` — it's a universally available opt-in, not auto-enabled by trade family.

5. THE SYSTEM SHALL gate every PPSR endpoint behind `ModuleService.is_enabled(org_id, 'ppsr')` via the existing `app/middleware/modules.py::ModuleMiddleware` (registers `/api/v2/ppsr` in `MODULE_ENDPOINT_MAP`). When disabled, the middleware returns HTTP **403** with body `{ "detail": "Module 'ppsr' is not enabled for your organisation.", "module": "ppsr" }` (verified against `app/middleware/modules.py:117-126` — the spec previously said 404; corrected).

6. THE SYSTEM SHALL handle the platform-admin case (`global_admin` users have no `org_id`): when a `global_admin` hits `/api/v2/ppsr/*` endpoints, the middleware fails open (per `app/middleware/modules.py:95-97`); the router additionally enforces `if not current_user.org_id: raise HTTPException(403, "ppsr_requires_org_context")` so global admins can't accidentally run searches. Global admins read audit-log surface via the existing Audit Log admin screen (not via PPSR endpoints).

### R2. CarJam Client Extension

**User story:** As a backend developer, I need the existing `CarjamClient` to support PPSR-flavored queries without forking it.

**Acceptance criteria:**

1. THE SYSTEM SHALL extend `CarjamClient` in `app/integrations/carjam.py` with a new method:
   ```python
   async def lookup_ppsr(
       self,
       rego: str,
       *,
       include_basic: bool = True,
       include_owners: bool = False,
       include_owner: bool = False,
       include_warnings: bool = True,
       include_fws: bool = False,
       check_hidden_plates: bool = False,
       s241_purpose: str | None = None,
       translate: bool = True,
       use_cache: int | str | None = None,
   ) -> CarjamPpsrResponse
   ```
   - `include_basic` → maps to `basic=1` (always on for PPSR — gives `idh`).
   - `include_owners` → `owners=1` (ownership history, **requires s241_purpose**).
   - `include_owner` → `owner=1` (current owner only, **requires s241_purpose**).
   - `include_warnings` → `warnings=1` (compulsory recalls, write-offs).
   - `include_fws` → `fws=1` (fire/water/write-off).
   - `check_hidden_plates` → `ppsrh=1` (additional charges; searches past plates).
   - `s241_purpose` → required when `include_owners` or `include_owner`; passed as `s241_purpose=<purpose>`.
   - `translate=True` → adds `translate=1` so the response includes human-readable variants in `hidh`, `hioh`, `hico`, `hirh`.
   - `use_cache` → maps to the `cache` parameter (see CarJam docs; `0` = no cache, `1` = default 10 years, or a `strtotime` string like `-1 month`).
   - Always sends `ppsr=1`.

2. THE SYSTEM SHALL define a typed response dataclass `CarjamPpsrResponse` with these top-level fields parsed from the XML response:
   - `rego: str`
   - `not_found: bool`
   - `basic: dict | None` — raw `idh` content (lookup_vehicle's existing `CarjamVehicleData` already covers this; reuse).
   - `ownership_history: list[dict] | None` — `ioh.owners` array (when `owners=1`).
   - `current_owner: dict | None` — `ico` content (when `owner=1`).
   - `ppsr_summary: dict` — `ppsr` tag content (financing-statement count + match summary).
   - `ppsr_details: list[dict]` — `ppsr_details` content (each financing statement, up to 50).
   - `money_owing: dict` — `money_owing` tag content with `match`, `match_description`, `search_id`.
   - `warnings: list[dict] | None` — `warnings` array.
   - `flood: dict | None` — `flood` content (when `fws=1`).
   - `charges_cents: int | None` — `charges` content if returned.
   - `raw_xml: str` — the unaltered response body for audit storage.
   - `requested_options: dict` — the option flags that produced this response (for audit + reproducibility).

3. THE SYSTEM SHALL apply the existing `_check_carjam_rate_limit` (the global Redis-backed limit) before every PPSR HTTP call. PPSR queries count against the same global CarJam budget — the limiter already exists.

4. THE SYSTEM SHALL refuse with `ValueError("s241_purpose required when include_owners or include_owner is true")` if either flag is set without a purpose.

5. THE SYSTEM SHALL raise the existing `CarjamNotFoundError` / `CarjamRateLimitError` / generic `CarjamError` exception classes; no new exception classes needed.

### R3. `ppsr_searches` Table (audit log + cache)

**Acceptance criteria:**

1. THE SYSTEM SHALL create `ppsr_searches`:
   ```sql
   id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
   org_id          uuid NOT NULL REFERENCES organisations(id),
   user_id         uuid NOT NULL REFERENCES users(id),              -- who ran the search
   rego            text NOT NULL,                                   -- normalised UPPER
   options_json    jsonb NOT NULL,                                  -- exact flags + s241_purpose
   match           text,                                            -- money_owing.match: Y/PY/M/PM/U/N
   match_description text,
   statement_count int NOT NULL DEFAULT 0,
   has_warnings    boolean NOT NULL DEFAULT false,
   has_ownership_data boolean NOT NULL DEFAULT false,
   response_encrypted bytea,                                        -- envelope_encrypted full JSON (per security-hardening-checklist §2)
   charges_cents   int,                                             -- cost reported by CarJam if known
   not_found       boolean NOT NULL DEFAULT false,
   error_message   text,                                            -- non-NULL when the search failed
   carjam_request_id text,                                          -- for vendor support traceability
   created_at      timestamptz NOT NULL DEFAULT now()
   ```

2. RLS + tenant_isolation policy.

3. **Encryption rule:** `response_encrypted` stores the envelope-encrypted JSON via `app/core/encryption.py::envelope_encrypt(plaintext: str | bytes) -> bytes` (verified — *not* `envelope_encrypt_str`; that name appears only in steering text but the helper itself is `envelope_encrypt` per `app/core/encryption.py:66`). The plaintext top-level summary fields (`match`, `statement_count`, etc.) are denormalised onto the row for indexing + filtering without decryption.

4. **Extra columns added (G13/G30/G39 closure):**
   - `org_vehicle_id   uuid REFERENCES org_vehicles(id) ON DELETE SET NULL` — set on save when rego matches an existing OrgVehicle row.
   - `global_vehicle_id uuid REFERENCES global_vehicles(id) ON DELETE SET NULL` — same, for the global table.
   - `options_hash     text NOT NULL` — `sha256(json.dumps(options_json, sort_keys=True))` hex digest, used as the cache-lookup key so JSON-key-order changes don't break cache hits.
   - `forgotten_at     timestamptz` — set when the admin invokes the forget endpoint; `response_encrypted` is set to NULL and `error_message='forgotten by admin'`. (G29)

5. **Indexes (CONCURRENTLY):**
   - `idx_ppsr_searches_org_created ON ppsr_searches (org_id, created_at DESC)` — history page.
   - `idx_ppsr_searches_org_rego_options_created ON ppsr_searches (org_id, rego, options_hash, created_at DESC)` — cache lookup. (Note G24: rego is normalised UPPER on insert, so a plain `rego` column index is sufficient — no `UPPER(rego)` function index needed.)
   - `idx_ppsr_searches_user ON ppsr_searches (user_id, created_at DESC)` — per-user activity report.
   - `idx_ppsr_searches_org_vehicle ON ppsr_searches (org_id, org_vehicle_id, created_at DESC) WHERE org_vehicle_id IS NOT NULL` — Vehicle Profile embed latest-match lookup.

### R4. Search Endpoint

**Acceptance criteria:**

1. THE SYSTEM SHALL expose `POST /api/v2/ppsr/search` with body:
   ```json
   {
     "rego": "ABC123",
     "include_ownership_history": false,
     "include_current_owner": false,
     "include_warnings": true,
     "include_fws": false,
     "check_hidden_plates": false,
     "s241_purpose": null,
     "force_refresh": false
   }
   ```

2. THE SYSTEM SHALL normalise `rego` to upper-case + strip whitespace before any query.

3. THE SYSTEM SHALL check the org's `ppsr_lookups_this_month` vs `subscription_plans.ppsr_lookups_included` quota (per R5). When over quota, return HTTP 402 `{ "detail": "ppsr_quota_exceeded", "used": N, "included": M }` — same shape as the existing CarJam quota response.

4. THE SYSTEM SHALL serve a cached result from `ppsr_searches` instead of calling CarJam when:
   - A successful search exists for the same `(org_id, rego, options_hash)` (per G30) within the configured TTL (default 5 minutes; admin-overridable via `ppsr_cache_ttl_minutes` per R7), AND
   - `force_refresh=false`, AND
   - `response_encrypted IS NOT NULL` (forgotten rows don't satisfy cache; per G26), AND
   - `error_message IS NULL` AND `not_found = false`.
   - Cached responses return a `cached: true, cached_at: <timestamp>, source_search_id: <id>` field in the response so the user knows they're seeing a recent result.

5. THE SYSTEM SHALL refuse with HTTP 422 `{ "detail": "s241_purpose_required" }` when `include_ownership_history` or `include_current_owner` is true but `s241_purpose` is null AND no default is configured on `integration_configs[name='carjam'].s241_purpose_default`.

6. THE SYSTEM SHALL refuse with HTTP 422 `{ "detail": "s241_not_authorised" }` when `ppsr_owner_lookups_enabled=false` on `integration_configs[name='carjam']` (admin must explicitly opt-in per R7).

6a. **(G28/G49 closure)** WHEN no `integration_configs` row exists with `name='carjam'` OR the row exists but the decrypted `api_key` is missing/empty, THE SYSTEM SHALL return HTTP 422 `{ "detail": "carjam_not_configured", "help_url": "/admin/integrations" }` on all PPSR endpoints (G-CODE-10 — the actual admin Integrations page lives at `/admin/integrations`, not `/settings/integrations/carjam`). The service treats missing optional fields (`s241_purpose_default`, `ppsr_cache_ttl_minutes`, `ppsr_owner_lookups_enabled`) as null/5/false respectively — never crashes.

6b. **(G27 closure)** THE SYSTEM SHALL acquire a Redis-backed in-flight lock keyed on `ppsr:lock:{org_id}:{rego}:{options_hash}` (TTL 30s) before calling CarJam. Duplicate concurrent requests wait briefly (up to 5s) for the holder's result; on lock-wait timeout they get the holder's cached row if it has landed, otherwise they call CarJam themselves. This prevents the same rego+options being billed twice by an over-eager double-click.

7. THE SYSTEM SHALL call `CarjamClient.lookup_ppsr(...)` with the supplied options, log the search in `ppsr_searches` (encrypted), increment the quota counter, and return:
   ```json
   {
     "search_id": "uuid",
     "rego": "ABC123",
     "cached": false,
     "match": "N",
     "match_description": "No money owing",
     "statement_count": 0,
     "ppsr_details": [...],
     "ownership_history": [...] | null,
     "current_owner": {...} | null,
     "warnings": [...],
     "basic": {...},
     "charges_cents": 50,
     "carjam_request_id": "..."
   }
   ```

8. THE SYSTEM SHALL audit-log every search via `write_audit_log` with `action='ppsr.search'`, `entity_type='ppsr_search'`, `entity_id=:search_id`, `after_value={ rego, options, match, statement_count, charges_cents }`. **No raw response in the audit row** — the encrypted payload lives on the `ppsr_searches` row itself.

### R5. Quota & Cost Tracking

**Acceptance criteria:**

1. **(G44 closure — renamed counters for clarity)** THE SYSTEM SHALL add two columns to `subscription_plans`:
   - `ppsr_lookups_included int NOT NULL DEFAULT 0` — standard PPSR queries (basic + ppsr + warnings).
   - `ppsr_hidden_plate_lookups_included int NOT NULL DEFAULT 0` — separate counter for hidden-plate / `ppsrh=1` queries which CarJam bills at a higher rate. (Previously called `ppsr_money_owing_lookups_included`; renamed because `ppsrh` is the hidden-plate flag, not the money-owing flag — money-owing always runs.)
   Default plans get `ppsr_lookups_included=0` (admin must explicitly grant). One-time backfill optional.

2. THE SYSTEM SHALL add two columns to `organisations`:
   - `ppsr_lookups_this_month int NOT NULL DEFAULT 0`
   - `ppsr_hidden_plate_lookups_this_month int NOT NULL DEFAULT 0`
   And mirror the existing `carjam_lookups_reset_at` reset cadence (monthly rollover at UTC month boundary).

3. THE SYSTEM SHALL increment the appropriate counter exactly once per successful CarJam HTTP call (NOT on cache hits) inside the same DB transaction as the `ppsr_searches` INSERT. Atomic via `UPDATE organisations SET ppsr_lookups_this_month = ppsr_lookups_this_month + 1 WHERE id = :id`. When `check_hidden_plates=true`, also bumps `ppsr_hidden_plate_lookups_this_month`.

3a. **(G-CODE-8 closure — actual reset path)** THE existing billing-cycle task at [app/tasks/subscriptions.py::process_due_billings](app/tasks/subscriptions.py#L196) (NOT `app/tasks/scheduled.py`) SHALL reset both PPSR counters in the same per-org block that resets `org.carjam_lookups_this_month`. The reset is overage-conditional (`if ppsr_overage_count > 0:`); a `ppsr_overage_count` computation is added beside the existing `carjam_overage_count`. Per-org locking inside `process_due_billings` already prevents the double-reset race, so no extra time-window guard is needed.

4. THE SYSTEM SHALL expose `GET /api/v2/ppsr/quota` returning `{ used, included, hidden_plate_used, hidden_plate_included, resets_at }` for the current org. Used by the search page header to surface remaining quota.

5. THE existing `carjam_lookups_*` counters on `subscription_plans` + `organisations` are NOT shared with PPSR — separate budgets so admins can throttle the costlier PPSR queries independently.

6. **(G10 closure — per-org rate limit)** THE SYSTEM SHALL apply a per-org rate limit of **10 PPSR searches per minute** (rolling window) on `POST /api/v2/ppsr/search` via the existing rate-limit middleware (`app/middleware/rate_limit.py`). On 429, return `Retry-After` header (in seconds) per security-hardening §6. Cache hits do NOT consume rate-limit budget.

### R6. Search History + Detail Endpoints

**Acceptance criteria:**

1. `GET /api/v2/ppsr/searches?rego=&match=&user_id=&date_from=&date_to=&offset=&limit=` — list searches for the org, `{ items: [...], total: N }`. **(G5 closure — filter spec)** Filters supported: `rego` (UPPER substring match), `match` (exact one of `Y/PY/M/PM/U/N`), `user_id` (exact match — admins only; non-admins are force-filtered to their own), `date_from` / `date_to` (ISO date). Sort: `created_at DESC` always. Pagination: `offset` (default 0) + `limit` (default 25, max 100). Includes denormalised summary fields only (no encrypted payload).

2. `GET /api/v2/ppsr/searches/:id` — single search detail with decrypted payload. **(G36/G37 closure — role simplification)** Access rule: `current_user.role == 'org_admin'` OR `search.user_id == current_user.id`. No branch-scoping (PPSR is org-level data; `ppsr_searches` has no `branch_id`). Decryption happens inside this endpoint only. **(G29 closure)** When `forgotten_at IS NOT NULL`, return HTTP 410 `{ "detail": "search_forgotten", "forgotten_at": <ts> }` with the summary fields still in the body for audit context but no `response` field.

3. `GET /api/v2/ppsr/searches/:id/export` — returns the decrypted payload as a downloadable PDF (rendered via WeasyPrint, mirroring `app/modules/invoices/service.py:4449-4452`). Same access rule as R6.2. Returns 410 (not 404) when forgotten. Counts as an audit-worthy event (`ppsr.exported`).

4. **(G26 closure)** `DELETE /api/v2/ppsr/searches/:id/forget` — `org_admin` only. Sets `response_encrypted=NULL`, `forgotten_at=now()`, `error_message='forgotten by admin'`. Invalidates any Redis cache keys of the form `ppsr:cache:{org_id}:{rego}:{options_hash}` (best-effort — `_find_recent_match` already skips forgotten rows per R4.4, so a stale Redis hint is harmless). Audit row `ppsr.forgotten` written. Returns 204.

### R7. CarJam → PPSR Configuration Page (Settings)

**User story:** As an org admin, I want to configure the s241 purpose code on my CarJam credentials, so PPSR queries that need ownership data work.

**Acceptance criteria:**

1. THE SYSTEM SHALL extend the existing CarJam config card (Global Admin → Integrations → CarJam, and the equivalent at the org level under Settings → Integrations → CarJam if it exists) with a new "PPSR" section:
   - `s241_purpose_default` text input — the purpose code authorised for the account (sourced by the org from their CarJam member dashboard → s241 section).
   - `ppsr_cache_ttl_minutes` int input, default 5 — how long to serve cached PPSR results before re-hitting CarJam. Applies only to the cache rule in R4.4.
   - `ppsr_owner_lookups_enabled` bool, default false — explicit org-level opt-in for owner / owners options (admin must tick this AND set `s241_purpose_default` before the API will accept `include_current_owner=true` or `include_ownership_history=true`).

2. The fields persist into the `integration_configs[name='carjam']` JSON payload alongside the existing `api_key`. `app/modules/admin/service.py:1742` (`"carjam": ["api_key"]`) gets `s241_purpose_default` and `ppsr_cache_ttl_minutes` and `ppsr_owner_lookups_enabled` added to the schema definition.

3. THE SYSTEM SHALL mask the `s241_purpose_default` value with the existing mask-pattern detection (the value isn't a secret per se, but treating it like one keeps the GUI consistent).

### R8. Frontend — Search Page

**User story:** As an org user, I open the PPSR Search page, type a rego, choose what to include, click Search, see the result.

**Acceptance criteria:**

1. THE SYSTEM SHALL add a route `/ppsr/search` registered in `App.tsx`, lazy-loaded, behind `ModuleRoute moduleSlug='ppsr'`.

2. THE SYSTEM SHALL add a sidebar item "PPSR Check" under "Tools" (or "Vehicles" when the trade family is `automotive-transport`).

3. The page contains:
   - **Quota strip** (top): "PPSR lookups this month: 7 / 50 — resets 1 Jul" + small bar.
   - **Search form:**
     - `rego` text input (uppercase, alphanumeric, 1-8 chars).
     - **Include** checkboxes: "Money owing (always on)", "Warnings & recalls" (default on), "Fire/water/write-off", "Hidden-plate search (extra charge)", "Current owner" (disabled when `ppsr_owner_lookups_enabled=false` or `s241_purpose_default` is unset; tooltip explains why), "Ownership history" (same gating).
     - `s241_purpose` text input — only shown when "Current owner" or "Ownership history" is checked; pre-populated with `s241_purpose_default`; admin can override per search.
     - `Force refresh` toggle — bypasses the 5-minute cache.
   - **Search button** (loading state on click).
   - **Recent searches** (bottom) — paginated list of past searches with quick-reload links.

4. The page renders the response in a structured way:
   - **Money owing**: prominent traffic-light banner (red for `Y`/`PY`, amber for `M`/`PM`, grey for `U`, green for `N`).
   - **Basic vehicle**: make/model/year/colour summary.
   - **Financing statements**: table of `ppsr_details` rows with collateral description, secured party, registration date.
   - **Warnings**: severity-coloured rows.
   - **Ownership** (when included): table with owner name (or masked when no s241), dates, status.
   - **Charges**: footer showing CarJam cost in NZD.
   - **Actions**: Export PDF, Save report to vehicle file (links to existing vehicle record if rego matches an `org_vehicles` or `global_vehicles` entry), New search.

5. All API consumption uses `?.` + `?? []` + AbortController per `safe-api-consumption.md`. No `as any`.

### R9. Frontend — Embedded Quick-Check on Vehicle Profile

**Acceptance criteria:**

1. WHEN module is enabled AND the current page is a Vehicle Profile (existing page at `frontend/src/pages/vehicles/VehicleProfile.tsx`) THE SYSTEM SHALL render a "PPSR" card alongside the existing WOF / COF / registration cards.

2. The card shows the most recent `ppsr_searches` row for the rego (if any) with the match traffic-light and a "View / Re-run check" button. If no prior search exists, shows "No PPSR check on file — run one now" button.

3. Clicking "Run now" navigates to `/ppsr/search?rego=<rego>` with the rego pre-filled and warnings + basic checked by default.

4. The card is gated by `<ModuleGate module="ppsr">` — invisible when the module is disabled, regardless of trade family. (G-CODE-3: the actual prop name is `module`, not `moduleSlug`; verified at [ModuleGate.tsx:13](frontend/src/components/common/ModuleGate.tsx#L13).)

### R10. Audit Logging

THE SYSTEM SHALL write audit rows for:

- `ppsr.search` — every PPSR HTTP call (cache hits get a separate row `ppsr.search.cached` with `source_search_id` in `after_value`).
- `ppsr.config_updated` — admin changes to s241_purpose_default, ppsr_cache_ttl_minutes, ppsr_owner_lookups_enabled.
- `ppsr.exported` — PDF export of a saved search.
- `ppsr.quota_exceeded` — 402 response served (so ops can see when orgs are saturating their plan).

**Audit redaction rule:** `after_value` for `ppsr.search` contains `{ rego, options, match, statement_count, charges_cents }` only — never the full debtor / owner details. Those live encrypted on the `ppsr_searches` row and are visible to the explicit `GET /searches/:id` endpoint (per R6.2 access rule).

### R11. E2E Test Script

**Acceptance criteria:**

1. THE SYSTEM SHALL ship `scripts/test_ppsr_module_e2e.py` per `feature-testing-workflow.md`.
2. The script SHALL: login as org_admin, enable the `ppsr` module on the test org, configure `s241_purpose_default`, POST `/ppsr/search` with `rego='TEST_E2E_PLATE'` against the **test CarJam endpoint** (`https://test.carjam.co.nz/api/car/`), assert the response shape, hit the cache path on a second call, verify quota counter incremented exactly once, fetch the search detail (verify decryption works for admin), attempt the same fetch as a different non-admin user (should 403), export PDF, hit the quota-exceeded path by setting `included=1` and running two searches, cleanup all created rows in `finally`.
3. Test data prefixed `TEST_E2E_`; cleanup verified by post-test SELECT.
4. **(G18 closure — OWASP coverage)** The script SHALL additionally cover:
   - **A1 IDOR:** as org_B's user, attempt `GET /api/v2/ppsr/searches/<org_A_search_id>` → assert 403 or 404 (RLS handles).
   - **A2 PII leakage:** assert the list-endpoint response payload (raw bytes) does NOT contain decrypted owner names, debtor names, or any field from `response_encrypted`.
   - **A3 SQL injection:** POST `/ppsr/search` with `rego="'; DROP TABLE ppsr_searches; --"` → assert 422 (rego validation rejects non-alphanumeric).
   - **A5 misconfiguration:** trigger a 500 (e.g., corrupt the encrypted payload, then GET detail) → assert response has no stack trace, no SQL fragment.
   - **A8 audit log:** assert `audit_log` table has exactly one row per fresh search, one row per cache hit (`ppsr.search.cached`), one row per export, one row per forget; assert `after_value` JSONB contains only summary fields (run `jq` over each row).
   - **Module-gate response shape:** disable module → POST `/ppsr/search` → assert response is HTTP **403** (not 404) with body `{ detail, module: "ppsr" }` per the actual middleware (G38 closure).

### R12. Versioning + Issue IDs

**Acceptance criteria:**

1. THE SYSTEM SHALL bump `pyproject.toml`, `frontend/package.json`, `mobile/package.json` MINOR version (per `versioning-and-changelog.md`).
2. CHANGELOG entry listing: PPSR module, search page, quota tracking, vehicle-profile embed, CarJam config extension.
3. Allocate `PPSR-001`..`PPSR-005` placeholder IDs in `docs/ISSUE_TRACKER.md` for the open questions in §Open Questions below.

## Non-Goals

- **RUC queries** (`rucs=1`, `ruc_outstanding=1`). The CarJam API supports them but PPSR module focus is on money owing + ownership + warnings. RUC is a future-phase add-on.
- **Motfuel/FuelSaver** (`motfuel=1`). Same reason.
- **Valuation** (`valuation=1`). Different commercial conversation.
- **Mobile app surface.** First cut is web only. Mobile entry deferred — mobile-app.md scope already large.
- **Automated bulk searches** (CSV upload of 200 regos and a bulk PPSR run). The CarJam global rate limiter would throttle this and the per-search cost makes it expensive. Could be a future enhancement.
- **PPSR registration / amendment** (registering a security interest as a secured party). That's a different PPSR surface entirely (the NZ Companies Office b2b API), not CarJam.

## Open Questions

- **PPSR-001 (RESOLVED — G-CODE-VERIFIED):** Which subscription plans should include PPSR by default? **Resolution:** every unarchived plan (`WHERE is_archived = false`), mirroring the [Phase 1 staff-management resolution at 0203:229-240](alembic/versions/2026_05_31_0900-0203_staff_phase1_schema.py#L229-L240). PPSR included with `ppsr_lookups_included=0` so admins still need to explicitly grant quota — but the line item appears on every active plan.
- **PPSR-002:** Cache TTL default of 5 minutes — confirm this is short enough for "ran a check 10 mins ago, still relevant" but long enough to prevent accidental double-billing on UI re-renders.
- **PPSR-003:** s241_purpose validation. CarJam returns a list of authorised purposes per account; should the Settings page show a dropdown sourced from CarJam, or just a free-text field? Free-text is simpler; dropdown requires a new CarJam endpoint call.
- **PPSR-004:** PDF export branding — should the exported PDF use the org's invoice header template, or a dedicated PPSR template? Recommend dedicated PPSR template so the disclaimer text ("Information sourced from PPSR via CarJam — not a substitute for independent legal advice") is clear.
- **PPSR-005:** Retention period for `ppsr_searches.response_encrypted`. PPSR data isn't subject to wage-record-style 7-year retention but lender / dealer recordkeeping varies. Default: indefinite retention; admin can purge via a "Forget this search" button (audit-logged). Confirm with ops.
- **PPSR-006 (G17 closure):** Telemetry — should we emit Prometheus metrics for `ppsr_search_total{result=fresh|cached|404|429}`, `ppsr_quota_exceeded_total`, `ppsr_carjam_latency_seconds` (histogram)? Recommend yes for ops visibility; instrumented via the existing `app/observability/metrics.py` helpers (mirrors how `carjam_lookup_seconds` is already tracked).
- **PPSR-007 (G50 closure):** Onboarding journey for orgs that toggle PPSR ON but admin hasn't granted quota — should the Setup Guide show a "Configure your PPSR plan" follow-up step linked to Global Admin → Subscription Plans? Recommend yes, mirroring the existing post-module-enable callout pattern.

## Verification Gates

Before merging, every box in `docs/future/staff-management-system.md` §12 (the pre-merge gate template) MUST be ticked plus:

- [ ] `module_registry` insert + `feature_flags` insert + subscription-plan update verified post-migration.
- [ ] `CarjamClient.lookup_ppsr` covers every option flag with a unit test.
- [ ] CHECK constraint on `ppsr_searches` enforces RLS at INSERT time.
- [ ] Quota counter increments exactly once per HTTP call (not on cache hit) — property test asserts.
- [ ] s241_purpose required-when-owner-flag-set guard returns 422.
- [ ] Audit `ppsr.search` rows do NOT contain decrypted owner / debtor details.
- [ ] E2E script `scripts/test_ppsr_module_e2e.py` exits 0.
- [ ] Browser test: type rego → result renders → cache hit on second click within 5 mins → force-refresh actually re-hits CarJam (Network tab confirms).
- [ ] Vehicle Profile shows PPSR card when module enabled; hidden when disabled.
- [ ] Version bump synced across the three package files; CHANGELOG entry under the new version heading.

## Gap-Closure Addendum (steering-driven, 2026-05-31)

Patches applied to close gaps surfaced during a sweep against every `.kiro/steering/*.md` doc:

| Gap | Closure |
|---|---|
| G3  | (deferred) Per-org "Test PPSR connection" button — tracked as nice-to-have; existing CarJam Test Connection covers the api_key. |
| G5  | History-endpoint filter spec made explicit in R6.1 (rego, match, user_id, date_from, date_to + non-admin force-filter). |
| G6  | Request-path trace added to design.md §1a (per implementation-completeness-checklist Rule 2). |
| G7  | Pydantic schema gate verified — `PpsrSearchResult` populates fields explicitly per `frontend-backend-contract-alignment.md` Rule 8; added e2e assert in R11.4. |
| G8  | Platform-admin path (`global_admin` has no `org_id`) — middleware fails open, router enforces explicit 403 (R1.6). |
| G10 | Per-org rate limit 10/min on `/api/v2/ppsr/search` with `Retry-After` (R5.6). |
| G13/G39 | `org_vehicle_id` + `global_vehicle_id` columns on `ppsr_searches` (R3.4); resolution algorithm in design §3.1a. |
| G17 | Metrics open question PPSR-006. |
| G18 | OWASP coverage expanded in R11.4 (A1 IDOR, A2 PII leakage, A3 injection, A5 misconfig, A8 audit). |
| G19 | Issue-tracker entries to be drafted in tasks F3 with full template. |
| G23 | Vehicle-link algorithm specified in design §4.2 + §6.5. |
| G24 | UPPER(rego) function index dropped — plain `rego` is sufficient because rego is normalised on insert (R3.5 note). |
| G25/G42 | Org template variables enumerated in design §4.3a. |
| G26 | Forget invalidation + cache-skip-for-forgotten in R4.4 + R6.4. |
| G27 | Redis in-flight lock to prevent concurrent CarJam calls billing the org twice (R4.6b). |
| G28/G49 | `carjam_not_configured` 422 + graceful defaults for missing optional fields (R4.6a). |
| G29 | 410 Gone for forgotten search detail/export (R6.2/R6.3). |
| G30 | `options_hash` column + cache lookup keyed on hash (R3.4 + R4.4). |
| G31 | Function name `envelope_encrypt` verified against `app/core/encryption.py:66` (R3.3). |
| G33/G45 | Audit table name `audit_log` (singular) — corrected throughout. |
| G34 | `Intl.NumberFormat` for NZD formatting documented in design §6.3 (G34 note). |
| G35 | Search button disabled when `included=0` with tooltip (design §6.2 G35 note). |
| G36/G37 | Detail-endpoint access rule simplified to `org_admin OR own search` (R6.2). |
| G38 | Module-gate response shape corrected to **HTTP 403** with `{detail, module}` per actual middleware (R1.5, R11.4). |
| G43 | Daily-reset task race-condition guard with `WHERE carjam_lookups_reset_at < (now() - interval '1 day')` (R5.3a). |
| G44 | Counter renamed `ppsr_money_owing_lookups_*` → `ppsr_hidden_plate_lookups_*` (R5.1, R5.2, R5.4). |
| G50 | Setup-Guide post-enable quota-grant prompt — open question PPSR-007. |
