# PPSR Module — Code-Gap Analysis

Audit of `.kiro/specs/ppsr-module/{requirements,design,tasks}.md` against the actual codebase. Every claim was re-verified by reading the cited file/line. The "Verified-against-code addendum" in design.md §13 and the "Code-Verified Addendum" in tasks.md were treated as **claims** to re-check.

Audit performed: 2026-05-31 (post-Phase 4 payroll merge).

---

## Backend claims

### B1. CarjamClient location + class structure — ✅ verified

`app/integrations/carjam.py:252` → `class CarjamClient:` matches.

Constructor at lines 270-285:
```python
def __init__(
    self,
    redis: Redis,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    rate_limit: int | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> None:
```

`_DEFAULT_TIMEOUT = 10.0` is at line 249. Matches spec exactly.

### B2. `_check_carjam_rate_limit` signature — ✅ verified

`app/integrations/carjam.py:114-122`:
```python
async def _check_carjam_rate_limit(
    redis: Redis,
    limit: int,
) -> tuple[bool, int]:
    """...Returns ``(allowed, retry_after_seconds)``."""
```

Returns a tuple. Spec is correct — `lookup_ppsr` MUST unpack `(allowed, retry_after)`.

### B3. `lookup_vehicle` uses `f=json` — ✅ verified

`app/integrations/carjam.py:341`:
```python
"f": "json",  # Request JSON format instead of XML
```

Confirmed inside the `params` dict at lines 337-342, called from `lookup_vehicle` at line 326. Spec claim "PPSR can mirror this for parser parity" is correct.

### B4. `_load_carjam_client` location + signature — ✅ verified

`app/modules/vehicles/service.py:28`:
```python
async def _load_carjam_client(db: AsyncSession, redis: Redis) -> CarjamClient:
```

Function spans lines 28-65. Spec said "lines 28-64"; actual is 28-65 (off by 1, **LOW**). Loads via `IntegrationConfig` + `envelope_decrypt_str(config_row.config_encrypted)`. Spec correctly identifies the pattern PPSR must mirror.

### B5. `IntegrationConfig` model has `config_encrypted` BLOB column — ✅ verified

`app/modules/admin/models.py:280`:
```python
config_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
```

Column name is `config_encrypted` (not `config` or `encrypted_config`). Type is `LargeBinary` (PostgreSQL `BYTEA`). Class definition at line 271. CHECK constraint `name IN ('carjam','stripe','smtp','twilio')` confirmed. Spec is correct.

### B6. `envelope_encrypt` exists at `app/core/encryption.py:66` — ✅ verified

`app/core/encryption.py:66`:
```python
def envelope_encrypt(plaintext: str | bytes) -> bytes:
```

`envelope_decrypt(blob: bytes) -> bytes` at line 88. `envelope_decrypt_str(blob: bytes) -> str` at line 105. The function is `envelope_encrypt`, not `envelope_encrypt_str`. Spec is correct.

### B7. `write_audit_log` writes to table `audit_log` (singular) — ✅ verified

`app/core/audit.py:35` → `async def write_audit_log(...)`.

`app/core/audit.py:79`:
```sql
INSERT INTO audit_log (
```

Singular `audit_log`, no trailing `s`. Cross-confirmed by `AuditLog.__tablename__ = "audit_log"` in `app/modules/admin/models.py`. Spec is correct.

### B8. `ModuleService.is_enabled` exists, `require_enabled` does NOT — ✅ verified

`app/core/modules.py:304`:
```python
async def is_enabled(self, org_id: str, module_slug: str) -> bool:
```

A grep for `def require_enabled` across `app/core/modules.py` returned zero matches. Spec is correct — service-layer defence-in-depth must call `is_enabled` and raise `HTTPException(403)` itself.

### B9. `app/middleware/modules.py:117-126` returns 403 (not 404) — ✅ verified

`app/middleware/modules.py:121-130` (spec said 117-126; actual block is 121-130, **LOW** line drift):
```python
if not enabled:
    response = JSONResponse(
        status_code=403,
        content={
            "detail": f"Module '{module_slug}' is not enabled for your organisation.",
            "module": module_slug,
        },
    )
    await response(scope, receive, send)
    return
```

Status code is **403**, body is `{detail, module}`. Spec is structurally correct; line range drift is cosmetic.

### B10. `app/middleware/modules.py:95-97` fails open for global_admin — ⚠️ partial — clarification

The fail-open path exists but the line range is wrong.

