# PPSR Module — Tasks

Each task is independently mergeable, has a `**Verify:**` line per `implementation-completeness-checklist.md` Rule 9, and references back to a requirement.

## Workstream A — Migrations

- [ ] **A1. Write Alembic migration `0207_ppsr_module.py`**
  - Creates `ppsr_searches` with RLS + tenant_isolation policy, CHECK constraint on `match` enum, all encrypted-payload columns typed `BYTEA`.
  - Includes the gap-closure columns: `options_hash text NOT NULL` (G30), `org_vehicle_id uuid REFERENCES org_vehicles(id) ON DELETE SET NULL` + `global_vehicle_id uuid REFERENCES global_vehicles(id) ON DELETE SET NULL` (G13/G39), `forgotten_at timestamptz` (G29).
  - `ALTER TABLE subscription_plans` ADD COLUMN: `ppsr_lookups_included int NOT NULL DEFAULT 0`, `ppsr_hidden_plate_lookups_included int NOT NULL DEFAULT 0` (G44 — renamed from `ppsr_money_owing_*`).
  - `ALTER TABLE organisations` ADD COLUMN: `ppsr_lookups_this_month int NOT NULL DEFAULT 0`, `ppsr_hidden_plate_lookups_this_month int NOT NULL DEFAULT 0` (G44).
  - Insert `module_registry` row for `'ppsr'` with `setup_question` + `setup_question_description` (idempotent `ON CONFLICT (slug) DO NOTHING`).
  - Insert mirror `feature_flags` row for key `'ppsr'`.
  - Update `subscription_plans.enabled_modules` JSONB to include `'ppsr'` for all non-archived plans (idempotent set-union).
  - Provide downgrade that drops the table, columns, module_registry row, feature_flags row.
  - **Refs:** R1, R3, R5.
  - **Verify:**
    1. `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app alembic upgrade head` runs cleanly (per database-migration-checklist §"Mandatory Steps").
    2. Verify CHECK constraint accepts each valid match value:
       ```bash
       docker compose exec postgres psql -U postgres -d workshoppro -c \
         "SELECT consrc FROM pg_constraint WHERE conname LIKE '%ppsr_searches%match%'"
       ```
    3. In psql:
       - `SELECT slug, setup_question FROM module_registry WHERE slug='ppsr'` → 1 row.
       - `SELECT key FROM feature_flags WHERE key='ppsr'` → 1 row.
       - `\d+ ppsr_searches` shows RLS enabled, all gap-closure columns present.
       - `\d+ organisations` shows the two new ppsr counter columns (hidden_plate, not money_owing).
       - `SELECT enabled_modules FROM subscription_plans WHERE NOT is_archived` — all rows include `'ppsr'`.

- [ ] **A2. Write Alembic migration `0208_ppsr_indexes.py`**
  - 4 indexes via `CREATE INDEX CONCURRENTLY ... IF NOT EXISTS` inside `op.get_context().autocommit_block()`. Mirrors canonical 0202 template.
  - Indexes per design §3.2: `idx_ppsr_searches_org_created`, `idx_ppsr_searches_org_rego_options_created` (cache lookup, G30), `idx_ppsr_searches_user`, `idx_ppsr_searches_org_vehicle` partial index (G13).
  - Downgrade drops via `DROP INDEX CONCURRENTLY IF EXISTS`.
  - **Refs:** R3, performance-and-resilience steering.
  - **Verify:** `SELECT indexname FROM pg_indexes WHERE tablename='ppsr_searches'` returns the 4 new indexes; `EXPLAIN SELECT * FROM ppsr_searches WHERE org_id=$1 ORDER BY created_at DESC LIMIT 25` shows index-only scan on `idx_ppsr_searches_org_created`; `EXPLAIN SELECT 1 FROM ppsr_searches WHERE org_id=$1 AND rego=$2 AND options_hash=$3 AND created_at >= now() - interval '5 min'` uses `idx_ppsr_searches_org_rego_options_created`.

## Workstream B — Backend integration extension

- [ ] **B1. Extend `app/integrations/carjam.py`**
  - Add the `CarjamPpsrResponse` dataclass per design §4.1.
  - Add `_parse_ppsr_response(rego, xml_text, requested_options)` parser that handles `idh`, `ioh`, `ico`, `ppsr`, `ppsr_details`, `money_owing`, `warnings`, `flood`, `charges` tags. On top-level `<error>`, raise `CarjamError(message)`.
  - Add `CarjamClient.lookup_ppsr(...)` method (signature per design §4.1). Calls `_check_carjam_rate_limit` first. Always sends `ppsr=1`, `charges=1`. Validates `s241_purpose` when owner flags set.
  - **Refs:** R2.
  - **Verify:** `pytest tests/unit/test_carjam_lookup_ppsr.py -v` covers:
    - happy path with `ppsr=1` only → returns CarjamPpsrResponse with `money_owing.match='N'`;
    - `owners=1` without `s241_purpose` → raises ValueError;
    - upstream `<error><message>Invalid key</message></error>` → raises CarjamError;
    - XML with `<not_found>true</not_found>` → `not_found=True`;
    - financing-statement parsing pulls out a 3-statement fixture correctly.

