# PPSR Module — Design

## 1a. Request path trace (G6 closure)

Per `implementation-completeness-checklist.md` Rule 2, every layer is mapped before implementation:

```
Browser → Nginx (proxy /api/v2/*)
       → CSRFMiddleware            ← exempt? POST has CSRF token; verified via existing pattern
       → AuthMiddleware            ← /api/v2/ppsr/* requires JWT (not in PUBLIC_PREFIXES)
       → RateLimitMiddleware       ← per-org 10/min on /search (per R5.6)
       → ModuleMiddleware          ← MODULE_ENDPOINT_MAP entry `/api/v2/ppsr` → `ppsr`; 403 if disabled
       → Router (app/modules/ppsr/router.py)
       → require_role / current_user dependency
       → app.current_org_id GUC set by tenant dependency (RLS gate)
       → PpsrService.search()
           → module gate (defence-in-depth)
           → quota check (SELECT subscription_plans + organisations)
           → CarJam config check (G28/G49 — 422 if not configured)
           → Redis in-flight lock (G27 — ppsr:lock:{org_id}:{rego}:{options_hash}, TTL 30s)
           → cache lookup (G30 — keyed on options_hash; G26 — skip forgotten)
           → CarjamClient.lookup_ppsr() → CarJam API
           → envelope_encrypt(json)
           → INSERT INTO ppsr_searches (RLS-tagged via current_setting)
           → UPDATE organisations SET ppsr_lookups_this_month = + 1 (atomic, same txn)
           → write_audit_log(action='ppsr.search', ...) → audit_log (singular per code)
           → release Redis lock
       → Pydantic PpsrSearchResult.model_dump() → JSON response
       → CSP / security headers added on response
```

No layer is skipped or guessed at — each one matches existing code:

| Layer | Existing reference |
|---|---|
| ModuleMiddleware | `app/middleware/modules.py:79-128` (returns 403, not 404, with `{detail, module}` — corrected from earlier draft) |
| RateLimit | `app/middleware/rate_limit.py` (existing decorator-driven pattern) |
| envelope_encrypt | `app/core/encryption.py:66` (function name is `envelope_encrypt`, not `envelope_encrypt_str`) |
| write_audit_log | `app/core/audit.py:35` writes to table `audit_log` (singular) per `app/core/audit.py:79` |
| Redis lock | follow existing pattern from `app/integrations/carjam.py::_check_carjam_rate_limit` (Redis SET NX EX) |

## 1. Architecture overview

PPSR is a thin module that reuses the existing CarJam infrastructure and adds three pieces:

1. **One extension method** on the existing `CarjamClient` (`lookup_ppsr`) — same client, same credentials, same rate-limit, new query-string parameters.
2. **Two new tables** — `ppsr_searches` (the audit log + cache) and a small column-extension on `subscription_plans` + `organisations` for the separate quota.
3. **One new module surface** in `app/modules/ppsr/` with router + service + schemas + tests, plus a frontend page + a Vehicle-Profile embed.

Backend touches:

- `alembic/versions/0207_ppsr_module.py` (schema + module-registry inserts).
- `alembic/versions/0208_ppsr_indexes.py` (CONCURRENTLY pack).
- `app/integrations/carjam.py` — extend with `lookup_ppsr(...)` method + `CarjamPpsrResponse` dataclass + XML parser additions (parse `ppsr`, `ppsr_details`, `money_owing`, `ioh`, `ico`, `warnings`, `flood`, `charges`). The existing `_parse_vehicle_response` doesn't need to change — `lookup_ppsr` builds its own response dataclass.
- `app/modules/ppsr/{__init__,models,schemas,service,router,pdf}.py` — new module.
- `app/modules/admin/service.py:1742` — extend the `"carjam": ["api_key"]` map to include `s241_purpose_default`, `ppsr_cache_ttl_minutes`, `ppsr_owner_lookups_enabled`.
- `app/modules/admin/router.py` — extend the CarJam config GET/PATCH to cover the new fields.
- `app/main.py` — include the new router; add `/api/v2/ppsr/*` path entries to `app/middleware/modules.py::MODULE_ENDPOINT_MAP` so the module middleware knows to gate them.

Frontend touches:

- `frontend/src/pages/ppsr/PPSRSearchPage.tsx` — primary surface.
- `frontend/src/pages/ppsr/components/PpsrResultPanel.tsx` — the structured result renderer.
- `frontend/src/pages/ppsr/components/PpsrHistoryTable.tsx` — recent searches.
- `frontend/src/pages/vehicles/VehicleProfile.tsx` — small additive change: render the new `PpsrCard.tsx` when module enabled.
- `frontend/src/pages/vehicles/components/PpsrCard.tsx` — embedded quick-check card.
- `frontend/src/pages/admin/Integrations.tsx` (G-CODE-10 — actual existing path; `frontend/src/pages/settings/integrations/CarJamConfigPage.tsx` does NOT exist) — extend the `INTEGRATION_FIELDS.carjam` field-def array at line 45 with three new entries (`s241_purpose_default`, `ppsr_cache_ttl_minutes`, `ppsr_owner_lookups_enabled`).
- `frontend/src/api/ppsr.ts` — typed client.
- `frontend/src/router/AppRoutes.tsx` (or `App.tsx`) — lazy-load the new page + sidebar entry.

## 2. Navigation & Access