Actual code at `app/middleware/modules.py:96-102`:
```python
org_id = getattr(request.state, "org_id", None)             # line 96

# Only check module-gated paths for authenticated org requests
if not org_id:                                              # line 99
    await self.app(scope, receive, send)
    return                                                  # line 102
```

The check `if not org_id:` (line 99) makes the middleware fail open for any request without `org_id` set on `request.state` (global_admin, anon, etc.). Spec said "lines 95-97" — actual is **lines 96-102**. **LOW** — semantic claim is correct, line numbers drift.

There is also a SECOND fail-open at lines 115-119 (exception handler):
```python
except Exception:
    logger.exception("Module check failed for %s/%s", org_id, module_slug)
    # Fail open — don't block requests if the check itself fails
    await self.app(scope, receive, send)
    return
```

The spec only references the first fail-open. Both are real.

### B11. Migration 0203 feature_flags column shape — ✅ verified

Spec says lines 254-276; actual block at `alembic/versions/2026_05_31_0900-0203_staff_phase1_schema.py:255-281` (first INSERT, **LOW** line drift):

```sql
INSERT INTO feature_flags (
    id, key, display_name, description, category,
    access_level, dependencies, default_value,
    is_active, targeting_rules, created_at, updated_at
) VALUES (...)
```

Confirmed columns: `id, key, display_name, description, category, access_level, dependencies, default_value, is_active, targeting_rules, created_at, updated_at`. NO `default_enabled`, NO `scope`. Spec is correct on shape; line range slightly off.

### B12. Migration 0203 enabled_modules JSONB update at lines 229-240 — ✅ verified

`alembic/versions/2026_05_31_0900-0203_staff_phase1_schema.py:229-240`:
```sql
UPDATE subscription_plans
SET enabled_modules = (
    SELECT jsonb_agg(DISTINCT m)
    FROM jsonb_array_elements_text(
        COALESCE(enabled_modules, '[]'::jsonb) || '["staff_management","payroll"]'::jsonb
    ) AS m
)
WHERE is_archived = false
```

Idempotent set-union via `jsonb_agg(DISTINCT)` and `WHERE is_archived = false`. Matches spec exactly.

### B13. `feature_flags` model column shape — ✅ verified

`app/modules/feature_flags/models.py:18-80` defines `FeatureFlag` with: `id, key, display_name, description, category, access_level, dependencies, default_value, is_active, targeting_rules, created_by, updated_by, created_at, updated_at`.

The model has two extra nullable columns (`created_by`, `updated_by`) that the migration INSERT doesn't populate (they're nullable FKs). The migration-shape match holds for INSERT purposes. Spec is correct.

### B14. Current alembic head — ❌ wrong — fix below

**HIGH severity.** Spec is wrong on multiple counts.

Spec claims (design.md §13, tasks A1/A2/§Code-Verified Addendum):
- "Current alembic head is **0206**".
- PPSR migrations therefore land as **0207** + **0208**.

Actual repo state (`ls alembic/versions/`):
```
2026_05_31_0903-0206_leave_indexes.py
2026_05_31_0904-0207_time_clock_schema.py
2026_05_31_0905-0208_time_clock_indexes.py
2026_05_31_0906-0209_payslip_schema.py
2026_05_31_0907-0210_payslip_indexes.py    ← head
```

`alembic/versions/2026_05_31_0907-0210_payslip_indexes.py` declares:
```python
revision: str = "0210"
down_revision: str = "0209"
```

So:
- **Current head is 0210, not 0206.**
- **Slots 0207 and 0208 are already taken by the time-clock migrations.**
- **Slots 0209 and 0210 are taken by payslip migrations.**

PPSR migrations must land as **0211** (`0211_ppsr_module.py`) + **0212** (`0212_ppsr_indexes.py`). Trying to write `0207_ppsr_module.py` would clash with the existing `2026_05_31_0904-0207_time_clock_schema.py`.

Fix:
- design.md §13 line "Current alembic head is **0206**" → change to "Current alembic head is **0210** (`2026_05_31_0907-0210_payslip_indexes.py`)."
- tasks.md A1 / A2 / Code-Verified Addendum A2 — rename to `0211_ppsr_module.py` and `0212_ppsr_indexes.py`.

### B15. `process_due_billings` location + line numbers — ✅ verified