## Workstream C — Backend module `app/modules/ppsr/`

- [ ] **C1. `models.py`** — `PpsrSearch` ORM model matching the migration. `response_encrypted` typed `Mapped[bytes | None]` with `LargeBinary`. `options_json` typed `Mapped[dict]` with `JSONB`.
  - **Verify:** `docker compose exec app python -c "from app.modules.ppsr.models import PpsrSearch; print(PpsrSearch.__table__.columns.keys())"` lists every column.

- [ ] **C2. `schemas.py`** — Pydantic for:
  - `PpsrSearchOptions` (the input options).
  - `PpsrSearchRequest` (full POST body — wraps rego + options + force_refresh).
  - `PpsrSearchResult` (response wrapper with `cached` flag).
  - `PpsrSearchSummary` (row in history list — denormalised fields only).
  - `PpsrSearchListResponse = { items: list[PpsrSearchSummary], total: int }`.
  - `PpsrQuotaResponse = { used, included, money_owing_used, money_owing_included, resets_at }`.
  - All response models populate field-by-field — no `model_dump(by_alias=...)` shortcuts that could leak the encrypted blob.
  - **Verify:** `pytest tests/unit/test_ppsr_schemas.py` covers happy + round-trip cases; assert encrypted payload never serialises into a list-response payload.

- [ ] **C3. `service.py::PpsrService`** — full implementation per design §4.2.
  - `search()` — module gate, CarJam-not-configured gate (G28/G49 → `PpsrCarjamNotConfiguredError`), quota check, Redis in-flight lock (G27 — TTL 30s, wait 5s), owner-lookup gate, cache check (keyed on `options_hash` per G30; skip forgotten per G26), CarJam call, vehicle-link resolve (G23), persist (encrypted via `envelope_encrypt` — G31), increment quota (`ppsr_hidden_plate_lookups_*` rename per G44), audit (`audit_log` singular per G33/G45), return result. Wrap CarJam call in try/except that converts `CarjamNotFoundError` → `not_found=True` row stored AND audit, `CarjamRateLimitError` → 429 response with Retry-After header.
  - `_hash_options(options)` — sha256 of canonical-JSON (sort_keys=True) of `options.model_dump()` → hex digest. (G30)
  - `_find_recent_match` — Redis-cached `cache_ttl_minutes` lookup; query keyed on `(org_id, rego, options_hash)` with `response_encrypted IS NOT NULL` AND `forgotten_at IS NULL` filters (G26/G29/G30).
  - `_resolve_vehicle_link` — O(1) UPPER-match lookup against OrgVehicle then GlobalVehicle, no mutation (G23).
  - `_load_quota(org_id)` — returns `(used, included, hidden_plate_used, hidden_plate_included, resets_at)` (G44).
  - `list_searches(org_id, filters)` — paginated history with G5 filters (rego, match, user_id [admin only], date_from, date_to).
  - `get_search(search_id, current_user)` — ownership check (admin OR original searcher), decrypts payload, **returns HTTP 410 when `forgotten_at IS NOT NULL`** (G29).
  - `forget_search(search_id, current_user)` — admin-only; sets `response_encrypted=NULL`, `forgotten_at=now()`, invalidates Redis cache hint, writes audit `ppsr.forgotten` (G26/G29).
  - `link_vehicle(search_id, org_vehicle_id, current_user)` — updates `org_vehicle_id` column; audit `ppsr.search.linked` (G23).
  - All DB ops use `await db.refresh(obj)` after `db.flush()` (per project-overview.md MissingGreenlet note).
  - **Refs:** R4, R5, R6.
  - **Verify:** `pytest tests/unit/test_ppsr_service.py -v` covers:
    - first search → CarJam called, row inserted, quota incremented by 1;
    - second identical search within 5min → cached path, quota NOT incremented, audit row `ppsr.search.cached` written;
    - second search with re-ordered options JSON dict → still cache HIT because of `options_hash` keying (G30);
    - force_refresh → CarJam re-called, quota incremented;
    - 11th search when included=10 → `PpsrQuotaExceededError`;
    - owner-lookup without s241 config → `PpsrS241PurposeRequiredError`;
    - owner-lookup with s241 config but blank purpose param → defaults to `s241_purpose_default`;
    - CarJam config missing entirely → `PpsrCarjamNotConfiguredError` (G28/G49);
    - admin can view any search detail; non-admin can view only their own; 403 otherwise;
    - forget wipes payload but keeps summary row + audit; subsequent GET detail returns 410 with `forgotten_at` (G29);
    - cache lookup skips a forgotten search even within TTL (G26);
    - hidden-plate search increments `ppsr_hidden_plate_lookups_this_month` (G44);
    - concurrent search (two coroutines for same rego/options) → only one CarJam call due to Redis lock (G27).