- **Route:** `/ppsr/search` registered in `App.tsx`, lazy-loaded. Pattern mirrors [App.tsx:414](frontend/src/App.tsx#L414):
  ```tsx
  const PPSRSearchPage = lazy(() => import('@/pages/ppsr/PPSRSearchPage'))
  // inside <Routes>:
  <Route path="/ppsr/search" element={<SafePage name="ppsr-search"><ModuleRoute moduleSlug="ppsr"><PPSRSearchPage/></ModuleRoute></SafePage>} />
  ```
- **Route guard:** existing `RequireAuth` is applied globally by `OrgLayout` — no per-route guard needed. The `ModuleRoute moduleSlug="ppsr"` wrapper renders `FeatureNotAvailable` (existing component at [frontend/src/pages/common/FeatureNotAvailable.tsx](frontend/src/pages/common/FeatureNotAvailable.tsx)) when the module is disabled.
- **Sidebar (G-CODE-9):** the sidebar is a **flat `navItems` array** at [frontend/src/layouts/OrgLayout.tsx:43-85](frontend/src/layouts/OrgLayout.tsx#L43-L85) — there are no nested "Vehicles" or "Tools" sections in the existing layout. Add a single entry positioned immediately after the existing Vehicles entry (line 46):
  ```ts
  { to: '/ppsr/search', label: 'PPSR Check', icon: PpsrIcon, module: 'ppsr', flagKey: 'ppsr' },
  ```
  No `tradeFamily` filter — PPSR is universal. The existing filter logic at line 161 already hides items when `useModules().isEnabled(item.module)` is false, so no extra wiring is needed. A new `PpsrIcon` SVG component lives at `frontend/src/components/icons/PpsrIcon.tsx` (mirrors the existing icon pattern).
- **CarJam admin sub-section:** the existing Integrations admin page at [frontend/src/pages/admin/Integrations.tsx](frontend/src/pages/admin/Integrations.tsx) already renders CarJam fields generically from `INTEGRATION_FIELDS.carjam`. PPSR adds three field-def entries to that array (no new sub-section component required; the page renders new fields automatically).
- **Vehicle Profile embed:** [frontend/src/pages/vehicles/VehicleProfile.tsx](frontend/src/pages/vehicles/VehicleProfile.tsx) renders the new `<PpsrCard rego={vehicle.rego} />` between WOF/COF and Notes; the card internally wraps itself in `<ModuleGate module="ppsr">` (G-CODE-3 — actual prop name is `module`, not `moduleSlug`, per [ModuleGate.tsx:13](frontend/src/components/common/ModuleGate.tsx#L13)).
- **Module gate (two-layer):** `ModuleRoute` at the route boundary returns `FeatureNotAvailable` for disabled module; `ModuleGate` inside the Vehicle Profile renders nothing when disabled. Both are existing components.

## 3. Data Model

### 3.1 Migration `0207_ppsr_module.py`

```sql
-- Audit log + cache. RLS enforced.
CREATE TABLE IF NOT EXISTS ppsr_searches (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id            uuid NOT NULL REFERENCES users(id),
    rego               text NOT NULL,
    options_json       jsonb NOT NULL,
    options_hash       text NOT NULL,                                           -- G30: sha256(canonical_json(options))
    org_vehicle_id     uuid REFERENCES org_vehicles(id) ON DELETE SET NULL,    -- G13/G39: link to existing vehicle row
    global_vehicle_id  uuid REFERENCES global_vehicles(id) ON DELETE SET NULL, -- G13/G39
    match              text,
    match_description  text,
    statement_count    int NOT NULL DEFAULT 0,
    has_warnings       boolean NOT NULL DEFAULT false,
    has_ownership_data boolean NOT NULL DEFAULT false,
    response_encrypted bytea,
    charges_cents      int,
    not_found          boolean NOT NULL DEFAULT false,
    error_message      text,
    carjam_request_id  text,
    forgotten_at       timestamptz,                                             -- G29
    created_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (match IS NULL OR match IN ('Y','PY','M','PM','U','N'))
);
ALTER TABLE ppsr_searches ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON ppsr_searches
    USING (org_id = current_setting('app.current_org_id', true)::uuid);

-- Quota counters mirroring the existing carjam_lookups pattern.
-- (G44 closure — `hidden_plate` matches the actual CarJam flag `ppsrh=1` instead of the misleading `money_owing` name.)
ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS ppsr_lookups_included int NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ppsr_hidden_plate_lookups_included int NOT NULL DEFAULT 0;

ALTER TABLE organisations
    ADD COLUMN IF NOT EXISTS ppsr_lookups_this_month int NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ppsr_hidden_plate_lookups_this_month int NOT NULL DEFAULT 0;
-- Reuses the existing `carjam_lookups_reset_at` timestamp for monthly rollover.

-- Module registration (idempotent — wizard auto-shows the question to new orgs).
INSERT INTO module_registry (
    id, slug, display_name, description, category, is_core,
    dependencies, incompatibilities, status,
    setup_question, setup_question_description
) VALUES (
    gen_random_uuid(),
    'ppsr',
    'PPSR Vehicle Checks',
    'Run PPSR money-owing and ownership checks on NZ vehicles via CarJam.',
    'vehicles',
    false,
    '[]'::jsonb,
    '[]'::jsonb,
    'available',
    'Do you need to check if a vehicle has money owing on it (PPSR) or look up ownership history?',
    'Run finance-status, ownership, and warning checks on any NZ-registered vehicle. Uses the same CarJam connection as vehicle lookups.'
) ON CONFLICT (slug) DO NOTHING;

-- Feature-flag mirror per implementation-completeness-checklist Rule 8.
-- ACTUAL column shape per app/modules/feature_flags/models.py:18-80 — there is NO `default_enabled` and NO `scope` column. Mirror 0203_staff_phase1_schema.py:254-276 exactly.
INSERT INTO feature_flags (
    id, key, display_name, description, category,
    access_level, dependencies, default_value,
    is_active, targeting_rules, created_at, updated_at
) VALUES (
    gen_random_uuid(),
    'ppsr',
    'PPSR Vehicle Checks',
    'PPSR (Personal Property Securities Register) module — money-owing, ownership-history, warnings, and hidden-plate checks via the existing CarJam integration.',
    'operations',
    'all_users',
    '[]'::jsonb,
    true,                  -- default_value=true per migration 0171 policy; module gate is the real lever
    true,
    '[]'::jsonb,
    now(),
    now()
)
ON CONFLICT (key) DO NOTHING;

-- Append 'ppsr' to enabled_modules JSONB of all non-archived plans.
UPDATE subscription_plans
SET enabled_modules = (
    SELECT jsonb_agg(DISTINCT m)
    FROM jsonb_array_elements_text(enabled_modules || '["ppsr"]'::jsonb) m
)
WHERE NOT is_archived;
```

### 3.1a Vehicle-link resolution (G23 closure)

On every fresh PPSR search, `PpsrService.search()` resolves the vehicle link before insert:

```python
# After CarJam responds, before INSERT:
org_vehicle_id = None
global_vehicle_id = None

# 1. Look for an existing OrgVehicle row in this org (UPPER match).
ov = await db.execute(
    select(OrgVehicle.id).where(
        OrgVehicle.org_id == org_id,
        OrgVehicle.rego == rego_norm,
    ).limit(1)
)
org_vehicle_id = ov.scalar_one_or_none()

# 2. If no OrgVehicle row, look at GlobalVehicle (shared cache).
if not org_vehicle_id:
    gv = await db.execute(
        select(GlobalVehicle.id).where(GlobalVehicle.rego == rego_norm).limit(1)
    )
    global_vehicle_id = gv.scalar_one_or_none()
```

Neither call mutates the vehicle tables — the PPSR module does NOT auto-create or promote vehicle rows. That stays the responsibility of the existing `app/modules/vehicles/service.py::_ensure_vehicle_linked` flow used by Invoice Create / Kiosk. PPSR is a read-side observer.

If the user later clicks "Save report to vehicle file" on the result panel, the frontend POSTs `/ppsr/searches/:id/link-vehicle` with the chosen `org_vehicle_id` — the service updates the link column (audit-logged as `ppsr.search.linked`).

### 3.2 Migration `0208_ppsr_indexes.py` (CONCURRENTLY)

```python
_UPGRADE: list[tuple[str, str]] = [
    ("History page lookup (org × date)",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_org_created "
     "ON ppsr_searches (org_id, created_at DESC)"),
    # G30 closure — cache lookup keyed on (org, rego, options_hash). G24 — plain `rego` is sufficient since rego is normalised UPPER on insert; no UPPER() function index.
    ("Cache lookup (org × rego × options_hash × date)",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_org_rego_options_created "
     "ON ppsr_searches (org_id, rego, options_hash, created_at DESC)"),
    ("Per-user activity report",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_user "
     "ON ppsr_searches (user_id, created_at DESC)"),
    # G13/G39 closure — Vehicle Profile embed latest-match-per-vehicle lookup. Partial index keeps it small.
    ("Vehicle Profile embed — latest match per org_vehicle",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppsr_searches_org_vehicle "
     "ON ppsr_searches (org_id, org_vehicle_id, created_at DESC) "
     "WHERE org_vehicle_id IS NOT NULL"),
]
```

### 3.3 ORM additions

`app/modules/ppsr/models.py` defines `PpsrSearch` with mapped fields one-to-one with the migration. `response_encrypted` typed as `Mapped[bytes | None]` via `LargeBinary`. `options_json` typed as `Mapped[dict]` via `JSONB`.

## 4. Service Layer

### 4.1 `CarjamClient.lookup_ppsr` (extension to `app/integrations/carjam.py`)

```python
@dataclass(frozen=True)
class CarjamPpsrResponse:
    rego: str
    not_found: bool
    basic: dict | None
    ownership_history: list[dict] | None
    current_owner: dict | None
    ppsr_summary: dict
    ppsr_details: list[dict]
    money_owing: dict
    warnings: list[dict] | None
    flood: dict | None
    charges_cents: int | None
    raw_xml: str
    requested_options: dict


class CarjamClient:
    # ... existing methods unchanged ...

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
    ) -> CarjamPpsrResponse:
        if (include_owners or include_owner) and not s241_purpose:
            raise ValueError(
                "s241_purpose required when include_owners or include_owner is true"
            )

        # G-CODE-14: _check_carjam_rate_limit returns tuple (allowed, retry_after).
        allowed, retry_after = await _check_carjam_rate_limit(self._redis, self._rate_limit)
        if not allowed:
            raise CarjamRateLimitError(retry_after=retry_after)

        params: dict[str, str] = {
            "key": self._api_key,
            "plate": rego.strip().upper(),
            "basic": "1" if include_basic else "0",
            "ppsr": "1",
            "f": "json",                              # G-CODE-13: match existing lookup_vehicle JSON-mode parser
        }
        if include_owners:        params["owners"] = "1"
        if include_owner:         params["owner"] = "1"
        if include_warnings:      params["warnings"] = "1"
        if include_fws:           params["fws"] = "1"
        if check_hidden_plates:   params["ppsrh"] = "1"
        if s241_purpose:          params["s241_purpose"] = s241_purpose
        if translate:             params["translate"] = "1"
        if use_cache is not None: params["cache"] = str(use_cache)
        params["charges"] = "1"   # always return charge info

        url = f"{self._base_url}/api/car/"             # G-CODE-13: same path as lookup_vehicle
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            body_text = resp.text

        return _parse_ppsr_response(rego, body_text, requested_options=params)
```

**Response format note (G-CODE-13):** `lookup_vehicle` already passes `f=json` ([carjam.py:341](app/integrations/carjam.py#L341)). CarJam returns JSON when `f=json` is set regardless of feature flags. `_parse_ppsr_response` therefore parses JSON, not XML. The earlier spec text mentioning "raw XML" still applies as a *storage* concept — we keep the raw response body text for audit (could be JSON-encoded), but the parser reads JSON dicts directly. If CarJam's PPSR endpoint behaviour differs (some flags only return XML), the parser must dual-format: try JSON first, fall back to XML on parse failure.

The parser (`_parse_ppsr_response`) handles the CarJam JSON response (`f=json` per G-CODE-13). The nested structure mirrors the XML response shape — keys are the same. Handles:
- Top-level `error` key → raise `CarjamError(error.message)`.
- `message.idh.header.not_found == true` → `not_found=True`.
- `message.idh` content → `basic` dict (delegate to existing `_parse_vehicle_response(rego, message.idh)` for parity).
- `message.ioh.owners` → `ownership_history` array (when `owners=1`).
- `message.ico` → `current_owner` dict (when `owner=1`).
- `message.ppsr` + `message.ppsr_details` → `ppsr_summary` + `ppsr_details`.
- `message.money_owing` → dict with `match`, `match_description`, `search_id`.
- `message.warnings` → array (when `warnings=1`).
- `message.flood` → dict (when `fws=1`).
- `message.charges.cents` → `charges_cents` int.
- `raw_xml` field on the dataclass is misnamed (legacy of the XML-era plan) — keep the field name for backwards-compat with the dataclass docstring, but the value stored is `resp.text` (which CarJam returns as JSON-encoded text). Add a deprecation comment + rename to `raw_body` in a follow-up minor version.
- **Dual-format fallback (G-CODE-13):** if `resp.text` doesn't parse as JSON, attempt XML parsing — CarJam docs warn that some optional flags may revert to XML in edge cases. Wrap the JSON-first / XML-fallback in a single helper.

### 4.2 `app/modules/ppsr/service.py` — `PpsrService`

```python
class PpsrService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

    async def search(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        rego: str,
        options: PpsrSearchOptions,
        force_refresh: bool = False,
    ) -> PpsrSearchResult:
        # 1. Module gate (defence-in-depth — also gated by middleware at router boundary).
        # G-CODE-5: `ModuleService.require_enabled` doesn't exist; call `is_enabled` and raise.
        if not await ModuleService(self.db).is_enabled(str(org_id), "ppsr"):
            raise HTTPException(403, "module_not_enabled")

        # 2. CarJam configuration gate (G28/G49 closure).
        # G-CODE-4: `get_integration_config` returns ONLY masked / safe fields — it cannot
        # return the secret api_key needed for runtime calls. Load the IntegrationConfig
        # row directly and decrypt the full JSON, mirroring `_load_carjam_client` at
        # app/modules/vehicles/service.py:28-64.
        from app.modules.admin.models import IntegrationConfig
        from app.core.encryption import envelope_decrypt_str
        cfg_row_q = await self.db.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
        )
        cfg_row = cfg_row_q.scalar_one_or_none()
        if cfg_row is None:
            raise PpsrCarjamNotConfiguredError()
        try:
            cfg_fields = json.loads(envelope_decrypt_str(cfg_row.config_encrypted))
        except Exception:
            raise PpsrCarjamNotConfiguredError()
        if not (cfg_fields.get("api_key") or "").strip():
            raise PpsrCarjamNotConfiguredError()

        # Pull optional fields with safe defaults — never raise on missing keys (G28).
        s241_default      = cfg_fields.get("s241_purpose_default") or None
        cache_ttl_minutes = int(cfg_fields.get("ppsr_cache_ttl_minutes") or 5)
        owner_enabled     = bool(cfg_fields.get("ppsr_owner_lookups_enabled") or False)

        # 3. Quota check.
        quota = await self._load_quota(org_id)
        if quota.used >= quota.included:
            raise PpsrQuotaExceededError(quota)

        # 4. Owner-lookup gating.
        if options.include_current_owner or options.include_ownership_history:
            if not owner_enabled:
                raise PpsrOwnerLookupsDisabledError()
            effective_s241 = options.s241_purpose or s241_default
            if not effective_s241:
                raise PpsrS241PurposeRequiredError()
        else:
            effective_s241 = None

        rego_norm = rego.strip().upper()
        options_hash = _hash_options(options)  # G30 — sha256(canonical_json)

        # 5. Redis in-flight lock (G27 — prevent double-billing on rapid double-click).
        lock_key = f"ppsr:lock:{org_id}:{rego_norm}:{options_hash}"
        async with redis_lock(self.redis, lock_key, ttl=30, wait_timeout=5):
            # Re-check cache inside the lock — another tab may have populated it while we waited.

            # 6. Cache check (G26 — skip forgotten rows; G30 — keyed on options_hash).
            if not force_refresh:
                cached = await self._find_recent_match(org_id, rego_norm, options_hash, cache_ttl_minutes)
                if cached is not None:
                    await write_audit_log(
                        session=self.db, action="ppsr.search.cached",
                        entity_type="ppsr_search", entity_id=cached.id,
                        org_id=org_id, user_id=user_id,
                        after_value={"source_search_id": str(cached.id), "rego": rego_norm},
                    )
                    return PpsrSearchResult.from_cached(cached)

            # 7. Call CarJam.
            client = await _load_carjam_client(self.db, self.redis)
            carjam_resp = await client.lookup_ppsr(
                rego_norm,
                include_owners=options.include_ownership_history,
                include_owner=options.include_current_owner,
                include_warnings=options.include_warnings,
                include_fws=options.include_fws,
                check_hidden_plates=options.check_hidden_plates,
                s241_purpose=effective_s241,
            )

            # 8. Resolve vehicle link (G23 closure — read-side only, no mutation).
            ov_id, gv_id = await self._resolve_vehicle_link(org_id, rego_norm)

            # 9. Persist (encrypted).
            encrypted = envelope_encrypt(json.dumps(_to_serialisable(carjam_resp)))  # G31 — function name verified
            search = PpsrSearch(
                org_id=org_id, user_id=user_id, rego=rego_norm,
                options_json=options.model_dump(),
                options_hash=options_hash,                   # G30
                org_vehicle_id=ov_id,                        # G13
                global_vehicle_id=gv_id,                     # G13
                match=carjam_resp.money_owing.get("match"),
                match_description=carjam_resp.money_owing.get("match_description"),
                statement_count=int(carjam_resp.ppsr_summary.get("count", 0)),
                has_warnings=bool(carjam_resp.warnings),
                has_ownership_data=bool(carjam_resp.ownership_history or carjam_resp.current_owner),
                response_encrypted=encrypted,
                charges_cents=carjam_resp.charges_cents,
                not_found=carjam_resp.not_found,
                carjam_request_id=_extract_request_id(carjam_resp.raw_xml),
            )
            self.db.add(search)

            # 10. Increment quota counter atomically (G44 — renamed columns).
            await self.db.execute(
                update(Organisation)
                .where(Organisation.id == org_id)
                .values(
                    ppsr_lookups_this_month=Organisation.ppsr_lookups_this_month + 1,
                    **({"ppsr_hidden_plate_lookups_this_month":
                        Organisation.ppsr_hidden_plate_lookups_this_month + 1}
                       if options.check_hidden_plates else {}),
                )
            )

            await self.db.flush()
            await self.db.refresh(search)

            # 11. Audit (audit_log singular per app/core/audit.py:79).
            await write_audit_log(
                session=self.db, action="ppsr.search",
                entity_type="ppsr_search", entity_id=search.id,
                org_id=org_id, user_id=user_id,
                after_value={
                    "rego": rego_norm,
                    "options": options.model_dump(),
                    "match": search.match,
                    "statement_count": search.statement_count,
                    "charges_cents": search.charges_cents,
                },
            )

            return PpsrSearchResult.from_fresh(search, carjam_resp)

    async def _find_recent_match(
        self, org_id: UUID, rego: str, options_hash: str, ttl_minutes: int
    ) -> PpsrSearch | None:
        """G30 — keyed on options_hash so JSON-key-order doesn't break cache;
        G26 — skip forgotten rows (response_encrypted IS NULL)."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
        result = await self.db.execute(
            select(PpsrSearch).where(
                PpsrSearch.org_id == org_id,
                PpsrSearch.rego == rego,
                PpsrSearch.options_hash == options_hash,
                PpsrSearch.created_at >= cutoff,
                PpsrSearch.response_encrypted.isnot(None),     # G26 — forgotten rows don't satisfy cache
                PpsrSearch.error_message.is_(None),
                PpsrSearch.not_found.is_(False),
                PpsrSearch.forgotten_at.is_(None),             # G29 — defence-in-depth
            ).order_by(PpsrSearch.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def _resolve_vehicle_link(self, org_id: UUID, rego: str) -> tuple[UUID | None, UUID | None]:
        """G23 — match rego against existing vehicle tables WITHOUT mutating them."""
        ov = await self.db.execute(
            select(OrgVehicle.id).where(
                OrgVehicle.org_id == org_id, OrgVehicle.rego == rego
            ).limit(1)
        )
        ov_id = ov.scalar_one_or_none()
        if ov_id:
            return ov_id, None
        gv = await self.db.execute(
            select(GlobalVehicle.id).where(GlobalVehicle.rego == rego).limit(1)
        )
        return None, gv.scalar_one_or_none()

    async def forget_search(self, search_id: UUID, current_user) -> None:
        """G26 / G29 closure — wipe payload, leave summary + audit row.
        Org-admin only; preserves audit trail."""
        if current_user.role != "org_admin":
            raise HTTPException(403, "org_admin_required")
        await self.db.execute(
            update(PpsrSearch)
            .where(PpsrSearch.id == search_id)
            .values(
                response_encrypted=None,
                forgotten_at=func.now(),
                error_message=PpsrSearch.error_message.op("COALESCE")("forgotten by admin"),
            )
        )
        # Best-effort Redis cache invalidation (key may not exist; that's OK).
        await self.redis.delete(f"ppsr:cache:{current_user.org_id}:{search_id}")
        await write_audit_log(
            session=self.db, action="ppsr.forgotten",
            entity_type="ppsr_search", entity_id=search_id,
            org_id=current_user.org_id, user_id=current_user.id,
            after_value={"search_id": str(search_id)},
        )
```

### 4.3 PDF export (`app/modules/ppsr/pdf.py`)

Mirrors the existing WeasyPrint pattern at `app/modules/quotes/service.py:1162-1165` / `app/modules/invoices/service.py:4449-4452`:

```python
async def render_pdf(search: PpsrSearch, decrypted_response: dict, org_ctx: dict) -> bytes:
    html = render_template(
        "ppsr/report.html",
        search=search,
        response=decrypted_response,
        org=org_ctx,
    )
    return await asyncio.to_thread(lambda: HTML(string=html).write_pdf())
```

### 4.3a PDF org template variables (G25/G42 + G-CODE-6 + G-CODE-7 closure)

The `org_ctx` dict passed to the Jinja template is built from `organisations.settings` JSONB (verified against [app/modules/invoices/service.py:4257-4297](app/modules/invoices/service.py#L4257-L4297)). **The org has no `address_line_1`, `region`, `postcode` columns — all address fields live in the `settings` JSONB.** Build the context as:

```python
from app.core.pdf_utils import resolve_logo_for_pdf

settings = org.settings or {}
org_ctx = {
    "name": org.name,                                        # column on organisations table
    "logo_url": resolve_logo_for_pdf(org),                   # base64 data URI for WeasyPrint; helper in app/core/pdf_utils.py
    "address_unit": settings.get("address_unit"),
    "address_street": settings.get("address_street"),
    "address_city": settings.get("address_city"),
    "address_state": settings.get("address_state"),
    "address_postcode": settings.get("address_postcode"),
    "address_country": settings.get("address_country"),
    "phone": settings.get("phone"),
    "email": settings.get("email"),
    "website": settings.get("website"),
    "gst_number": settings.get("gst_number"),
    "primary_colour": settings.get("primary_colour", "#1a1a1a"),
}
```

The template (`app/modules/ppsr/templates/report.html`) mirrors the existing invoice PDF header pattern verbatim (see [app/templates/pdf/invoice.html:144-159](app/templates/pdf/invoice.html#L144-L159)):

```jinja
{% if org.logo_url %}<img src="{{ org.logo_url }}" alt="{{ org.name }}" class="logo">{% endif %}
<div class="org-name">{{ org.name }}</div>
{% if org.address_unit %}{{ org.address_unit }}<br>{% endif %}
{% if org.address_street %}{{ org.address_street }}<br>{% endif %}
{% if org.address_city or org.address_state or org.address_postcode %}
  {{ org.address_city or '' }}{% if org.address_city and (org.address_state or org.address_postcode) %}, {% endif %}{{ org.address_state or '' }}{% if org.address_state and org.address_postcode %}, {% endif %}{{ org.address_postcode or '' }}<br>
{% endif %}
{% if org.phone %}{{ org.phone }}<br>{% endif %}
{% if org.email %}{{ org.email }}<br>{% endif %}
{% if org.gst_number %}<div>GST No: {{ org.gst_number }}</div>{% endif %}
```

The disclaimer footer is a constant string in the template:
*"This PPSR report was generated via the CarJam API on {{ search.created_at | nz_datetime }}. It is current as at the search time only. Independent legal advice should be sought before acting on this information."*

Print-CSS basics (mirrors invoice PDF):
- `@page { size: A4; margin: 18mm 15mm; }`
- `@media print` rules to suppress interactive elements (not needed for WeasyPrint render but harmless).
- `white-space: pre-wrap` on the disclaimer paragraph and any wrapped strings.

### 4.4 Quota reset (existing pattern — G-CODE-8)

**The reset task does NOT live in `app/tasks/scheduled.py`.** Verified against the actual codebase — the reset fires per-org inside the billing cycle at [app/tasks/subscriptions.py:196 and :273](app/tasks/subscriptions.py#L196). Pattern:

```python
# In app/tasks/subscriptions.py inside process_due_billings:
if sms_overage_count > 0:
    org.sms_sent_this_month = 0
if carjam_overage_count > 0:
    org.carjam_lookups_this_month = 0
# NEW for PPSR — same boundary, same overage-conditional reset:
if ppsr_overage_count > 0:
    org.ppsr_lookups_this_month = 0
    org.ppsr_hidden_plate_lookups_this_month = 0
```

A matching `ppsr_overage_count` computation is added near the existing `carjam_overage_count` (around line 150 of `subscriptions.py`) — same shape, comparing `org.ppsr_lookups_this_month` against `plan.ppsr_lookups_included` plus the hidden-plate variant. Then `ppsr_overage_cents` is added into the `total_excl_gst_cents` sum.

No new task or scheduler; ~10 line addition inside the existing `process_due_billings` loop.

(G43 race-condition guard from earlier draft is unnecessary in this pattern — `process_due_billings` already iterates orgs whose `next_billing_date` has fallen due, with per-org locking, so there's no chance of a simultaneous double-reset.)

## 5. API Endpoints

| Endpoint | Method | Purpose | Returns |
|---|---|---|---|
| `/api/v2/ppsr/search` | POST | Run a PPSR search; returns the structured response (cached or fresh) | 200, 402 (quota), 422 (config/s241), 429 (rate limit), 502 (CarJam down) |
| `/api/v2/ppsr/searches` | GET | Search history (paginated, denormalised summary only) — `{ items, total }`. Filters: rego, match, user_id (admin-only), date_from, date_to. | 200 |
| `/api/v2/ppsr/searches/:id` | GET | Single search with decrypted payload (admin or original user only) | 200, 403 (not own + not admin), **410** (forgotten), 404 (not found) |
| `/api/v2/ppsr/searches/:id/export` | GET | Download PDF of the decrypted search | 200 (application/pdf), 410 (forgotten), 403 |
| `/api/v2/ppsr/searches/:id/forget` | DELETE | Admin-only: wipe the encrypted payload (audit-logged); summary row retained; sets `forgotten_at=now()` | 204, 403, 404 |
| `/api/v2/ppsr/searches/:id/link-vehicle` | POST | Body `{ org_vehicle_id }`. Link a saved PPSR search to an existing OrgVehicle row. Audit `ppsr.search.linked`. (G23 closure) | 200, 404 |
| `/api/v2/ppsr/quota` | GET | Current org's quota usage `{ used, included, hidden_plate_used, hidden_plate_included, resets_at }` | 200 |

All list responses are `{ items, total }`. Pagination via `offset` (default 0) + `limit` (default 25, max 100) per existing patterns. All endpoints gated by `ModuleService.is_enabled(org_id, "ppsr")` and `RequireAuth`. The middleware returns **HTTP 403** with `{ detail, module }` when disabled (G38) — not 404 as initially drafted.

**Global-admin handling (G8):** when `current_user.org_id is None` (platform admin), every PPSR router raises `HTTPException(403, "ppsr_requires_org_context")`. Global admins read PPSR activity via the existing Audit Log admin screen, not via PPSR endpoints.

## 6. Frontend Component Tree

### 6.0 UI / UX polish guidelines (G-CODE-FE-1 — make it look right)

Every PPSR component MUST:

- **Use existing UI primitives.** `Card`, `Button`, `Input`, `Select`, `Toggle`, `Banner`, `Badge`, `Spinner`, `Drawer`, `Modal`, `EmptyState`, `PageHeader`, `DataTable` — all live in `frontend/src/components/ui/`. Don't roll our own. If a primitive is missing for a specific need (e.g., MatchBanner), build it as a small new file in `frontend/src/pages/ppsr/components/` rather than inline.
- **Tailwind class palette** must mirror the rest of the app — read `frontend/tailwind.config.js` for design tokens. Specifically:
  - Page background: `bg-gray-50 dark:bg-gray-900`.
  - Card surface: `bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700`.
  - Padding: `p-6` for top-level cards, `p-4` for nested panels.
  - Headings: `text-xl font-semibold text-gray-900 dark:text-white` for page; `text-base font-medium` for card titles.
  - Body text: `text-sm text-gray-700 dark:text-gray-300`.
  - Form-element height: `h-10` (40px); min touch target 44×44 on mobile.
- **Traffic-light banner colour scheme** for `money_owing.match`:
  | Match | Banner colour | Tailwind |
  |---|---|---|
  | `Y` (matched, money owing) | Red | `bg-red-50 text-red-900 border-red-300 dark:bg-red-900/20 dark:text-red-100` |
  | `PY` (possible match, money owing) | Red-amber | `bg-orange-50 text-orange-900 border-orange-300 dark:bg-orange-900/20` |
  | `M` (matched, no money owing) | Amber-info | `bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-900/20` |
  | `PM` (possible match, no money owing) | Amber-info | (same as M) |
  | `U` (unknown / could not determine) | Slate | `bg-slate-50 text-slate-900 border-slate-300 dark:bg-slate-800/40` |
  | `N` (no match — clear) | Green | `bg-emerald-50 text-emerald-900 border-emerald-300 dark:bg-emerald-900/20` |
- **Empty / loading / error states** are mandatory (per `implementation-completeness-checklist.md` Rule 4):
  - **Empty** (no result yet, no history): centred icon + `<EmptyState message="..." action={...} />` per `frontend/src/components/ui/EmptyState.tsx`.
  - **Loading**: skeleton blocks for content > 200 ms; `<Spinner size="md" />` for short ops.
  - **Error**: `<Banner variant="error">` with the API error message; never just blank.
  - **Cached badge**: small `<Badge variant="info">Cached HH:MM · Force refresh</Badge>` inline with the result panel header.
- **Accessibility:**
  - Every interactive element has a discernible label (`aria-label` on icon-only buttons).
  - Tab order is logical: form → result → history.
  - Focus rings via existing `focus:ring-2 focus:ring-primary-500`.
  - The traffic-light banner ALSO carries a textual match-description — colour is not the only signal (WCAG 1.4.1).
- **Mobile responsiveness:**
  - Form fields stack on `< sm` (640 px); two-column on `≥ md` (768 px).
  - Tables wrap in `overflow-x-auto` so the financing-statements table doesn't break the viewport on phones.
  - Action row buttons collapse to a `<details>` "More actions" menu on `< sm`.
- **Dark mode**: every Tailwind class has a `dark:` variant (existing project convention). Test with `document.documentElement.classList.add('dark')` in dev.
- **Microcopy** (consistent with rest of app):
  - "Run search" not "Submit" (action verb the user understands).
  - "PPSR check" everywhere user-facing, never "lookup" or "query" in the GUI.
  - Quota strip: "PPSR checks: 7 / 50 this month — resets 1 Jul".
  - Forget: "Wipe report payload (audit trail kept)" — explain what stays, what goes.
  - Force refresh: "Run a fresh search, ignoring the 5-minute cache" tooltip.
- **Iconography**: PPSR icon should evoke "checklist + vehicle"; use a Heroicons-style outline SVG (no external library). Sit it inline with the page header.
- **Currency formatting** (G34): `Intl.NumberFormat(orgLocale, { style: 'currency', currency: 'NZD' }).format(cents / 100)`. Never hardcode `$`.
- **Date formatting**: use the existing `formatRelative` / `formatDateTime` helpers in `frontend/src/utils/date.ts` (or equivalent) — no inline `toLocaleString` reinvention.
- **Toasts**: import the existing `useToast()` hook for transient feedback ("Search saved", "PDF downloaded"). 4-second auto-dismiss.

### 6.1 `PPSRSearchPage.tsx`

```tsx
import { useState, useCallback, useEffect } from 'react'
import { PageHeader } from '@/components/ui/PageHeader'
import { QuotaStrip } from './components/QuotaStrip'
import { SearchForm } from './components/SearchForm'
import { PpsrResultPanel } from './components/PpsrResultPanel'
import { PpsrHistoryTable } from './components/PpsrHistoryTable'
import { ppsrApi, type PpsrSearchResult } from '@/api/ppsr'

// Module-disabled fallback is handled by <ModuleRoute moduleSlug="ppsr"> in App.tsx,
// so the page itself does NOT need its own isEnabled check (G-CODE-3 — earlier draft
// duplicated the gate which is a maintenance smell).
export default function PPSRSearchPage() {
  const [result, setResult] = useState<PpsrSearchResult | null>(null)
  const [isSearching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [historyKey, setHistoryKey] = useState(0)  // bump to refresh history after a search

  const handleSearch = useCallback(async (form: PpsrSearchInput) => {
    setSearching(true)
    setError(null)
    try {
      const res = await ppsrApi.search(form)
      setResult(res?.data ?? null)
      setHistoryKey(k => k + 1)
    } catch (e: unknown) {
      setError(extractErrorMessage(e) ?? 'PPSR search failed')
    } finally {
      setSearching(false)
    }
  }, [])

  return (
    <div className="space-y-6 p-6">
      <PageHeader title="PPSR Vehicle Check" subtitle="Check money owing, ownership, and warnings on any NZ vehicle." />
      <QuotaStrip />
      <SearchForm onSearch={handleSearch} loading={isSearching} />
      {error && <Banner variant="error">{error}</Banner>}
      {result && <PpsrResultPanel result={result} />}
      <PpsrHistoryTable refreshKey={historyKey} />
    </div>
  )
}
```

State management: local `useState` for form fields and result; `ppsr` typed API client handles the POST. AbortController applies in `QuotaStrip` and `PpsrHistoryTable` per safe-api-consumption.md.

### 6.1a Page layout wireframe (G-CODE-FE-2 — concrete spec)

```
┌────────────────────────────────────────────────────────────────────────┐
│  ◀ PPSR Vehicle Check                                                  │   ← PageHeader (h1 + subtitle)
│  Check money owing, ownership, and warnings on any NZ vehicle.         │
├────────────────────────────────────────────────────────────────────────┤
│  PPSR checks: ████░░░░░░ 7 / 50 this month — resets 1 Jul   [Manage]   │   ← QuotaStrip card
├────────────────────────────────────────────────────────────────────────┤
│  Search                                                                │   ← SearchForm card
│  ┌──────────┐  Include:                                                │
│  │  ABC123  │  ☑ Money owing (always)                                  │
│  │  (rego)  │  ☑ Warnings & recalls                                    │
│  └──────────┘  ☐ Fire/water/write-off                                  │
│                ☐ Hidden-plate search (extra charge)         ⓘ          │
│                ☐ Current owner    [disabled — configure s241 ⓘ]        │
│                ☐ Ownership history                                     │
│                                                                        │
│  ☐ Force refresh (bypass 5-min cache)                                  │
│                                                                        │
│  [ Run search ]   ← disabled while in-flight or quota=0                │
├────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────┐  │   ← PpsrResultPanel
│  │   🟢   No money owing                                            │  │
│  │        Match: N · Statements: 0                                  │  │
│  │                                                  [Cached 14:32]  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  Vehicle:  2018 Toyota Hilux SR5 · Silver                              │
│  Warnings: ⚠ 1 active recall (click for details)                       │
│  Charges:  CarJam reported $0.50 NZD for this check                    │
│                                                                        │
│  [ Export PDF ]  [ Save to vehicle file ]  [ New search ]              │
├────────────────────────────────────────────────────────────────────────┤
│  Recent PPSR checks                                                    │   ← PpsrHistoryTable
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Date         Rego     Match            Statements  By       $   │    │
│  │ 14:32 Today  ABC123   🟢 No owing       0          you      .50 │    │
│  │ Yesterday    BCD234   🔴 Money owing    1          ana      .50 │    │
│  │ 28 May       CDE345   ⚪ Unknown         —          you      .50 │    │
│  │             [ ‹ 1 2 3 › ]                                       │    │
│  └────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────┘
```

Key visual decisions:
- Vertical stack on mobile; tighter horizontal layout on ≥ `md` breakpoint.
- The traffic-light banner uses BOTH colour AND emoji glyph (🟢/🟠/🔴/⚪) so it survives colour-blindness.
- "Manage" link in quota strip → routes to `/admin/subscription-plans` (org admin) or shows a tooltip for non-admins.
- "Cached HH:MM" badge in the top-right corner of the result panel is clickable → triggers force-refresh.

### 6.2 `SearchForm` (inside PPSRSearchPage)

Fields:
- **Rego** text input — uppercase, alphanumeric, 1-8 chars; validation inline. Rejects any non-alphanumeric character (G18-A3 — defends against `'; DROP TABLE`-style injection at the input layer).
- **Includes** checkbox group:
  - "Money owing" — always on, disabled.
  - "Warnings & recalls" — default on.
  - "Fire/water/write-off" — default off.
  - "Hidden-plate search (extra charge)" — default off; tooltip "Searches past plates; CarJam bills this at a higher rate (counts against your separate hidden-plate quota)".
  - "Current owner" — disabled when `!ppsr_owner_lookups_enabled || !s241_purpose_default`; tooltip explains why.
  - "Ownership history" — same gating as current owner.
- **`s241_purpose`** text input — only renders when current-owner or ownership-history is checked; default value is the org's `s241_purpose_default`.
- **`force_refresh`** toggle — bypass cache.
- **Search button** — disabled while a search is in-flight, **disabled when `quota.used >= quota.included`** with tooltip "PPSR quota exhausted. Ask your org admin to grant more in your subscription plan." (G35 closure).

### 6.3 `PpsrResultPanel.tsx`

Sections:
1. **Money owing banner**: traffic-light coloured (red `Y`/`PY`, amber `M`/`PM`, grey `U`, green `N`). Shows `match_description`.
2. **Cached badge**: when `result.cached === true`, render a small badge "Cached at HH:MM — Re-run for fresh data" with a "Force refresh" button shortcut.
3. **Basic vehicle**: make/model/year/colour summary card.
4. **Financing statements** table (when `ppsr_details.length > 0`):
   - Columns: Secured party, Collateral description, Registration date, Status.
5. **Warnings** rows (when `warnings.length > 0`):
   - Severity-coloured; expandable for details.
6. **Ownership** table (when included):
   - Owner name (masked when s241 not authorised), Date of ownership, Status, DOB (when authorised).
7. **Flood / FWS** card (when `fws=1` and data present).
8. **Charges footer**: "CarJam reported a charge of {{currency}} for this search." Use `Intl.NumberFormat(orgLocale, { style: 'currency', currency: 'NZD' }).format(cents / 100)` (G34 closure — no hardcoded `$` per mobile-app.md guidance).
9. **Actions row**:
   - **Export PDF** → triggers `/searches/:id/export` download.
   - **Save report to vehicle file** → if rego matches an existing `org_vehicles`/`global_vehicles` row, link the search to it (writes `vehicle_id` to a new column or to vehicle metadata — see Open Question PPSR-005).
   - **New search** → clears the form.

### 6.4 `PpsrHistoryTable.tsx`

Columns: Date, Rego, Match (colour chip), Statements, By (user), Charge. Pagination 25/page. Click a row → open detail in a drawer (calls `/searches/:id`).

### 6.5 `PpsrCard.tsx` (embed on Vehicle Profile)

```tsx
import { ModuleGate } from '@/components/common/ModuleGate'

export function PpsrCard({ rego }: { rego: string }) {
  // G-CODE-3: ModuleGate prop name is `module`, not `moduleSlug`
  return (
    <ModuleGate module="ppsr">
      <PpsrCardInner rego={rego} />
    </ModuleGate>
  )
}

function PpsrCardInner({ rego }: { rego: string }) {
  const { latest, isLoading } = useLatestPpsrSearch(rego)
  return (
    <Card title="PPSR">
      {isLoading && <Spinner size="sm" />}
      {!isLoading && !latest && (
        <EmptyState
          message="No PPSR check on file for this vehicle."
          action={{ label: "Run PPSR check now", href: `/ppsr/search?rego=${encodeURIComponent(rego)}` }}
        />
      )}
      {!isLoading && latest && (
        <MatchBanner match={latest?.match ?? 'U'} description={latest?.match_description ?? ''}>
          <span>Last checked {formatRelative(latest?.created_at)} by {latest?.user_email ?? 'unknown'}</span>
          <Button as={Link} to={`/ppsr/search?rego=${encodeURIComponent(rego)}`} size="sm">
            Re-run check
          </Button>
        </MatchBanner>
      )}
    </Card>
  )
}
```

Placement: inside the existing `VehicleProfile.tsx` between WOF/COF cards and Notes section. Module-gated via `<ModuleGate module="ppsr">`. Safe-API patterns (`?.` + `??`) applied per safe-api-consumption.md.

### 6.6 CarJam config page extension

The existing CarJam config form (Global Admin and/or org Settings → Integrations) gets a new "PPSR" sub-section with:

- `s241_purpose_default` — text input + helper text linking to CarJam member dashboard.
- `ppsr_cache_ttl_minutes` — numeric input, min 1, max 60, default 5.
- `ppsr_owner_lookups_enabled` — boolean toggle.

Save handler PATCHes `integration_configs[name='carjam']` with the new fields merged into the existing `fields` JSON. Mask-pattern detection still applies (if the user submits `***` for a previously-set value, skip).

## 7. User Workflow Traces

### 7.1 First PPSR search by an org admin

```
User toggles "PPSR Vehicle Checks" ON in setup wizard
  → org_modules.is_enabled=true for 'ppsr' for this org
  → feature_flag mirror also true
User navigates sidebar → PPSR Check
  → route resolves; ModuleRoute passes; page renders
QuotaStrip GETs /api/v2/ppsr/quota → "0 / 0 — admin needs to grant quota"
  → admin clicks "Manage quota" link → goes to Global Admin → Subscription Plans
  → bumps ppsr_lookups_included to 50 on the org's plan
QuotaStrip refreshes → "0 / 50"

User types rego = "ABC123"
  → "Warnings & recalls" already checked (default)
  → ignores hidden-plate (default off)
  → leaves owner / ownership unchecked (admin hasn't set s241_purpose_default yet)
User clicks Search
  → POST /api/v2/ppsr/search { rego: "ABC123", include_warnings: true, ... }
  → service.search():
      module gate ✓
      quota check: 0 < 50 ✓
      no owner flags → no s241 gating
      no cache match → call CarJam
      CarjamClient.lookup_ppsr with basic=1, ppsr=1, warnings=1, charges=1
      → CarJam responds with money_owing.match='N', 0 statements, 1 warning (recall)
      → envelope_encrypt the JSON, insert ppsr_searches row
      → increment org.ppsr_lookups_this_month to 1
      → audit ppsr.search
      → commit
  → 200 OK with structured payload
Frontend renders green "No money owing" banner + 1 warning row.
```

### 7.2 Owner-lookup attempt without s241

```
Admin checks "Current owner" on the form
  → frontend disables the box because ppsr_owner_lookups_enabled=false
    or s241_purpose_default is null
  → tooltip: "Configure your s241 authorisation in Settings → Integrations → CarJam"
Admin clicks the tooltip link, configures the purpose, returns
  → frontend re-fetches CarJam config, checkbox is now enabled
Admin clicks Search again
  → POST /api/v2/ppsr/search { rego, include_current_owner: true, s241_purpose: null }
  → service.search() merges s241_purpose_default from config
  → CarjamClient.lookup_ppsr with owner=1, s241_purpose=...
  → response includes ico tag with owner info
  → encrypted JSON stored; summary row includes has_ownership_data=true
  → audit ppsr.search with options.include_current_owner=true
```

### 7.3 Cache hit on repeat search

```
User runs same rego + options 90 seconds later
  → service.search():
      no force_refresh
      _find_recent_match finds the prior row (within 5min TTL, same options_json, same rego)
      audit ppsr.search.cached with source_search_id
      returns PpsrSearchResult.from_cached(prior)
  → response includes cached=true, cached_at, source_search_id
  → quota counter NOT incremented (no CarJam call)
Frontend shows "Cached at HH:MM" badge.
```

### 7.4 Force refresh

```
User clicks "Force refresh" toggle and Search again
  → service.search() with force_refresh=true
  → cache check skipped → fresh CarJam call → new ppsr_searches row → counter increments
```

### 7.5 PDF export

```
User clicks "Export PDF" on the result
  → frontend GETs /api/v2/ppsr/searches/:id/export
  → router checks ownership (user is original searcher OR org_admin)
  → service decrypts response_encrypted
  → render_pdf() → Jinja + WeasyPrint via asyncio.to_thread
  → audit ppsr.exported
  → returns application/pdf
Browser downloads the file.
```

### 7.6 Forget a search

```
Admin opens search detail → Forget button
  → DELETE /api/v2/ppsr/searches/:id/forget
  → service.forget_search() sets response_encrypted=NULL, error_message='forgotten by admin'
    (the audit-trail row stays; only the encrypted payload is wiped)
  → audit ppsr.forgotten
  → 204 No Content
History row now shows "(payload forgotten)" instead of a clickable detail link.
```

## 8. Modal / Panel Inventory

| Element | Trigger | Contains | Closes |
|---|---|---|---|
| `SearchInProgressOverlay` | Search button → loading | Spinner + "Talking to CarJam..." | Auto-dismiss on result |
| `QuotaExceededModal` | 402 response | Quota usage + link to admin upgrade | OK button |
| `S241ConfigPromptModal` | Owner/Ownership checkbox while config missing | Helper text + link to Settings | Backdrop / OK |
| `PpsrDetailDrawer` | History row click | Decrypted result panel + Export + Forget (admin) | X / Esc / Backdrop |
| `ForgetConfirmModal` | Forget button | "This wipes the cached payload; the audit row stays." | Cancel / Confirm |
| `ExportingPdfToast` | Export PDF click | "Preparing PDF..." → "Downloaded" | Auto-dismiss |

## 9. Error & Edge Case UI

| Case | UI |
|---|---|
| 402 `ppsr_quota_exceeded` | `QuotaExceededModal` with link to Subscription Plans |
| 422 `s241_purpose_required` | Inline red below the s241 field |
| 422 `s241_not_authorised` | Banner: "Owner lookups not enabled for this org — see Settings → Integrations → CarJam" |
| 422 invalid rego format | Inline red below rego field |
| 429 (CarJam global rate limit) | Toast "CarJam is busy — try again in a few seconds" with Retry-After-driven countdown |
| 404 `not_found` from CarJam (vehicle doesn't exist) | "No vehicle found for that registration. Check the plate and try again." |
| 502 CarJam upstream error | Banner: "CarJam is currently unavailable. Try again shortly." Audit `ppsr.search` row written with `error_message` populated. |
| 403 on detail endpoint (not the searcher and not admin) | Toast "You don't have permission to view this search" + redirect to history |
| Module disabled mid-session | Sidebar item disappears on next render; navigating directly to the URL → `FeatureNotAvailablePage` |
| Loading | `MobileSpinner` (mobile) / `Spinner` (web) |
| Empty history | "No PPSR checks yet — run your first one above." |
| `not_found=true` on a search | Special amber banner: "CarJam couldn't find a vehicle for this rego. The plate might be wrong, surrendered, or never registered." |

## 10. Integration Points

- **CarJam credentials** — reuses `integration_configs[name='carjam']` and the existing `_load_carjam_client(db, redis)` factory. No new integration to register.
- **Module-gate middleware** — `app/middleware/modules.py::MODULE_ENDPOINT_MAP` needs entries for `/api/v2/ppsr/*` → `ppsr`.
- **Setup wizard** — auto-picks up the new `module_registry` row; no frontend change in the wizard component.
- **Subscription Plans admin UI** — actual page is [frontend/src/pages/admin/SubscriptionPlans.tsx:1349](frontend/src/pages/admin/SubscriptionPlans.tsx#L1349) (G-CODE-12 — `SubscriptionPlanForm.tsx` doesn't exist). Pattern is inline form state via `set('field_name', value)`; mirror the `carjam_lookups_included` field at line 493. New form fields: `ppsr_lookups_included`, `ppsr_hidden_plate_lookups_included` (G44).
- **Audit log viewer** — existing `AuditLog.tsx` admin screen surfaces the new actions automatically (slug-agnostic).
- **Vehicle Profile** — additive embed via `PpsrCard.tsx`. No existing functionality removed or reshaped.
- **Email / SMS** — none. PPSR is a pure-fetch surface; no outbound notifications.

## 11. Performance

- **CarJam call latency** is the dominant cost — typically 800–1500 ms p99 because the upstream goes to NZTA. Frontend shows a clear loading spinner; the request handler shouldn't block on anything else.
- **Cache hits** return <50 ms p99 — single indexed `ppsr_searches` SELECT + decrypt is fast.
- **History page** uses `idx_ppsr_searches_org_created` — O(log N) lookup with LIMIT/OFFSET pagination.
- **Vehicle Profile embed** uses `idx_ppsr_searches_rego_match` — single-row latest-per-rego lookup.
- **Encrypted payload size** typically 2–10 KB after envelope encryption — negligible row size.
- **Global rate limit** — `_check_carjam_rate_limit` enforces the platform-wide CarJam budget (existing). PPSR queries count against this same budget so we don't accidentally DoS the upstream.

## 12. Security / PII

- **Encryption at rest:** `ppsr_searches.response_encrypted` is envelope-encrypted via `app/core/encryption.py`. Only the explicit detail endpoint (R6.2) decrypts.
- **Mask in audit:** audit log rows never contain decrypted owner names, DOBs, or financing-statement debtor details. The `after_value` is summary fields only.
- **RBAC (G36/G37 closure — simplified to match actual `ppsr_searches` schema which has no `branch_id`):**
  - `org_admin`: can search, can read any search detail, can export any, can forget any, can link to vehicle.
  - All other roles (`staff_member`, `salesperson`, `branch_admin`, `location_manager`, etc.): can run searches if module is enabled for the org; can only read their **own** searches (server-side check: `search.user_id == current_user.id`); cannot forget.
  - `global_admin`: blocked from PPSR endpoints (`org_id is None` → 403 `ppsr_requires_org_context`).
- **Endpoint gating:** the detail endpoint refuses with 403 when neither admin nor the original searcher.
- **No raw PII in URL** — search inputs go via POST body; detail endpoint URLs contain only the search UUID.
- **No localStorage of decrypted PII** — frontend caches in component state only; nothing serialised to disk.
- **Forget mechanism** (R6.4 / endpoint `/forget`): wipes `response_encrypted` to NULL, leaves the summary fields for audit. Mirrors the "right to be forgotten" principle while preserving the audit trail of the search itself.

## 13. Verified-against-code addendum

Every fact below was confirmed by reading the actual file at the cited line range (commit at 2026-05-31).

### Backend code references — verified

- ✅ `app/integrations/carjam.py::CarjamClient` at line 252. Constructor: `__init__(self, redis: Redis, *, api_key=None, base_url=None, rate_limit=None, timeout=10.0)`. PPSR `lookup_ppsr` is added as a method on this same class — no new client.
- ✅ `_check_carjam_rate_limit(redis, limit)` at line 114 returns **tuple `(allowed: bool, retry_after: int)`** — `lookup_ppsr` MUST unpack it, not `await`-discard like the spec earlier showed:
  ```python
  allowed, retry_after = await _check_carjam_rate_limit(self._redis, self._rate_limit)
  if not allowed:
      raise CarjamRateLimitError(retry_after=retry_after)
  ```
- ✅ `_load_carjam_client(db, redis)` at [app/modules/vehicles/service.py:28-64](app/modules/vehicles/service.py#L28-L64) loads from `IntegrationConfig`, decrypts via `envelope_decrypt_str`, reads JSON fields `api_key`, `endpoint_url`, `global_rate_limit_per_minute`. PPSR will use this same factory verbatim — no fork.
- ✅ `IntegrationConfig` table ([app/modules/admin/models.py:271-291](app/modules/admin/models.py#L271-L291)) has a CHECK constraint `name IN ('carjam','stripe','smtp','twilio')` — PPSR reuses `name='carjam'`, no new constraint value needed.
- ✅ `subscription_plans.carjam_lookups_included` is `Mapped[int]` at [app/modules/admin/models.py:57](app/modules/admin/models.py#L57). `subscription_plans.enabled_modules` is JSONB at line 58. `subscription_plans.is_archived` is Boolean (line 60).
- ✅ `organisations.carjam_lookups_this_month` at line 112; `carjam_lookups_reset_at` at line 113. `organisations.settings` is JSONB at line 116 — the org address / phone / email / GST / logo all live in this dict.
- ✅ **Quota reset task lives in [app/tasks/subscriptions.py:196 + :273](app/tasks/subscriptions.py#L196), NOT `app/tasks/scheduled.py`.** The reset fires per-org at billing-cycle boundary when `carjam_overage_count > 0`. PPSR adds two parallel lines next to the existing `org.carjam_lookups_this_month = 0`.
- ✅ `app/core/encryption.py::envelope_encrypt(plaintext: str | bytes) -> bytes` at line 66 — confirmed. `envelope_decrypt_str(blob: bytes) -> str` at line 105 is what reads the JSON back.
- ✅ `app/core/audit.py::write_audit_log(session, *, action, entity_type, org_id, user_id, entity_id, before_value, after_value, ip_address, device_info)` at line 35; SQL writes to table **`audit_log`** (singular) at line 79.
- ✅ `app/core/modules.py::ModuleService.is_enabled(org_id: str, module_slug: str) -> bool` at line 304. **There is NO `require_enabled()` helper** — service-level defence-in-depth must call `is_enabled` and raise itself:
  ```python
  if not await ModuleService(self.db).is_enabled(str(org_id), "ppsr"):
      raise HTTPException(403, "module_not_enabled")
  ```
- ✅ `app/middleware/modules.py::MODULE_ENDPOINT_MAP` at line 36 — dict of path-prefix → module slug. PPSR adds single entry `"/api/v2/ppsr": "ppsr"` (no wildcard; `_resolve_module` at line 71 matches by prefix). Disabled-module response is HTTP **403** with `{detail: "Module 'ppsr' is not enabled for your organisation.", module: "ppsr"}` at lines 117-126.
- ✅ `module_registry.setup_question` + `setup_question_description` columns exist at [app/modules/module_management/models.py:41-42](app/modules/module_management/models.py#L41-L42).
- ✅ `feature_flags` real columns ([app/modules/feature_flags/models.py:18-80](app/modules/feature_flags/models.py#L18-L80)): `id, key, display_name, description, category, access_level, dependencies, default_value, is_active, targeting_rules`. **No `default_enabled`, no `scope`.** Migration must mirror [0203:254-276](alembic/versions/2026_05_31_0900-0203_staff_phase1_schema.py#L254-L276).
- ✅ `TRADE_GATED_MODULES = {"vehicles"}` at [app/modules/setup_guide/router.py:45](app/modules/setup_guide/router.py#L45) — PPSR is **not** added here ✓.
- ✅ User roles per [alembic 0136](alembic/versions/2026_04_04_0900-0136_add_branch_admin_role.py#L24): `global_admin, franchise_admin, org_admin, branch_admin, location_manager, salesperson, staff_member, kiosk`. PPSR RBAC uses `org_admin` for admin-only ops; all other org-roles for own-search read.
- ✅ Router DI pattern (mirror [app/modules/vehicles/router.py:126-131](app/modules/vehicles/router.py#L126-L131)):
  ```python
  async def ppsr_search(
      request: Request,
      db: AsyncSession = Depends(get_db_session),
      redis: Redis = Depends(get_redis),
  ): ...
  ```
- ✅ `OrgVehicle` lives at [app/modules/vehicles/models.py:32](app/modules/vehicles/models.py#L32). **`GlobalVehicle` lives at [app/modules/admin/models.py:210](app/modules/admin/models.py#L210) — NOT in `app/modules/vehicles/models.py`.** Import accordingly:
  ```python
  from app.modules.vehicles.models import OrgVehicle
  from app.modules.admin.models import GlobalVehicle
  ```
- ✅ WeasyPrint pattern at [app/modules/quotes/service.py:1162](app/modules/quotes/service.py#L1162) and [app/modules/invoices/service.py:4449](app/modules/invoices/service.py#L4449) — `await asyncio.to_thread(lambda: HTML(string=html).write_pdf())`.
- ✅ PDF org context loaded from `org.settings` JSONB ([app/modules/invoices/service.py:4257-4297](app/modules/invoices/service.py#L4257-L4297)):
  - **Actual keys** in `org.settings`: `address_unit`, `address_street`, `address_city`, `address_state`, `address_postcode`, `address_country`, `phone`, `email`, `website`, `gst_number`, `primary_colour`, `invoice_header_text`, `invoice_footer_text`.
  - Logo: `from app.core.pdf_utils import resolve_logo_for_pdf; org_context["logo_url"] = resolve_logo_for_pdf(org)` — returns a base64 data URI.
  - The PPSR PDF template uses **these exact keys** — earlier spec mention of `address_line_1`, `region`, `postcode` was wrong; corrected in §4.3a.
- ✅ Existing CarJam config admin schema map ([app/modules/admin/service.py:1734-1742](app/modules/admin/service.py#L1734-L1742)):
  - `_SAFE_FIELDS["carjam"] = ["endpoint_url", "per_lookup_cost_nzd", "abcd_per_lookup_cost_nzd", "global_rate_limit_per_minute"]` — PPSR extends to: `[..., "ppsr_cache_ttl_minutes", "ppsr_owner_lookups_enabled"]` (boolean + int, both safe).
  - `_MASKED_FIELDS["carjam"] = ["api_key"]` — PPSR extends to: `[..., "s241_purpose_default"]` (treated like a secret for GUI consistency per R7.3).
- ✅ Existing CarJam DB JSON config keys (per [_load_carjam_client](app/modules/vehicles/service.py#L28-L64)): `api_key`, `endpoint_url`, `global_rate_limit_per_minute`. **PPSR adds three NEW keys to the same JSON:** `s241_purpose_default`, `ppsr_cache_ttl_minutes`, `ppsr_owner_lookups_enabled`. The `_load_carjam_client` helper reads only `api_key`/`endpoint_url`/`rate_limit` — PPSR service must do its own JSON read for the three new keys (load the row + decrypt the JSON directly, same pattern).
- ✅ `get_integration_config(db, name)` ([app/modules/admin/service.py:1749-1809](app/modules/admin/service.py#L1749-L1809)) returns `{name, is_verified, updated_at, fields: { ...safe and masked fields only... }}` — **DO NOT use this for runtime credentials**; it doesn't return secrets. The PPSR service must read `IntegrationConfig` + `envelope_decrypt_str` directly (same as `_load_carjam_client`).

### Frontend code references — verified

- ✅ `ModuleGate` ([frontend/src/components/common/ModuleGate.tsx:6,13](frontend/src/components/common/ModuleGate.tsx#L6)) uses prop name **`module`** (NOT `moduleSlug`). Correct usage: `<ModuleGate module="ppsr">...</ModuleGate>`. Earlier spec snippets that wrote `moduleSlug='ppsr'` would not compile.
- ✅ `ModuleRoute` ([frontend/src/components/common/ModuleRoute.tsx:8,23](frontend/src/components/common/ModuleRoute.tsx#L8)) uses prop name **`moduleSlug`** (matches PPSR spec). Usage: `<ModuleRoute moduleSlug="ppsr">...</ModuleRoute>`.
- ✅ `FeatureNotAvailable` ([frontend/src/pages/common/FeatureNotAvailable.tsx:7](frontend/src/pages/common/FeatureNotAvailable.tsx#L7)) is the disabled-module fallback; `ModuleRoute` renders it automatically — no manual import in PPSRSearchPage required.
- ✅ `useTenant().tradeFamily` returns slug strings like `'automotive-transport'`, `'plumbing-gas'` ([frontend/src/contexts/TenantContext.tsx:56-57,94](frontend/src/contexts/TenantContext.tsx#L56-L57)). Null fallback per steering: `tradeFamily ?? 'automotive-transport'`.
- ✅ `useModules().isEnabled(slug: string)` ([frontend/src/contexts/ModuleContext.tsx:27,91](frontend/src/contexts/ModuleContext.tsx#L27)).
- ✅ **Sidebar layout is a FLAT `navItems` array, not nested sections.** [frontend/src/layouts/OrgLayout.tsx:43-85](frontend/src/layouts/OrgLayout.tsx#L43-L85). Each item: `{ to, label, icon, module?, flagKey?, tradeFamily?, adminOnly? }`. Earlier spec mention of "PPSR Check under Vehicles/Tools section" was wrong — there are no sections. PPSR Check is a single nav item inserted after Vehicles:
  ```ts
  { to: '/ppsr/search', label: 'PPSR Check', icon: PpsrIcon, module: 'ppsr', flagKey: 'ppsr' },
  ```
  (No `tradeFamily` filter — PPSR is universal, visible to any trade as long as module enabled.)
- ✅ `VehicleProfile` lives at [frontend/src/pages/vehicles/VehicleProfile.tsx](frontend/src/pages/vehicles/VehicleProfile.tsx); route at [App.tsx:414](frontend/src/App.tsx#L414) is gated by `ModuleRoute moduleSlug="vehicles"`. PPSR card embed goes inside this page wrapped in `<ModuleGate module="ppsr">` (not `moduleSlug=`).
- ✅ **CarJam config UI is at [frontend/src/pages/admin/Integrations.tsx](frontend/src/pages/admin/Integrations.tsx) (Global Admin → Integrations) — NOT a path under `/settings/integrations/`.** PPSR fields go into the `INTEGRATION_FIELDS.carjam` array at line 45-51. The component renders fields generically — appending three new entries is mechanical:
  ```ts
  { key: 's241_purpose_default', label: 's241 purpose code', type: 'password', placeholder: '••••••••', backendKey: 's241_purpose_default_last4', helperText: 'Source from your CarJam member dashboard → s241 section. Required for owner-lookups.' },
  { key: 'ppsr_cache_ttl_minutes', label: 'PPSR cache TTL (minutes)', type: 'number', placeholder: '5', helperText: 'How long to serve cached PPSR results before re-hitting CarJam. Default 5.' },
  { key: 'ppsr_owner_lookups_enabled', label: 'Enable owner / ownership-history lookups', type: 'checkbox', helperText: 'Tick this AND set s241 purpose code before owner-lookups will work.' },
  ```
  (Note: `Integrations.tsx` may need a `type: 'checkbox'` field type added — verify before relying on it; otherwise use `type: 'text'` with `'true'/'false'` strings.)
- ✅ **Subscription Plans admin page is at [frontend/src/pages/admin/SubscriptionPlans.tsx:1349](frontend/src/pages/admin/SubscriptionPlans.tsx#L1349)** (not `SubscriptionPlanForm.tsx` — that file doesn't exist). Pattern: inline form state with `set('field_name', value)` and `<Input checked={form.field > 0} onChange={...} />`. PPSR adds two new numeric inputs mirroring `carjam_lookups_included` at line 493.
- ✅ Module-gated route registration pattern at [App.tsx:414](frontend/src/App.tsx#L414):
  ```tsx
  <Route path="/vehicles/:id" element={<SafePage name="vehicle-profile"><ModuleRoute moduleSlug="vehicles"><VehicleProfile /></ModuleRoute></SafePage>} />
  ```
  PPSR follows this exact wrap: `SafePage` (error boundary) → `ModuleRoute` → page.

### Migration sequencing — verified

- ✅ Current alembic head is **0206** ([2026_05_31_0903-0206_leave_indexes.py](alembic/versions/2026_05_31_0903-0206_leave_indexes.py)). PPSR migrations therefore land as **0207** (schema + module_registry + feature_flags + plan extension) and **0208** (CONCURRENTLY index pack).
- ✅ `CREATE INDEX CONCURRENTLY` template per [0204_staff_phase1_indexes.py](alembic/versions/2026_05_31_0901-0204_staff_phase1_indexes.py#L67) — `_run_outside_tx` helper with `op.get_context().autocommit_block()`. Mirror exactly.
- ✅ The PPSR test endpoint `https://test.carjam.co.nz/api/car/` is the documented test surface (CarJam member docs); cannot programmatically grep this — it's an external API. Test fixtures must be captured into `tests/fixtures/carjam_ppsr_*.xml` before the E2E script runs to ensure reproducibility.

### Code-verified gap list (G-CODE-1..20)

The 20 specific gaps caught by this sweep and where they were closed:

| Gap | What was wrong | Closure |
|---|---|---|
| G-CODE-1  | `feature_flags` INSERT used wrong column names (`default_enabled`, `scope`) | Real shape applied in §3.1 SQL + R1.2 |
| G-CODE-2  | `GlobalVehicle` import path | Documented: `from app.modules.admin.models import GlobalVehicle` |
| G-CODE-3  | `<ModuleGate moduleSlug=>` (wrong) vs `<ModuleGate module=>` (correct) | §6.5 PpsrCard prop fixed |
| G-CODE-4  | `get_integration_config` returns masked fields only, not usable at runtime | Service uses `IntegrationConfig` + `envelope_decrypt_str` directly per `_load_carjam_client` pattern |
| G-CODE-5  | `ModuleService.require_enabled()` doesn't exist | Use `is_enabled` + raise HTTPException 403 |
| G-CODE-6  | Org address fields are in `org.settings` JSONB, not direct columns | §4.3a corrected to actual keys |
| G-CODE-7  | Logo loaded via `resolve_logo_for_pdf(org)` helper, not raw setting | §4.3a documents the helper call |
| G-CODE-8  | Quota reset lives in `app/tasks/subscriptions.py`, not `scheduled.py` | §4.4 corrected; tasks C8 corrected |
| G-CODE-9  | Sidebar is flat array, not nested sections | §2 + R8.2 simplified to single nav-item insert |
| G-CODE-10 | CarJam config UI lives at `admin/Integrations.tsx`, not `settings/integrations/...` | §6.6 corrected |
| G-CODE-11 | Existing CarJam config JSON already has `endpoint_url`, `per_lookup_cost_nzd`, `abcd_per_lookup_cost_nzd`, `global_rate_limit_per_minute` | Documented; PPSR adds 3 more keys to same JSON |
| G-CODE-12 | Frontend admin page is `SubscriptionPlans.tsx`, not `SubscriptionPlanForm.tsx` | D9 task path corrected |
| G-CODE-13 | `lookup_vehicle` uses `f=json` — PPSR response format must be chosen (JSON or XML) | `lookup_ppsr` will also use `f=json` for parser parity; XML fallback if PPSR fields aren't in JSON |
| G-CODE-14 | `_check_carjam_rate_limit` returns `(allowed, retry_after)` tuple | §4.1 updated to unpack tuple |
| G-CODE-15 | Adding per-org rate limit needs new constant in `app/middleware/rate_limit.py` | Tasks C5 + new task C9 added |
| G-CODE-16 | `tradeFamily` slug confirmed `'automotive-transport'` | already aligned |
| G-CODE-17 | Next alembic head is 0207/0208 | Migration filenames updated |
| G-CODE-18 | `TRADE_GATED_MODULES` correctly NOT touched | already aligned |
| G-CODE-19 | `MODULE_ENDPOINT_MAP` entry is `"/api/v2/ppsr"` (no wildcard) | C6 corrected |
| G-CODE-20 | `audit_log` (singular) confirmed | already aligned post-G33 |

## 14. Spec-completeness self-check

Per `.kiro/steering/spec-completeness-checklist.md`:

- ✅ §1 Navigation & Access — §2.
- ✅ §2 Frontend Component Tree — §6.
- ✅ §3 User Workflow Trace — §7.
- ✅ §4 Modal / Panel Inventory — §8.
- ✅ §5 Toolbar / Action Bar — §6.3 (PpsrResultPanel actions row).
- ✅ §6 List/Table — §6.4 (PpsrHistoryTable) + R6.1 (filters spec).
- ✅ §7 Error & Edge Case UI — §9.
- ✅ §8 Integration Points — §10.

## 15. Gap-closure addendum (steering sweep 2026-05-31)

Every patch applied to close gaps identified by a sweep against the steering library. See `requirements.md` §"Gap-Closure Addendum" for the master gap table.

Design-side changes summary:

- **§1a** new — full request-path trace (G6, Rule 2 of implementation-completeness-checklist).
- **§3.1** schema additions — `options_hash`, `org_vehicle_id`, `global_vehicle_id`, `forgotten_at` columns (G13/G30/G39/G29); counter columns renamed `ppsr_hidden_plate_lookups_*` (G44).
- **§3.1a** new — vehicle-link resolution algorithm (G23).
- **§3.2** index pack — `idx_ppsr_searches_org_rego_options_created` keyed on `options_hash`, plain `rego` (G24); partial index on `org_vehicle_id` (G13).
- **§4.2** `PpsrService.search()` — CarJam-not-configured gate (G28/G49), Redis in-flight lock (G27), cache lookup keyed on `options_hash` + skip forgotten (G26/G30), function name verified `envelope_encrypt` (G31), audit `audit_log` singular (G33/G45), counter rename (G44), `forget_search()` helper added (G26/G29).
- **§4.3** PDF render signature accepts `org_ctx` dict; §4.3a enumerates exactly what keys go into it (G25/G42); print-CSS basics added.
- **§4.4** daily reset task — race-condition guard `WHERE carjam_lookups_reset_at < now - 1 day` (G43).
- **§5** endpoints table — added `link-vehicle` (G23); detail endpoint returns 410 on forgotten (G29); module-disabled returns 403 with `{detail, module}` (G38); global-admin handling (G8); status codes per endpoint.
- **§6.2** SearchForm — rego validation rejects non-alphanumeric (G18-A3); Search button disabled at quota=0 (G35).
- **§6.3** PpsrResultPanel — `Intl.NumberFormat` for NZD (G34).
- **§12** RBAC simplified — `org_admin` OR `own search`; global_admin blocked (G8/G36/G37).