`app/tasks/subscriptions.py`:
- `carjam_overage_count` initialised at **line 150**: `carjam_overage_count = 0` (followed by computation block at 152-165). Matches spec "around line 150".
- First reset block (skip-free-plan path, lines 193-196):
  ```python
  if sms_overage_count > 0:
      org.sms_sent_this_month = 0
  if carjam_overage_count > 0:
      org.carjam_lookups_this_month = 0          # line 196
  ```
- Second reset block (post-charge-success path, lines 270-273):
  ```python
  if sms_overage_count > 0:
      org.sms_sent_this_month = 0
  if carjam_overage_count > 0:
      org.carjam_lookups_this_month = 0          # line 273
  ```

Both reset points exist exactly as the spec claims. Pattern is "overage-conditional" — only resets when the overage counter > 0, matching spec design §4.4.

### B16. `app/middleware/rate_limit.py` constants — ✅ verified

Hard-coded prefix-mapped limits, no config-driven dispatcher. Real constants:
- `_PAYMENT_PAGE_PREFIX = "/api/v1/public/pay/"` (line 58); `_PAYMENT_PAGE_RATE_LIMIT = 20` (line 59).
- `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = "/api/v2/public/staff-roster/"` (line 71); `_PUBLIC_STAFF_ROSTER_RATE_LIMIT = 30` (line 72).
- `_HA_HEARTBEAT_PATH = "/api/v1/ha/heartbeat"` (line 64); `_HA_HEARTBEAT_RATE_LIMIT = 12` (line 65).
- `_PORTAL_PER_TOKEN_RATE_LIMIT = 60` (line 75); `_PORTAL_PER_IP_RATE_LIMIT = 20` (line 78).

Dispatch sites at lines 242-245 (`_PAYMENT_PAGE_PREFIX`) and 279-281 (`_PUBLIC_STAFF_ROSTER_PATH_PREFIX`) confirm the spec pattern: separate `_…_PATH_PREFIX` (string) and `_…_RATE_LIMIT` (int) constants. Spec wording "`_PUBLIC_STAFF_ROSTER_PATH_PREFIX = 30`" conflates the path prefix string with the limit integer (they are two different constants). **LOW** — cosmetic conflation; semantic intent (add `_PPSR_SEARCH_PATH` + `_PPSR_SEARCH_RATE_LIMIT` constants and dispatch in the middleware body) is right.

### B17. `_SAFE_FIELDS` and `_MASKED_FIELDS` line numbers — ⚠️ partial — clarification

Spec says line 1734 for `_SAFE_FIELDS` and 1742 for `_MASKED_FIELDS`. Actual at `app/modules/admin/service.py`:

- `_SAFE_FIELDS: dict[str, list[str]]` defined on **line 1733**, `"carjam": [...]` on **line 1735**. Spec said 1734 (off by 1; spec is pointing to the entry, not the dict declaration — defensible).
- `_MASKED_FIELDS: dict[str, list[str]]` defined on **line 1741**, `"carjam": ["api_key"]` on **line 1743**. Spec said 1742 (off by 1; same reasoning).

Confirmed shape:
```python
_SAFE_FIELDS: dict[str, list[str]] = {
    "carjam": ["endpoint_url", "per_lookup_cost_nzd", "abcd_per_lookup_cost_nzd", "global_rate_limit_per_minute"],
    ...
}
_MASKED_FIELDS: dict[str, list[str]] = {
    "carjam": ["api_key"],
    ...
}
```

Two separate dicts, both need extending. Spec is structurally correct. **LOW** — line-number drift only.

### B18. `OrgVehicle` and `GlobalVehicle` ORM models — ✅ verified

- `OrgVehicle` at `app/modules/vehicles/models.py:32`, has `org_id` (line 43, FK to organisations.id) and `rego` (line 46, `String(20), nullable=False`). ✓
- `GlobalVehicle` at `app/modules/admin/models.py:210`, has `rego` (line 220, `unique=True`). NO `org_id` (it's a shared cache table — that's correct; the spec query should target `OrgVehicle.org_id`/`OrgVehicle.rego` and only `GlobalVehicle.rego`). ✓

The design §3.1a query pattern in spec (`select(OrgVehicle.id).where(OrgVehicle.org_id == org_id, OrgVehicle.rego == rego_norm)` then `select(GlobalVehicle.id).where(GlobalVehicle.rego == rego_norm)`) compiles cleanly against this schema.

### B19. `_parse_vehicle_response` parser pattern — ✅ verified

`app/integrations/carjam.py:164`:
```python
def _parse_vehicle_response(rego: str, data: dict[str, Any], lookup_type: str = "basic") -> CarjamVehicleData:
    """Extract vehicle fields from a Carjam regular API response dict."""
```