- [ ] **C4. `pdf.py`** — Jinja template `app/modules/ppsr/templates/report.html` + `report.css`. `render_pdf(search, decrypted)` wraps WeasyPrint in `await asyncio.to_thread(...)`. Template includes:
  - Org logo, name, address from `org_settings`.
  - Searcher name + email.
  - Search timestamp.
  - Rego + basic vehicle summary.
  - Money-owing banner (CSS-coloured by match value).
  - Financing-statement table (when statements present).
  - Warnings rows.
  - Ownership history table (when present + s241 was provided).
  - Footer: standard PPSR disclaimer + page X of N.
  - **Refs:** R6.3.
  - **Verify:** `pytest tests/integration/test_ppsr_pdf.py`:
    - render a sample PPSR search → parse PDF text → assert all sections present (rego, match-description, statement count, disclaimer footer text).
    - When `money_owing.match='Y'`, assert the banner colour/style emits "Money Owing — Match: Yes" string.

- [ ] **C5. `router.py`** — all endpoints from design §5. Every endpoint:
  - Behind `RequireAuth`.
  - Behind `ModuleService.is_enabled(org_id, 'ppsr')` (decorator or inline check).
  - **Global-admin gate (G8):** every endpoint raises `HTTPException(403, "ppsr_requires_org_context")` when `current_user.org_id is None`.
  - List responses use `{ items, total }`.
  - Pagination via `offset` + `limit` (default 25, max 100).
  - Detail + export endpoints enforce ownership (admin OR original searcher). Return **HTTP 410** with `{ detail: "search_forgotten", forgotten_at }` when `forgotten_at IS NOT NULL` (G29).
  - `POST /search` is rate-limited per-org via the existing rate-limit middleware: **10 requests/min** with `Retry-After` header on 429 (G10).
  - `POST /search/:id/link-vehicle` — new endpoint, body `{ org_vehicle_id }`, audit `ppsr.search.linked` (G23).
  - **Pydantic schema gate verification:** every service-dict field has a matching Pydantic response field (per frontend-backend-contract-alignment Rule 8). Use explicit `PpsrSearchResult(**)` constructor; do NOT rely on `model_dump(by_alias=...)` shortcuts that could leak the encrypted blob.
  - **Verify:** browser test — open `/ppsr/search`, type rego, search → result renders; check Network tab for response shape; second click within 5min → `cached: true` in response; force-refresh → fresh call. Test forgotten path: admin invokes forget → reload detail → see "(payload forgotten)" state.

- [ ] **C6. Register router in `app/main.py`**. Add `/api/v2/ppsr` entry to `app/middleware/modules.py::MODULE_ENDPOINT_MAP` so the module-gate middleware knows to refuse when disabled. (Single entry; the `_resolve_module` helper matches by prefix.)
  - **Verify:** disable the module on a test org → POST `/api/v2/ppsr/search` returns **HTTP 403** with body `{ "detail": "Module 'ppsr' is not enabled for your organisation.", "module": "ppsr" }` per the actual middleware at `app/middleware/modules.py:117-126` (G38 — corrected from earlier draft that said 404). Re-enable → 200.