Called from `lookup_vehicle` at line 437 with `vehicle_data = idh_data["vehicle"]` — the inner `idh.vehicle` dict, not `message.idh`. The spec design.md §4.1 says "delegate to existing `_parse_vehicle_response(rego, message.idh)`" — the actual call passes `idh.vehicle`, not `idh`. **LOW** — the delegation is feasible but the spec's argument shape is one nesting level off. PPSR parser must extract `idh.vehicle` (or whatever the equivalent is in the PPSR JSON response) before calling.

---

## Frontend claims

### F1. `frontend/src/components/common/ModuleGate.tsx` prop name — ✅ verified

`frontend/src/components/common/ModuleGate.tsx:6` defines the prop:
```tsx
interface ModuleGateProps {
  /** Module slug that must be enabled for children to render */
  module: string
  ...
}
```

`ModuleGate({ module, children, fallback = null }: ModuleGateProps)` at line 14. Prop is named **`module`**. Spec claim is correct (spec said line 13; the destructure is on line 14, the type-prop declaration is on line 6 — **LOW** drift).

### F2. `frontend/src/components/common/ModuleRoute.tsx` prop name — ✅ verified

`frontend/src/components/common/ModuleRoute.tsx:8`:
```tsx
interface ModuleRouteProps {
  /** Module slug that must be enabled for the route to render */
  moduleSlug: string
  ...
}
```

`export function ModuleRoute({ moduleSlug, children }: ModuleRouteProps)` at line 23.

The cross-component inconsistency (`ModuleGate` uses `module`, `ModuleRoute` uses `moduleSlug`) is real — both components exist in `frontend/src/components/common/`, with different prop names for the same concept. **Not a spec error**, it's an existing codebase quirk the spec correctly documents (G-CODE-3).

### F3. `frontend/src/layouts/OrgLayout.tsx:43-85` flat `navItems` array — ✅ verified

`frontend/src/layouts/OrgLayout.tsx:44-90` (spec said 43-85; the array literal opens at line 44 and closes at line 90 — **LOW** drift):

```tsx
const navItems: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: DashboardIcon },
  { to: '/customers', label: 'Customers', icon: CustomersIcon },
  { to: '/vehicles', label: 'Vehicles', icon: VehiclesIcon, module: 'vehicles', flagKey: 'vehicles', tradeFamily: 'automotive-transport' },
  ...
]
```

Flat array, no nested sections. Filter at **line 167** (`if (item.module) return isEnabled(item.module)`) — spec said line 161, actual is 167 (**LOW** drift; the filter logic is identical).

The spec recommendation to insert a single `navItems` entry after Vehicles (with `module: 'ppsr'`, `flagKey: 'ppsr'`, no `tradeFamily`) compiles cleanly against the existing `NavItem` interface (lines 31-41).

### F4. `frontend/src/App.tsx:414` is the VehicleProfile route — ❌ wrong — fix below

**LOW severity** (line drift; the structural pattern is correct).

Spec design.md §2 + §13 + tasks D8 cite `frontend/src/App.tsx:414` as the VehicleProfile route. Actual:

- `const VehicleProfile = lazy(() => import('@/pages/vehicles/VehicleProfile'))` at **line 66** (lazy import).
- The route registration at **line 437**:
  ```tsx
  <Route path="/vehicles/:id" element={<SafePage name="vehicle-profile"><ModuleRoute moduleSlug="vehicles"><VehicleProfile /></ModuleRoute></SafePage>} />
  ```

Line 414 in the actual file is in the global-admin `<Route path="integrations" ...>` block. The spec's claimed line 414 is wrong by ~23 lines.

Fix: change `[App.tsx:414]` references to `[App.tsx:437]` in design.md §2, design.md §13, and tasks.md D8.

Pattern wrap (`SafePage` → `ModuleRoute moduleSlug="…"` → page) matches spec exactly — only the line number is off.

### F5. `frontend/src/pages/admin/Integrations.tsx:45` — ✅ verified

`frontend/src/pages/admin/Integrations.tsx:44` opens the const:
```tsx
const INTEGRATION_FIELDS: Record<IntegrationName, FieldDef[]> = {
  carjam: [                                                    // line 45
    { key: 'api_key', ... },                                  // line 46
    { key: 'endpoint_url', ... },                             // line 47
    { key: 'per_lookup_cost_nzd', ... },                      // line 48
    { key: 'abcd_per_lookup_cost_nzd', ... },                 // line 49
    { key: 'global_rate_limit_per_minute', ... },             // line 50
  ],
  ...
}
```

Five existing carjam entries. Spec's three new entries (`s241_purpose_default`, `ppsr_cache_ttl_minutes`, `ppsr_owner_lookups_enabled`) are mechanical appends. **Note for implementer:** the existing `FieldDef` type union at line 32 is `'text' | 'password' | 'number' | 'select'` — there is **no** `'checkbox'` type. The spec acknowledges this in tasks D6 ("If the existing component doesn't support `type: 'checkbox'`, add a simple checkbox renderer..."), so the spec is internally consistent.

### F6. SubscriptionPlans.tsx form line numbers — ❌ wrong — fix below

**MEDIUM severity** (one line citation is structurally wrong, will mislead the implementer).

Spec claims (design.md §10 + §13, tasks D9):
- `:1349` is the **form**.
- `:493` is the `carjam_lookups_included` pattern.
- `:1527` is the table column list.

Actual:
- **Line 1349 is `export function SubscriptionPlans()`** — the **main page** export, NOT the form. Verified by reading the file.
- The **form** is `function PlanFormModal(...)` at **line 338**.
- The `carjam_lookups_included` checkbox pattern is at lines **492-510** (spec said 493; actual checkbox `<input>` opens line 492, the `checked={form.carjam_lookups_included > 0}` line is 493 — close enough, **LOW**).
- The table column entry `{ key: 'carjam_lookups_included', header: 'Carjam', ... }` is at **line 1527** — exactly as spec says. ✓

Fix: change `SubscriptionPlans.tsx:1349` references in design.md §10, design.md §13, and tasks.md D9 to point to the form at `SubscriptionPlans.tsx:338` (`function PlanFormModal`). The `set('field', value)` and `<input checked={form.field > 0} />` pattern lives inside `PlanFormModal`, not inside the main `SubscriptionPlans` page export.

### F7. `frontend/src/pages/settings/integrations/CarJamConfigPage.tsx` does NOT exist — ✅ verified

`fileSearch` for "CarJamConfigPage" returned **no files**. Spec is correct — the dedicated CarJam page doesn't exist; CarJam is rendered generically by `Integrations.tsx`.

### F8. `frontend/src/pages/common/FeatureNotAvailable.tsx` exists — ✅ verified

`fileSearch` for "FeatureNotAvailable" returned exactly one file: `frontend/src/pages/common/FeatureNotAvailable.tsx`. Imported and used by `frontend/src/components/common/ModuleRoute.tsx:4` as the disabled-module fallback. Spec is correct.

---

## Schema-shape claims

### S1. Organisation address fields are in `settings` JSONB — ✅ verified

`app/modules/admin/models.py:117`:
```python
settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
```

`Organisation` table (lines 85-..., with columns up to ~line 130) does NOT have `address_line_1`, `address_unit`, `address_street`, `address_city`, `address_state`, `address_postcode`, `phone`, `email`, `website`, `gst_number`, `primary_colour` as direct columns. All address/contact metadata lives inside the `settings` JSONB. Spec design §4.3a is correct.

### S2. `organisations.carjam_lookups_this_month` and `carjam_lookups_reset_at` exist — ✅ verified

`app/modules/admin/models.py:112-113`:
```python
carjam_lookups_this_month: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
carjam_lookups_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Both columns exist. Spec is correct that PPSR can mirror this pattern.

### S3. `subscription_plans.carjam_lookups_included` exists — ✅ verified

`app/modules/admin/models.py:57`:
```python
carjam_lookups_included: Mapped[int] = mapped_column(Integer, nullable=False)
```

✓

### S4. `subscription_plans.enabled_modules` is JSONB — ✅ verified

`app/modules/admin/models.py:58`:
```python
enabled_modules: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'[]'")
```

JSONB array (server-default `'[]'`). Spec's idempotent set-union pattern (`jsonb_agg(DISTINCT m)` from migration 0203) is the right approach.

### S5. `module_registry.setup_question` + `setup_question_description` exist — ✅ verified

`app/modules/module_management/models.py:41-42`:
```python
setup_question: Mapped[str | None] = mapped_column(Text, nullable=True)
setup_question_description: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Both columns exist with the exact names. ✓

### S6. `audit_log` table is singular — ✅ verified

Two confirmations:
- `app/core/audit.py:79`: `INSERT INTO audit_log (`
- `app/modules/admin/models.py` `class AuditLog` block: `__tablename__ = "audit_log"`