- [ ] **C7. Extend CarJam admin config schema maps** — [app/modules/admin/service.py:1734-1742](app/modules/admin/service.py#L1734-L1742) (G-CODE-11 — two separate dicts, not one):
  - Extend `_SAFE_FIELDS["carjam"]` (line 1734) to: `["endpoint_url", "per_lookup_cost_nzd", "abcd_per_lookup_cost_nzd", "global_rate_limit_per_minute", "ppsr_cache_ttl_minutes", "ppsr_owner_lookups_enabled"]` — `ppsr_cache_ttl_minutes` (int) and `ppsr_owner_lookups_enabled` (bool) are non-secret config and round-trip plainly via `get_integration_config`.
  - Extend `_MASKED_FIELDS["carjam"]` (line 1742) to: `["api_key", "s241_purpose_default"]` — `s241_purpose_default` is treated like a secret for GUI consistency (returned as `s241_purpose_default_last4`).
  - Update the CarJam config GET/PATCH handlers in `app/modules/admin/router.py` to accept the three new fields. Mask-pattern detection per `security-hardening-checklist.md §2` already filters incoming values matching `^\*+$|^.{0,4}\*{4,}$` for masked fields, so `s241_purpose_default` is protected automatically once added to `_MASKED_FIELDS`.
  - **Refs:** R7.
  - **Verify:** PATCH `/api/v2/admin/integrations/carjam` with `s241_purpose_default='Selling vehicle'`, `ppsr_cache_ttl_minutes=10`, `ppsr_owner_lookups_enabled=true` → GET returns `s241_purpose_default_last4='hicle'`, `ppsr_cache_ttl_minutes=10`, `ppsr_owner_lookups_enabled=true`. PATCH again with `s241_purpose_default='****'` → DB row unchanged (mask-detection skipped the update). Verify decrypted full config still has the original `s241_purpose_default` value by direct psql + `envelope_decrypt_str`.

- [ ] **C8. Quota-reset extension** — G-CODE-8: the reset actually fires inside [app/tasks/subscriptions.py:196 and :273](app/tasks/subscriptions.py#L196), NOT `app/tasks/scheduled.py`. The reset happens per-org at the billing-cycle boundary inside `process_due_billings` when `carjam_overage_count > 0`. Two parallel reset lines must be added next to each existing `org.carjam_lookups_this_month = 0`:
  ```python
  if sms_overage_count > 0:
      org.sms_sent_this_month = 0
  if carjam_overage_count > 0:
      org.carjam_lookups_this_month = 0
  # PPSR Phase 1 — counter resets fire at the same billing-cycle boundary as carjam counters.
  if ppsr_overage_count > 0:
      org.ppsr_lookups_this_month = 0
      org.ppsr_hidden_plate_lookups_this_month = 0
  ```
  Also add a `ppsr_overage_count` computation matching the existing `carjam_overage_count` pattern (line ~150 of subscriptions.py), so the counter resets aren't blindly fired every cycle.
  - **Verify:** mock `process_due_billings` with `ppsr_lookups_this_month=120, ppsr_lookups_included=100` → org gets billed for 20 PPSR overage AND counters reset to 0. Mock with `ppsr_lookups_this_month=50, included=100` → counters NOT reset (under quota).

- [ ] **C9. Per-org rate limit on `POST /api/v2/ppsr/search`** (G10 + G-CODE-15) — `app/middleware/rate_limit.py` currently hard-codes prefix-mapped limits (`_PUBLIC_STAFF_ROSTER_PATH_PREFIX = 30`, `_PAYMENT_PAGE_PREFIX = 20`, etc.) — there is NO config-driven dispatcher. Add:
  ```python
  # PPSR search — 10 req/min per org (Phase 1 G10).
  # Cache hits in the service don't reach this middleware because the
  # service short-circuits before any HTTP call; only fresh searches
  # consume budget.
  _PPSR_SEARCH_PATH = "/api/v2/ppsr/search"
  _PPSR_SEARCH_RATE_LIMIT = 10
  ```
  Insert dispatch into the per-org check section of the middleware (search for `_PUBLIC_STAFF_ROSTER_PATH_PREFIX` and mirror the pattern). On 429, return `Retry-After` header (seconds).
  - **Verify:** burst-test 11 POSTs in 1 second from same org → 11th returns HTTP 429 with `Retry-After: 60`; counter is per-org (org B can still search while org A is throttled).

## Workstream D — Frontend

- [ ] **D1. `frontend/src/api/ppsr.ts`** — typed client. Each method:
  - Uses typed generic `apiClient.post<PpsrSearchResult>(...)` — no `as any`.
  - Returns the response payload directly.
  - **Verify:** `pnpm vitest run frontend/src/api/__tests__/ppsr.test.ts` covers happy + 402 + 422 paths.

- [ ] **D2. `frontend/src/pages/ppsr/PPSRSearchPage.tsx`** — primary surface per design §6.1 + 6.2. Module-gated wrapper at top renders `FeatureNotAvailablePage` when disabled.
  - Quota strip refresh on mount + after every search.
  - Form fields with the documented gating (current-owner / ownership-history disabled until config is set).
  - AbortController on every API call.
  - All `set*(res.data?.field ?? fallback)` per safe-api-consumption.
  - **Refs:** R8.
  - **Verify:** browser test — open `/ppsr/search` → fill rego → search → result renders → check Network panel for `cached: false`; click search again within 5 min → `cached: true` chip appears; toggle force-refresh → fresh call.

- [ ] **D3. `frontend/src/pages/ppsr/components/PpsrResultPanel.tsx`** — structured result renderer per design §6.3. Traffic-light banner, financing-statements table, warnings rows, ownership table (gated), charges footer, actions row (Export PDF / Save / New).
  - **Verify:** Storybook story or Vitest snapshot for each match level + each combination of optional sections.

- [ ] **D4. `frontend/src/pages/ppsr/components/PpsrHistoryTable.tsx`** — paginated history per design §6.4. Row click opens `PpsrDetailDrawer`. Each row → GET `/searches/:id` lazy-loaded.
  - **Verify:** browser test — pagination works; row click loads detail; force-refresh repopulates.

- [ ] **D5. `frontend/src/pages/vehicles/components/PpsrCard.tsx` + integration into VehicleProfile**
  - `PpsrCard` lazy-loaded inside `<ModuleGate module="ppsr">` (G-CODE-3 — prop is `module`, not `moduleSlug`).
  - Placement in `VehicleProfile.tsx`: between WOF/COF cards and Notes section.
  - Empty state when no prior search; latest-match summary + "Re-run check" button when prior exists.
  - **Refs:** R9.
  - **Verify:** browser test — open a vehicle profile with no prior PPSR search → "Run PPSR check now" CTA renders. Click → navigates to `/ppsr/search?rego=<rego>` with rego pre-filled. Disable the module → card disappears.

- [ ] **D6. `frontend/src/pages/admin/Integrations.tsx`** extension (G-CODE-10 — actual page path; `pages/settings/integrations/CarJamConfigPage.tsx` does NOT exist):
  - Append three entries to the `INTEGRATION_FIELDS.carjam` array at line 45:
    ```ts
    { key: 's241_purpose_default', label: 's241 purpose code', type: 'password', placeholder: '••••••••', backendKey: 's241_purpose_default_last4', helperText: 'Source from CarJam member dashboard → s241 section. Required for owner lookups.' },
    { key: 'ppsr_cache_ttl_minutes', label: 'PPSR cache TTL (minutes)', type: 'number', placeholder: '5', helperText: 'How long to serve cached PPSR results before re-hitting CarJam (default 5).' },
    { key: 'ppsr_owner_lookups_enabled', label: 'Enable owner / ownership-history lookups', type: 'checkbox', helperText: 'Tick this AND set s241 purpose code before owner lookups will work.' },
    ```
  - If the existing component doesn't support `type: 'checkbox'`, add a simple checkbox renderer that maps `'true'/'false'` → boolean (mechanical extension).
  - Existing mask-pattern detection automatically applies to `s241_purpose_default` once the backend `_MASKED_FIELDS["carjam"]` list includes it (per C7).
  - **Refs:** R7.
  - **Verify:** browser test — fill the PPSR fields, save → GET returns `s241_purpose_default_last4` (masked), `ppsr_cache_ttl_minutes` (number), `ppsr_owner_lookups_enabled` (bool); reload page → values populate correctly.

- [ ] **D7. Sidebar registration** — [frontend/src/layouts/OrgLayout.tsx:43-85](frontend/src/layouts/OrgLayout.tsx#L43-L85) is a flat `navItems` array (G-CODE-9 — no nested sections). Insert a single entry immediately after the Vehicles row (line 46):
  ```ts
  { to: '/ppsr/search', label: 'PPSR Check', icon: PpsrIcon, module: 'ppsr', flagKey: 'ppsr' },
  ```
  Create the `PpsrIcon` SVG component at `frontend/src/components/icons/PpsrIcon.tsx` (mirror the inline SVG pattern of `VehiclesIcon` already imported into OrgLayout). No tradeFamily filter — PPSR is universal.
  The existing filter at line 161 (`isEnabled(item.module)`) already hides the item when the module is off — no extra wiring needed.
  - **Verify:** module enabled → sidebar shows "PPSR Check" right after Vehicles for every trade family. Module disabled → no sidebar item, navigating directly to `/ppsr/search` → `FeatureNotAvailable`.

- [ ] **D8. Route registration** — `frontend/src/App.tsx`, matching the [VehicleProfile pattern at line 414](frontend/src/App.tsx#L414):
  ```tsx
  const PPSRSearchPage = lazy(() => import('@/pages/ppsr/PPSRSearchPage'))
  // inside <Routes>:
  <Route path="/ppsr/search" element={<SafePage name="ppsr-search"><ModuleRoute moduleSlug="ppsr"><PPSRSearchPage/></ModuleRoute></SafePage>} />
  ```
  Wrap in `SafePage` (error boundary) and `ModuleRoute` per the existing convention.
  - **Verify:** browser navigates to `/ppsr/search` → page loads; module disabled → `FeatureNotAvailable` renders; throwing a deliberate error inside `PPSRSearchPage` → `SafePage` captures it instead of white-screening.

- [ ] **D9. Subscription Plans admin form extension** — actual file at `frontend/src/pages/admin/SubscriptionPlans.tsx:1349` (G-CODE-12). Add two numeric inputs mirroring the `carjam_lookups_included` pattern at line 493:
  - `ppsr_lookups_included`
  - `ppsr_hidden_plate_lookups_included` (G44 — renamed from `ppsr_money_owing_lookups_included`)
  Each rendered as `<Input type="checkbox" checked={form.field > 0} onChange={e => set('field', e.target.checked ? 100 : 0)} />` followed by a numeric input shown when checked (mirror lines 493-509 verbatim, two more times).
  Also add to the table column list at line 1527 so the value is visible on the plan listing.
  - **Verify:** browser test — set both to 50, save → GET `/api/v2/admin/subscription-plans/:id` returns the values; org's `/ppsr/quota` reflects the new ceiling.

- [ ] **D10. Frontend rebuild step** — after every `.tsx`/`.ts` change in this workstream, run the manual build step per database-migration-checklist.md:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vite build
  ```
  The watch-build may not reliably detect changes on bind-mounted volumes.
  - **Verify:** `docker logs invoicing-frontend-1 --tail 20` shows the new bundle hash; hard refresh in the browser picks up new chunks. (G2 closure.)

## Workstream E — Tests

- [ ] **E1. Unit-test files**:
  - `tests/unit/test_carjam_lookup_ppsr.py` — CarJam client extension.
  - `tests/unit/test_ppsr_service.py` — service-layer logic.
  - `tests/unit/test_ppsr_quota.py` — quota increment + reset behaviour.
  - `tests/unit/test_ppsr_schemas.py` — Pydantic serialisation (assert encrypted payload never escapes via list endpoints).
  - **Verify:** `pytest tests/unit/ -k 'ppsr or carjam_lookup_ppsr' -v` → all green.

- [ ] **E2. Integration test** `tests/integration/test_ppsr_pdf.py` — render a sample PPSR search → parse PDF text → assert disclaimer + all sections present.

- [ ] **E3. Property test** `tests/property/test_ppsr_invariants.py` — Hypothesis:
  - For any sequence of (search, cache-hit, force-refresh) events, `quota_used == count_of_carjam_calls` (cache hits don't increment).
  - For any forget-then-fetch sequence, the detail endpoint returns 410.
  - For any reordered options-JSON, `options_hash` is the same → cache hits land (G30).

- [ ] **E4. E2E** `scripts/test_ppsr_module_e2e.py` per R11 + R11.4 (OWASP coverage).
  - Login as org_admin → enable module → configure s241_purpose_default → POST search against test CarJam endpoint → assert response shape → second call → cached → verify quota counter = 1 → admin can fetch detail → non-admin gets 403 → export PDF (content-type=application/pdf) → set included=1 → run two searches → second returns 402.
  - **OWASP A1 IDOR (G18):** as org_B user, try `GET /api/v2/ppsr/searches/<org_A_search_id>` → assert 403 or 404.
  - **OWASP A2 PII leakage (G18):** assert list-endpoint raw response does NOT contain decrypted owner/debtor strings.
  - **OWASP A3 injection (G18):** POST search with rego `"'; DROP TABLE ppsr_searches; --"` → assert 422.
  - **OWASP A5 misconfig (G18):** corrupt encrypted blob → GET detail → assert response has no stack trace text.
  - **OWASP A8 audit (G18):** for each search/cache/export/forget, assert exactly one matching row in `audit_log` (singular table name per G33/G45); assert `after_value` JSONB contains only summary fields.
  - **Module-gate response shape (G38):** disable module → POST `/ppsr/search` → assert HTTP **403** with `{ detail, module: "ppsr" }`.
  - **Global-admin gate (G8):** as global_admin (no org_id), POST `/ppsr/search` → assert 403 `ppsr_requires_org_context`.
  - **Concurrent calls (G27):** spawn 2 coroutines both POSTing the same rego in parallel → assert only 1 fresh `ppsr_searches` row was created within 1 second (the second got the lock-wait cached result).
  - **CarJam-not-configured (G28/G49):** with no `integration_configs[name='carjam']` row, POST search → assert 422 `carjam_not_configured`.
  - **Rate limit (G10):** burst 11 searches/sec → assert 11th returns 429 with `Retry-After` header.
  - **Forgotten 410 (G29):** admin forgets a search → GET detail → assert 410 + `forgotten_at` field.
  - Cleanup `TEST_E2E_` rows in `finally`.
  - **Verify:** `docker exec invoicing-app-1 python scripts/test_ppsr_module_e2e.py` exits 0 with "passed: N, failed: 0".

## Workstream F — Versioning + docs

- [ ] **F1. Bump versions** across `pyproject.toml`, `frontend/package.json`, `mobile/package.json` — MINOR bump.
  - **Verify:** `git grep '<old version>'` after change returns only CHANGELOG history.

- [ ] **F2. Update `CHANGELOG.md`** — new entry listing: PPSR module, search page, quota tracking, vehicle-profile embed, CarJam config extension, PDF export, audit + retention.

- [ ] **F3. Allocate `PPSR-001`..`PPSR-007` placeholder IDs in `docs/ISSUE_TRACKER.md`** — one entry per open question in requirements.md §Open Questions, using the `issue-tracking-workflow.md` template:
  - PPSR-001: subscription-plan default quota policy — "Awaiting product decision before quota launch".
  - PPSR-002: cache TTL default validation — "Awaiting field validation after 1 month of usage".
  - PPSR-003: s241_purpose dropdown vs free-text — "Awaiting CarJam-API capability investigation".
  - PPSR-004: PDF branding template — "Awaiting design sign-off; default dedicated PPSR template".
  - PPSR-005: retention period for forgotten search rows — "Awaiting ops decision; default indefinite + admin-purge".
  - PPSR-006 (G17): telemetry / Prometheus metrics scope — "Awaiting observability priority".
  - PPSR-007 (G50): Setup-Guide post-enable quota-grant prompt — "Awaiting UX review".
  - Each entry follows the template: Date, Severity (`low` for open questions), Status (`open`), Reporter (`developer`), Symptoms, Root Cause (`design open question`), Fix Applied (`pending`), Files Changed (`pending`).

## Pre-merge gate (per source plan §12)

Tick before opening the merge PR:

**Code completeness**
- [ ] `alembic upgrade head` runs cleanly on dev.
- [ ] All index migrations use `CREATE INDEX CONCURRENTLY`.
- [ ] Zero `op.create_index(...)` calls.
- [ ] `ppsr_searches` has RLS + tenant_isolation policy.
- [ ] Module-registry insert includes `setup_question` + `setup_question_description`.
- [ ] `feature_flags` row added alongside.
- [ ] `subscription_plans.enabled_modules` updated for all non-archived plans.

**API contract**
- [ ] Every new service-dict field has a matching Pydantic schema field.
- [ ] All list endpoints return `{ items, total }`.
- [ ] No new env vars introduced.
- [ ] All third-party API calls route through the existing `CarjamClient` — no direct httpx calls to CarJam from the new module.
- [ ] `audit_log` (singular, per `app/core/audit.py:79`) entries written for every state change: `ppsr.search`, `ppsr.search.cached`, `ppsr.exported`, `ppsr.forgotten`, `ppsr.search.linked`, `ppsr.config_updated`, `ppsr.quota_exceeded`. (G33/G45 closure.)

**Frontend**
- [ ] Every API call uses `?.` + `?? []` / `?? 0`.
- [ ] No `as any`.
- [ ] Every `useEffect` with API call has AbortController cleanup.
- [ ] Empty / loading / error states all implemented.
- [ ] Module-disabled fallback (`FeatureNotAvailablePage`) renders correctly.
- [ ] Vehicle Profile embed is `ModuleGate`-wrapped.

**Testing**
- [ ] E2E script ships with prefix `TEST_E2E_` + cleanup.
- [ ] Property tests on quota invariants.
- [ ] Integration test on PDF rendering.
- [ ] Unit tests for every new service method.

**Security**
- [ ] `response_encrypted` is envelope-encrypted via `envelope_encrypt`.
- [ ] Detail endpoint enforces ownership (admin OR original searcher).
- [ ] Audit-log rows for `ppsr.search` redacted to summary fields only (no decrypted owner / debtor details).
- [ ] Forget endpoint wipes payload but keeps audit row.
- [ ] s241_purpose required when owner flags set — 422 on missing.
- [ ] Owner-lookup endpoint gated by org-level `ppsr_owner_lookups_enabled` toggle in CarJam config.

**Quota + cost**
- [ ] Quota increments exactly once per CarJam HTTP call (cache hit does NOT increment) — property test asserts.
- [ ] Daily reset task includes the two new PPSR counters.
- [ ] 402 returned with `Retry-After`-style body when quota exceeded (`{ detail, used, included }`).

**Versioning**
- [ ] `pyproject.toml` + `frontend/package.json` + `mobile/package.json` all bumped in sync.
- [ ] `CHANGELOG.md` updated.

**Browser test**
- [ ] Search page loads → form renders → search returns structured result → cache chip appears on repeat.
- [ ] Vehicle Profile embed shows latest match and "Re-run" CTA.
- [ ] Quota strip updates after each fresh search.
- [ ] PDF export downloads a file with correct content-type.
- [ ] Module-disabled state renders `FeatureNotAvailablePage`.
- [ ] Settings → Integrations → CarJam shows the new PPSR section + saves correctly.

The module is NOT done until every box is ticked. Any item that can't be ticked goes into `gap-analysis.md` with the reason.

## Code-Verified Addendum (real-code audit 2026-05-31)

Every backend / frontend file path and import line referenced in this tasks list was verified against the actual repo. The full evidence list lives in `design.md` §13 ("Verified-against-code addendum"). Key tasks where a path / API / column name was corrected after the audit:

- **A1** — Migration now uses **actual** `feature_flags` column shape (no `default_enabled`, no `scope`); mirrors 0203 staff-phase1.
- **A2** — Migration filename `0208_ppsr_indexes.py` (head was 0206 at audit time).
- **C3** — Service uses `ModuleService.is_enabled` + manual raise (no `require_enabled` helper); credentials loaded via raw `IntegrationConfig` + `envelope_decrypt_str` (not `get_integration_config`, which only returns masked fields).
- **C5** — Rate-limit tuple unpack `(allowed, retry_after) = await _check_carjam_rate_limit(...)`.
- **C6** — `MODULE_ENDPOINT_MAP` entry is single prefix `"/api/v2/ppsr": "ppsr"`; module-disabled response is **HTTP 403** with `{detail, module}`, not 404.
- **C7** — Two separate dicts to extend: `_SAFE_FIELDS["carjam"]` and `_MASKED_FIELDS["carjam"]` at admin/service.py:1734 and :1742.
- **C8** — Reset task lives in `app/tasks/subscriptions.py` (NOT `scheduled.py`); reset is overage-conditional, not unconditional monthly.
- **C9** — New task — per-org PPSR rate limit constant added to `app/middleware/rate_limit.py`.
- **D5** — `PpsrCard` uses `<ModuleGate module="ppsr">` (NOT `moduleSlug`).
- **D6** — Frontend CarJam config page lives at `frontend/src/pages/admin/Integrations.tsx`, extending `INTEGRATION_FIELDS.carjam` array.
- **D7** — Sidebar is flat `navItems` array; single entry insert; no nested sections.
- **D8** — Route wrapped in `SafePage` + `ModuleRoute` per existing pattern.
- **D9** — Subscription Plans page is `frontend/src/pages/admin/SubscriptionPlans.tsx:1349` (NOT `SubscriptionPlanForm.tsx`).

## Gap-Closure Addendum (steering sweep 2026-05-31)

Tasks-side changes summary (full gap table in `requirements.md`):

- **A1**: schema columns `options_hash`, `org_vehicle_id`, `global_vehicle_id`, `forgotten_at` added (G13/G29/G30/G39); counter columns renamed `ppsr_hidden_plate_lookups_*` (G44); CHECK-constraint verification step added (database-migration-checklist).
- **A2**: index pack rewritten — `idx_ppsr_searches_org_rego_options_created` keyed on `options_hash` (G24/G30); partial index on `org_vehicle_id` (G13).
- **C3**: service-layer test coverage expanded — `options_hash` cache key (G30), forgotten-row skip (G26), concurrent-call lock (G27), CarJam-not-configured (G28/G49), hidden-plate counter (G44).
- **C5**: router endpoints — global-admin gate (G8), 410 Gone on forgotten (G29), per-org rate limit (G10), link-vehicle endpoint (G23), explicit Pydantic-schema gate verification (frontend-backend-contract-alignment Rule 8).
- **C6**: module-disabled response shape corrected to **403** with `{detail, module}` per actual middleware (G38).
- **C8**: race-condition guard `WHERE carjam_lookups_reset_at < now() - interval '1 day'` (G43).
- **D9**: subscription-plan form input renamed `ppsr_hidden_plate_lookups_included` (G44).
- **D10**: new — manual frontend rebuild step per database-migration-checklist (G2).
- **E4**: e2e expanded with OWASP A1/A2/A3/A5/A8 coverage (G18), module-gate 403 shape (G38), global-admin 403 (G8), concurrent-call lock (G27), CarJam-not-configured 422 (G28/G49), rate limit 429 (G10), forgotten 410 (G29).
- **F3**: ISSUE_TRACKER entries expanded to PPSR-001..007 with `issue-tracking-workflow.md` template (G19); added PPSR-006 telemetry (G17) and PPSR-007 onboarding (G50).
- **Pre-merge gate**: `audit_log` (singular) corrected per actual table name (G33/G45).