Singular, not plural `audit_logs`. Spec claim is correct everywhere it appears.

---

## API call-site claims

### A1. `apiClient` import path is `@/api/client` — ✅ verified

`frontend/src/api/client.ts` exists. Default export at line 171: `export default apiClient`. Path `@/api/client` resolves to that file (Vite alias).

### A2. `useToast` from `@/components/ui/Toast` — ✅ verified

`frontend/src/components/ui/Toast.tsx:77-91`:
```tsx
export function useToast() {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const addToast = useCallback((variant: ToastVariant, message: string, duration?: number) => {
    ...
  }, [])

  return { toasts, addToast, dismissToast }
}
```

API matches spec exactly: `addToast(variant, message, duration?)`.

### A3. `useModules` hook exists — ✅ verified (with line drift)

`frontend/src/contexts/ModuleContext.tsx:33`:
```tsx
export function useModules(): ModuleContextValue {
```

Returns `{ ..., isEnabled: (slug: string) => boolean, ... }` (interface declared at line 27; implementation at line 91-94). Used by `OrgLayout` at line **167** (spec said 161; **LOW** drift):
```tsx
if (item.module) return isEnabled(item.module)
```

### A4. `useBranch` hook + BranchContext shape — ✅ verified (not applicable)

Searched both `requirements.md` and `design.md` for `BranchContext|useBranch` → 0 matches in PPSR spec. Per the audit instruction "verify only if claimed", nothing to flag. PPSR is org-level data; the design correctly says "no `branch_id` on `ppsr_searches`" (R6.2 / §12 RBAC simplification).

---

## Code-Gap Items Summary

| ID | Severity | Spec location | Claim | Reality |
|---|---|---|---|---|
| **CG-1** | **HIGH** | `design.md §13` ("Migration sequencing — verified"), `tasks.md A1`, `tasks.md A2`, `tasks.md §Code-Verified Addendum A2` | "Current alembic head is **0206**"; PPSR migrations land as `0207_ppsr_module.py` + `0208_ppsr_indexes.py`. | Head is **0210** (`2026_05_31_0907-0210_payslip_indexes.py`). Slots 0207-0210 are taken by time-clock + payslip migrations. **PPSR must use `0211_ppsr_module.py` + `0212_ppsr_indexes.py`.** Naming `0207_ppsr_module.py` would clash with existing `0207_time_clock_schema.py`. |
| **CG-2** | **MEDIUM** | `design.md §10`, `design.md §13` ("Frontend code references — verified"), `tasks.md D9` | `frontend/src/pages/admin/SubscriptionPlans.tsx:1349` is "the form". | Line 1349 is `export function SubscriptionPlans()` — the **main page**. The form is `function PlanFormModal` at **line 338**. The `set('carjam_lookups_included', …)` pattern lives inside `PlanFormModal` (lines 338-454+), not inside the main page export. Implementer following the spec verbatim would land in the wrong function. |
| **CG-3** | **LOW** | `design.md §2`, `design.md §13` ("Module-gated route registration"), `tasks.md D8` | `frontend/src/App.tsx:414` is the VehicleProfile route. | VehicleProfile route is at **line 437** (`<Route path="/vehicles/:id" element={<SafePage name="vehicle-profile"><ModuleRoute moduleSlug="vehicles"><VehicleProfile /></ModuleRoute></SafePage>}`). Lazy import is at line 66. Line 414 sits inside the global-admin `<Route path="integrations">` block. Pattern matches spec; line number drift only. |
| **CG-4** | **LOW** | `design.md §13` ("Sidebar layout") | `OrgLayout.tsx:43-85` flat array; filter at line 161. | Array opens at **line 44** and closes at **line 90**; filter at **line 167**. Structural claim correct; line range and filter line both drift by ~6. |
| **CG-5** | **LOW** | `design.md §13` ("Verified-against-code addendum"), `tasks.md C7` | `_SAFE_FIELDS["carjam"]` at line 1734; `_MASKED_FIELDS["carjam"]` at line 1742. | Dict declarations at lines **1733** and **1741**; the `"carjam":` entries at **1735** and **1743**. One-line drift. |
| **CG-6** | **LOW** | `requirements.md R1.6`, `design.md §13` (implicit) | Middleware fail-open lives at `app/middleware/modules.py:95-97`. | Actual fail-open at **lines 96-102** (single block: `org_id = getattr(...)` on line 96, `if not org_id:` on line 99, `return` on line 102). Off by ~3 lines. There is also a second fail-open in the exception handler at lines 115-119 not mentioned by the spec. |
| **CG-7** | **LOW** | `requirements.md R1.5`, `design.md §1a` (table) | Module-gate 403 response at `app/middleware/modules.py:117-126`. | Actual 403 block at **lines 121-130** (just below the exception fail-open). Body shape `{detail, module}` correct. |
| **CG-8** | **LOW** | `design.md §13` ("Backend code references — verified") | `_load_carjam_client(db, redis)` spans `app/modules/vehicles/service.py:28-64`. | Function spans **lines 28-65** (closing `return CarjamClient(redis=redis)` is line 65). Off by 1. |
| **CG-9** | **LOW** | `tasks.md C9` | `app/middleware/rate_limit.py` constant `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = 30`. | Two separate constants exist: `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = "/api/v2/public/staff-roster/"` (string, line 71) and `_PUBLIC_STAFF_ROSTER_RATE_LIMIT = 30` (int, line 72). Spec wording conflates them. The PPSR addition needs **two** constants too: `_PPSR_SEARCH_PATH = "/api/v2/ppsr/search"` and `_PPSR_SEARCH_RATE_LIMIT = 10`. |
| **CG-10** | **LOW** | `design.md §4.1` ("CarjamClient.lookup_ppsr") | "delegate to existing `_parse_vehicle_response(rego, message.idh)` for parity". | The actual existing call passes `idh_data["vehicle"]` (the inner dict), not `message.idh` itself. PPSR parser must extract `idh.vehicle` (or the JSON-mode equivalent) before delegating. Semantic intent is right; argument shape is one nesting level off. |
| **CG-11** | **LOW** | `tasks.md A1` (`Verify` block) | `0203_staff_phase1_schema.py:254-276` is the feature_flags INSERT. | First INSERT spans **lines 255-281** (the `staff_management` mirror). Second INSERT (`payroll`) spans lines ~284-309. Spec range partly straddles both. Shape claim is correct. |

### Severity counts

- **HIGH:** 1 (CG-1 — migration revision number wrong; will collide on `alembic upgrade head`).
- **MEDIUM:** 1 (CG-2 — `SubscriptionPlans.tsx:1349` points at the wrong function; implementer needs to be redirected to `:338`).
- **LOW:** 9 (CG-3..CG-11 — line-number drift; structural intent is correct).

### Items with no gap

All other claims (`B1, B2, B3, B5, B6, B7, B8, B9, B11, B12, B13, B16, B18, B19, F1, F2, F3, F5, F7, F8, S1, S2, S3, S4, S5, S6, A1, A2, A3, A4`) verified clean. The §13 "Verified-against-code addendum" and tasks.md "Code-Verified Addendum" are largely accurate — the substantive claims (column shapes, return-type signatures, audit table singular, prop names, function names, JSONB patterns) all hold up.

---

## Reviewer notes

- The single mandatory fix before implementation starts is **CG-1** — bump the migration filenames to `0211_ppsr_module.py` + `0212_ppsr_indexes.py`. Without this, `alembic upgrade head` will fail on filename collision.
- **CG-2** is worth fixing because tasks.md D9 instructs the implementer to "extend [SubscriptionPlans.tsx:1349]", which lands in the wrong function. The correct landing site is `function PlanFormModal` at line 338.
- All LOW items are line-number drift only — code structure and patterns referenced are accurate; an implementer reading the surrounding context (and not blindly trusting line numbers) would recover. No structural rewrite needed.
- The spec's two addendums (design §13, tasks "Code-Verified Addendum") are well-grounded — the underlying audit was thorough; only the alembic revision number has decisively moved on since the audit was first written.

---

## Code-Gap Closure Log

Applied 2026-05-31 across `requirements.md`, `design.md`, `tasks.md`. The gap-analysis file itself is not modified; only the three spec docs were edited.

| ID | Severity | Closure | Edits |
|---|---|---|---|
| **CG-1** | HIGH | **Closed in commit (pending)** — migration filenames bumped to `0211_ppsr_module.py` + `0212_ppsr_indexes.py`; "head 0206" claims rewritten to "head is 0210 (post-payslip-merge)"; `§13` "Migration sequencing — verified" + `Code-Verified Addendum A2` + `G-CODE-17` row + design.md "Backend touches" + design.md §3.1/§3.2 headers all updated. | design.md (5), tasks.md (3) |
| **CG-2** | MEDIUM | **Closed in commit (pending)** — `SubscriptionPlans.tsx:1349` references redirected to `PlanFormModal` at line 338 in design.md §10, design.md §13, and tasks.md D9 + Code-Verified Addendum. Existing `:1527` table column reference left intact (correct). `:492-510` used for `carjam_lookups_included` pattern in tasks D9 (already correct). | design.md (2), tasks.md (2) |
| **CG-3** | LOW | **Closed in commit (pending)** — `App.tsx:414` → `App.tsx:437` in design.md §2, design.md §13, and tasks.md D8. | design.md (3), tasks.md (1) |
| **CG-4** | LOW | **Closed in commit (pending)** — `OrgLayout.tsx:43-85` → `OrgLayout.tsx:44-90`; insertion-point comment "line 46" → "line 47"; filter-line "line 161" → "line 167". design.md §2 + §13 + tasks.md D7 all updated. | design.md (3), tasks.md (1) |
| **CG-5** | LOW | **Closed in commit (pending)** — `admin/service.py:1734` → `:1735` (`_SAFE_FIELDS["carjam"]` entry); `:1742` → `:1743` (`_MASKED_FIELDS["carjam"]` entry). design.md "Backend touches" + design.md §13 + tasks.md C7 + Code-Verified Addendum + requirements.md R7.2 updated. | design.md (2), requirements.md (1), tasks.md (2) |
| **CG-6** | LOW | **Closed in commit (pending)** — `modules.py:95-97` → `modules.py:96-102` in requirements.md R1.6; second fail-open at lines 115-119 noted explicitly. Design.md §1a request-trace table reference updated to `79-130` with note about second fail-open. | design.md (1), requirements.md (1) |
| **CG-7** | LOW | **Closed in commit (pending)** — `modules.py:117-126` → `modules.py:121-130` in requirements.md R1.5, design.md §13 ("MODULE_ENDPOINT_MAP"), tasks.md C6 verify step. | design.md (1), requirements.md (1), tasks.md (1) |
| **CG-8** | LOW | **Closed in commit (pending)** — `vehicles/service.py:28-64` → `:28-65` (3 occurrences in design.md: §13 verified addendum, design.md §13 "Existing CarJam DB JSON config keys", and the inline service-code comment in §4.2). | design.md (3) |
| **CG-9** | LOW | **Closed in commit (pending)** — tasks.md C9 reworded to clarify the actual two-constant pattern (`_<NAME>_PATH = "..."` string + `_<NAME>_RATE_LIMIT = N` int); shows both `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = "/api/v2/public/staff-roster/"` (string, line 71) and `_PUBLIC_STAFF_ROSTER_RATE_LIMIT = 30` (int, line 72) as the example PPSR mirrors. | tasks.md (1) |
| **CG-10** | LOW | **Closed in commit (pending)** — design.md §4.1 parser bullet rewritten: "delegate to existing `_parse_vehicle_response(rego, idh_data["vehicle"])` for parity. Note: the existing `_parse_vehicle_response(rego, idh_data["vehicle"])` extracts the **inner** `idh.vehicle` dict, not `message.idh` itself. PPSR's parser must extract the equivalent inner block before delegating." | design.md (1) |
| **CG-11** | LOW | **Closed in commit (pending)** — `0203_staff_phase1_schema.py:254-276` → `:255-281` in requirements.md R1.2 and design.md §3.1 SQL comment + §13 verified-against-code addendum. | design.md (2), requirements.md (1) |

### Verification

After the edits, the following greps over `.kiro/specs/ppsr-module/{requirements,design,tasks}.md` return **zero matches**:

- `0207_ppsr_module|0208_ppsr_indexes`
- `head is 0206|head was 0206`
- `SubscriptionPlans\.tsx:1349` (the only remaining reference is descriptive prose explaining `:1349` is **not** the form)
- `App\.tsx:414`
- `OrgLayout\.tsx:43-85`
- `service\.py:1734|service\.py:1742` (admin/service)
- `modules\.py:95-97|modules\.py:117-126`
- `vehicles/service\.py:28-64`
- `_PUBLIC_STAFF_ROSTER_PATH_PREFIX = 30` (the conflated single-constant phrasing)
- `_parse_vehicle_response\(rego, message\.idh\)`
- `0203_staff_phase1_schema\.py:254-276`

Every claimed file:line pointer in the three spec files now matches the actual code at audit time (commit 2026-05-31, alembic head 0210).
