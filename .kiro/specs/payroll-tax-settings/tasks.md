# Implementation Plan: Payroll Tax Settings

## Overview

This plan delivers the two-tier, GUI-editable NZ payroll tax configuration described in
the design. It starts with a zero-behaviour-change refactor of the PAYE engine so the
existing test battery keeps passing, then builds the pure layers (validation, resolution)
that have universal correctness properties, then the persistence/audit/router layers, the
seed migration, the payslip wiring, and finally the two frontend surfaces. Each step
builds on the previous one and ends by wiring the new code into an existing call site, so
there is no orphaned code and no big-bang integration at the end.

Backend: Python 3.11 / FastAPI / SQLAlchemy (async) / Alembic / PostgreSQL with RLS.
Frontend: React + TypeScript in `frontend-v2/`. Backend tests run via `pytest` inside the
app container; property tests use Hypothesis (`max_examples >= 100`). Frontend tests use
`vitest`.

## Tasks

- [x] 1. Refactor the PAYE engine to be configuration-driven (zero behaviour change)
  - [x] 1.1 Introduce config dataclasses and the `SAFETY_NET` instance in `app/modules/timesheets/paye.py`
    - Add `@dataclass(frozen=True)` `PAYEBracket` (`upper_limit: Decimal | None`, `rate: Decimal`), `IETCParams` (`amount`, `lower`, `abatement_start`, `abatement_rate`, `upper`), and `ResolvedTaxConfig` (`paye_brackets`, `secondary_rates`, `acc_levy_rate`, `acc_max_liable_earnings`, `student_loan_rate`, `student_loan_threshold`, `ietc`, `default_kiwisaver_employee_rate`, `default_kiwisaver_employer_rate`, `tax_year_label`)
    - Construct a module-level `SAFETY_NET: ResolvedTaxConfig` from the existing 2024/25 constants (`_INCOME_TAX_BRACKETS`, `_SECONDARY_FLAT_RATES`, `_ACC_LEVY_RATE`, `_ACC_MAX_LIABLE_EARNINGS`, `_STUDENT_LOAN_RATE`, `_STUDENT_LOAN_ANNUAL_THRESHOLD`, IETC constants, 3.00 KiwiSaver defaults, label "2024/25"); the open-ended top band uses `upper_limit=None` (convert the current `Decimal("Infinity")` top band)
    - Extract the IETC upper bound (currently the inline literal `Decimal("48000")` in `_ietc_annual`) into `IETCParams.upper`; the other four IETC values already exist as constants (`_IETC_AMOUNT`, `_IETC_LOWER`, `_IETC_ABATEMENT_START`, `_IETC_ABATEMENT_RATE`)
    - Keep the legacy constants as the single source for this instance
    - _Requirements: 1.2, 5.4_

  - [x] 1.2 Read every rate from `config` inside `compute_paye`
    - Add a `config: ResolvedTaxConfig = SAFETY_NET` keyword parameter; change `kiwisaver_employee_rate`/`kiwisaver_employer_rate` defaults to `None`
    - Drive `_annual_income_tax` from `config.paye_brackets` — treat a bracket with `upper_limit is None` as the open-ended top band (infinity); the current `annual < upper` comparison must not run against `None` (would raise `TypeError`). Secondary lookup from `config.secondary_rates`; ACC from `config.acc_levy_rate`/`config.acc_max_liable_earnings`; student loan from `config.student_loan_rate`/`config.student_loan_threshold`; IETC from `config.ietc` (including `config.ietc.upper` for the abatement ceiling)
    - When the caller passes `None` for a KiwiSaver rate, use `config.default_kiwisaver_employee_rate` / `config.default_kiwisaver_employer_rate`
    - Default `config=SAFETY_NET` guarantees existing callers and tests produce identical numbers
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 1.3 Write engine regression test (zero-behaviour-change cutover)
    - With the default `config=SAFETY_NET`, assert `compute_paye` reproduces current numbers for a battery of representative inputs (primary M/ME, each secondary code, with/without student loan, several period lengths and gross amounts)
    - _Requirements: 1.2, 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 1.4 Write property test for the config-driven engine
    - **Property 13: The PAYE engine honours the resolved configuration**
    - Metamorphic, pure/in-memory: generate a valid `ResolvedTaxConfig` and a pay input, then change a single field (a bracket rate, secondary rate, ACC rate/cap, SL rate/threshold, an IETC param, a KiwiSaver default) and assert the corresponding output moves as the rate math predicts
    - Tag: `# Feature: payroll-tax-settings, Property 13: ...`; `max_examples >= 100`
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7**

- [x] 2. Create the `payroll_tax` module data layer
  - [x] 2.1 Add ORM models in `app/modules/payroll_tax/models.py`
    - `PlatformTaxDefault`: `id` uuid PK, `is_singleton` bool NOT NULL DEFAULT true UNIQUE, `config` JSONB NOT NULL, `tax_year_label` text NOT NULL, `created_at`/`updated_at` timestamptz, `updated_by` uuid nullable (no RLS)
    - `OrgTaxSettings`: `id` uuid PK, `org_id` uuid NOT NULL UNIQUE, `overrides` JSONB NOT NULL DEFAULT `{}`, `created_at`/`updated_at`, `updated_by` uuid (RLS table)
    - Create `app/modules/payroll_tax/__init__.py`
    - _Requirements: 1.1, 3.4_

  - [x] 2.2 Add Pydantic schemas in `app/modules/payroll_tax/schemas.py`
    - Tax-field shapes (`PAYEBracketSchema`, `IETCParamsSchema`, secondary-rate map), `PlatformTaxDefaultView`, `PlatformTaxDefaultUpdate`, sparse `OrgOverridesUpdate`, `OrgTaxSettingsView` (per-field effective value + `inherited`/`override` flag), and `FieldError(field, message)`
    - Decimals serialize as JSON numbers and rehydrate via `Decimal(str(...))`
    - _Requirements: 2.1, 4.3_

- [x] 3. Implement tax-configuration validation (pure)
  - [x] 3.1 Implement `validate_config_fragment` in `app/modules/payroll_tax/validation.py`
    - Pure function over any sparse `fragment: dict`; validates only present fields; returns `list[FieldError]`
    - Brackets: at least one band (7.4); every finite `upper_limit > 0` (7.5); finite limits strictly ascending (7.1); exactly one open-ended top band, last (7.2); every `rate` in `[0, 1]` (7.3)
    - Rates in bounds (`[0,1]`; KiwiSaver percent `[0,100]`) (8.1); `acc_max_liable_earnings > 0` (8.2); `student_loan_threshold >= 0` (8.3); IETC `lower <= abatement_start <= upper` (8.4); secondary set, when present, contains all of SB,S,SH,ST,SA (8.5)
    - Each `FieldError` names the field with a human-readable message (8.6); wrap message generation in `try/except` substituting a generic message so an invalid submission is still rejected (8.7)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 3.2 Write property test for PAYE bracket validation
    - **Property 10: Invalid PAYE bracket sets are rejected and not persisted**
    - Generate bracket sets violating each rule (empty set, non-positive finite limit, non-ascending limits, no/!=1 open-ended top band, rate outside `[0,1]`) and assert a non-empty error list; generate valid sets and assert `[]`
    - Tag: `# Feature: payroll-tax-settings, Property 10: ...`; `max_examples >= 100`
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

  - [x] 3.3 Write property test for rate/cap/threshold/IETC/secondary validation
    - **Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted**
    - Generate out-of-bounds rates, non-positive ACC cap, negative SL threshold, mis-ordered IETC bounds, and incomplete secondary maps; assert each yields a validation error and that valid fragments pass
    - Tag: `# Feature: payroll-tax-settings, Property 11: ...`; `max_examples >= 100`
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

  - [x] 3.4 Write property test for validation messages
    - **Property 12: Validation errors identify the failing field**
    - For any invalid fragment, assert every returned error names a recognised Tax_Field and carries a non-empty message
    - Tag: `# Feature: payroll-tax-settings, Property 12: ...`; `max_examples >= 100`
    - **Validates: Requirements 8.6**

- [x] 4. Implement the resolution service (pure over stored rows)
  - [x] 4.1 Implement `resolve_tax_config` in `app/modules/payroll_tax/resolution.py`
    - `async def resolve_tax_config(db, org_id) -> ResolvedTaxConfig`: load the single `platform_tax_default` row and the org's `org_tax_settings` row (may be absent)
    - Add a pure `_resolve_field(field_key, org_overrides, platform_config, safety_net_value)` helper applying precedence: org override → platform value → Safety_Net, field by field
    - Coerce each field via typed parsing (`Decimal(str(...))`, bracket/IETC construction); a field that fails to parse or is missing falls through to the next tier (log fallback at `warning`); a missing platform row falls through every field to `SAFETY_NET`
    - Always return a fully-populated `ResolvedTaxConfig`; ignore pay-period dates
    - _Requirements: 1.4, 3.1, 3.3, 5.1, 5.2, 5.3, 5.4, 11.1, 11.2, 11.3, 11.4, 12.2_

  - [x] 4.2 Write property test for resolution precedence
    - **Property 1: Field-wise resolution precedence**
    - Generate a platform config, a sparse override map (each field independently present/absent), and assert each resolved field equals override-else-platform-else-Safety_Net, never zero/blank when a higher tier is absent; when all tiers absent the result equals `SAFETY_NET`
    - Tag: `# Feature: payroll-tax-settings, Property 1: ...`; `max_examples >= 100`
    - **Validates: Requirements 1.4, 2.5, 3.1, 3.3, 5.1, 5.2, 5.3, 11.2, 11.3**

  - [x] 4.3 Write property test for resolution totality
    - **Property 2: Resolution is total (never blank)**
    - For any stored state (missing org row, platform row missing arbitrary fields), assert every Tax_Field in the returned config is non-null/non-blank
    - Tag: `# Feature: payroll-tax-settings, Property 2: ...`; `max_examples >= 100`
    - **Validates: Requirements 5.4, 11.1**

  - [x] 4.4 Write property test for deterministic, date-independent resolution
    - **Property 3: Resolution is deterministic and date-independent**
    - For fixed stored config, assert repeated resolution (and any pay-period dates) yields identical results equal to an independent reference application of the precedence
    - Tag: `# Feature: payroll-tax-settings, Property 3: ...`; `max_examples >= 100`
    - **Validates: Requirements 11.4, 12.2**

- [x] 5. Create the seed migration and database tables
  - [x] 5.1 Add idempotent Alembic migration revision `0231` (down-revision `0230`)
    - `CREATE TABLE IF NOT EXISTS platform_tax_default (...)` and `org_tax_settings (...)` per the data model
    - Enable RLS on `org_tax_settings`; `DROP POLICY IF EXISTS` then `CREATE POLICY tenant_isolation` keyed on `current_setting('app.current_org_id', true)::uuid`; create index `ix_org_tax_settings_org`
    - Seed the single platform row from the 2024/25 constants via `INSERT ... WHERE NOT EXISTS (SELECT 1 FROM platform_tax_default)` (left untouched if a row already exists); `downgrade()` drops the policy then the tables
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 5.2 Write seed-migration tests
    - Assert the seeded row contains the exact 2024/25 values (1.2); re-running the seed with an existing row leaves it unchanged (1.3); a second platform insert conflicts on `is_singleton` (1.1)
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 5.3 Write RLS smoke test for `org_tax_settings`
    - With `app.current_org_id` set to org A, assert org B's `org_tax_settings` row is not visible (reinforces tenant isolation)
    - _Requirements: 3.4_

- [x] 6. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement the persistence and audit service
  - [x] 7.1 Implement platform-tier service functions in `app/modules/payroll_tax/service.py`
    - `get_platform_default(db)` and `update_platform_default(db, *, fields, user_id, request)`: validate first (non-empty errors → `HTTPException(422, detail=[{field, message}])`, no write); on success compute per-field before/after diff, `flush` + `refresh`, and `write_audit_log(... org_id=None ...)` with prior and new values
    - _Requirements: 2.2, 2.4, 10.2_

  - [x] 7.2 Implement org-tier service functions in `app/modules/payroll_tax/service.py`
    - `get_org_resolved_view(db, *, org_id)` returns effective value + inherited/override flag per field; `set_org_overrides(...)` validates then persists sparse `overrides` (flush+refresh) and audits prior/new; `reset_org_field(...)` removes one key; `reset_org_all(...)` sets `overrides` to `{}`; resets audit the prior override value and that the field now inherits
    - _Requirements: 3.2, 3.3, 4.3, 9.1, 9.2, 9.3, 10.1_

  - [x] 7.3 Write property test for persistence round-trip
    - **Property 4: Persistence round-trip**
    - For valid platform configs and valid sparse override sets submitted via the service, assert reading back (resolution / settings view) returns the submitted values
    - Exercises the service against a test session; tag: `# Feature: payroll-tax-settings, Property 4: ...`; `max_examples >= 100`
    - **Validates: Requirements 2.2, 3.2**

  - [x] 7.4 Write property test for audited changes
    - **Property 7: Every successful change is audited with prior and new values**
    - For any successful platform save, org override save, or reset, assert an `audit_log` row records acting user, org (for org actions), changed field(s), prior value(s), and new value(s) (reset records prior override + now-inherits)
    - Tag: `# Feature: payroll-tax-settings, Property 7: ...`; `max_examples >= 100`
    - **Validates: Requirements 2.4, 9.3, 10.1, 10.2**

  - [x] 7.5 Write property test for reset round-trip
    - **Property 8: Reset round-trip restores inheritance**
    - For an org with overrides, assert resetting a field (or all) removes the override(s) so the field(s) resolve to the platform default and report as inherited
    - Tag: `# Feature: payroll-tax-settings, Property 8: ...`; `max_examples >= 100`
    - **Validates: Requirements 9.1, 9.2, 9.4**

  - [x] 7.6 Write property test for the org settings view
    - **Property 9: Org settings view reflects resolution and inheritance status**
    - For any platform config + sparse overrides, assert the view's per-field effective value equals the resolved value and marks override exactly when the field is present in overrides, else inherited
    - Tag: `# Feature: payroll-tax-settings, Property 9: ...`; `max_examples >= 100`
    - **Validates: Requirements 4.3, 9.4**

  - [x] 7.7 Write append-only audit retention test
    - Assert `audit_log` rejects `UPDATE` and `DELETE` (append-only), confirming tax-config change history is retained. The immutability is `REVOKE UPDATE, DELETE ... FROM PUBLIC` (migration 0008), which PostgreSQL table owners/superusers bypass — so run this assertion over a connection using the app's actual non-owner runtime DB role, not a superuser/owner session, or it will spuriously pass writes
    - _Requirements: 10.3_

- [x] 8. Implement routers and authorisation auditing
  - [x] 8.1 Implement the org-tier `audit_denied_tax_access` dependency and the platform-tier middleware denial audit
    - **Org tier** — in `app/modules/payroll_tax/dependencies.py`, implement `audit_denied_tax_access` modelled on `require_global_admin_with_audit`: check `role == "org_admin"`, and on mismatch write a `payroll_tax.org.access_denied` `audit_log` entry **out-of-band** (fresh `async_session_factory()` session, since the request session may be rolled back on a 403) then raise `403`. This is the **sole** gate on the org routes — do NOT also attach `require_role("org_admin")` (it would 403 before the audit runs). Guard the audit write so an audit failure never turns a correct 403 into a 500
    - **Platform tier** — a route dependency cannot satisfy Req 2.3 because `RBACMiddleware` 403s every non-`global_admin` role on `/api/v2/admin/*` before the route runs. Extend `RBACMiddleware` (`app/middleware/rbac.py`) — or add a thin middleware ahead of it — to write a `payroll_tax.platform.access_denied` `audit_log` entry (out-of-band, guarded) when it denies a request whose path starts with `/api/v2/admin/platform-tax-default`
    - _Requirements: 2.3, 3.5_

  - [x] 8.2 Implement platform and org routers in `app/modules/payroll_tax/router.py`
    - Platform router: `GET` and `PUT /api/v2/admin/platform-tax-default`. Effective auth is `global_admin`, enforced by `RBACMiddleware` (path gate) plus a defence-in-depth `require_role("global_admin")` on the routes; the denial audit is handled in the middleware (task 8.1), not here
    - Org router: `GET` and `PUT /api/v2/payroll-tax-settings`, `DELETE /api/v2/payroll-tax-settings/{field}`, `DELETE /api/v2/payroll-tax-settings`. Gate **only** with `audit_denied_tax_access` (it performs the `org_admin` check + denial audit + 403). Do NOT also add `require_role("org_admin")` — pairing them risks the 403 firing before the audit
    - Handlers delegate to the service; 422 returns per-field detail
    - _Requirements: 2.1, 2.2, 2.3, 3.2, 3.5, 4.3, 9.1, 9.2_

  - [x] 8.3 Register both routers in `app/main.py`
    - `include_router(platform_router, prefix="/api/v2/admin/platform-tax-default")` and `include_router(org_router, prefix="/api/v2/payroll-tax-settings")`
    - _Requirements: 2.1, 4.3_

  - [x] 8.4 Write property test for unauthorised access
    - **Property 6: Unauthorised access is rejected and audited**
    - For any role other than `global_admin` (platform tier) / `org_admin` (org tier), assert view/modify is rejected with an auth error, nothing is persisted, and an access-denied `audit_log` entry is recorded
    - Tag: `# Feature: payroll-tax-settings, Property 6: ...`; `max_examples >= 100`
    - **Validates: Requirements 2.3, 3.5**

  - [x] 8.5 Write example tests for platform endpoints
    - Platform `GET` returns every documented field (2.1); a forced message-builder fault still rejects and persists nothing (8.7)
    - _Requirements: 2.1, 8.7_

- [x] 9. Wire resolution into payslip computation
  - [x] 9.1 Call `resolve_tax_config` in `app/modules/payslips/calc.py`
    - In `compute_payslip`, call `resolve_tax_config(db, org_id)` once (`org_id = staff.org_id`) and pass the result into `compute_paye(config=...)`; pass staff KiwiSaver rates as `None` when unset so the engine uses the resolved defaults
    - **Critical (Req 6.6/6.7):** the payslip's KiwiSaver lines are produced by calc.py's **own** block (`kiwisaver_employee = gross * (_q(staff.kiwisaver_employee_rate)/100)`), and `paye_result.kiwisaver_*` is discarded. Update that own block to fall back to the resolved `default_kiwisaver_employee_rate` / `default_kiwisaver_employer_rate` when `staff.kiwisaver_employee_rate` / `_employer_rate` is `None` (today `_q(None)` → `0.00` → 0%). Passing `None` into `compute_paye` alone does NOT change the payslip numbers
    - _Requirements: 5.1, 6.1, 6.6, 6.7_

  - [x] 9.2 Write end-to-end resolution-into-payslip test
    - Assert a platform rate change flows through resolution into a generated payslip's numbers for a non-overriding org (2.5), and an org override changes only that org's payslip (3.3)
    - _Requirements: 2.5, 3.3_

- [x] 10. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Build the Global Admin platform tax editor (frontend-v2)
  - [x] 11.1 Create the editor page and API client
    - Add `frontend-v2/src/api/payrollTax.ts` typed client covering both platform and org endpoints (consume responses with `?.` / `?? []` / `?? 0`)
    - Add `frontend-v2/src/pages/admin/PayrollTaxDefault.tsx`: fetch `GET /api/v2/admin/platform-tax-default`; editable controls for the bracket table (add/remove rows; last row is the open-ended top band), five secondary rates, ACC rate + cap, SL rate + threshold, five IETC params, two KiwiSaver defaults, and the tax-year label; `PUT` on save; render per-field 422 messages
    - _Requirements: 2.1, 2.2_

  - [x] 11.2 Route and link the editor in the Global Admin area
    - Add the route under the admin layout in `App.tsx` and a navigation link alongside `XeroCredentialsSettings.tsx` (e.g. in `AdminLayout.tsx`/integrations nav)
    - _Requirements: 2.1_

  - [x] 11.3 Write rendering tests for the platform editor (vitest)
    - Render with mocked data: all documented fields appear; a 422 response renders per-field inline errors
    - _Requirements: 2.1, 2.2_

- [x] 12. Build the Payroll-page org tax settings (frontend-v2)
  - [x] 12.1 Add the Settings control to `frontend-v2/src/pages/payroll/PayRunPage.tsx`
    - Add a Settings control to the `.page-head` actions mirroring `TimesheetsPage.tsx`, rendered only when `user.role === 'org_admin'` and omitted otherwise; it navigates to `/payroll/tax-settings` (the payroll console is at `/payroll/run`; `/payroll/tax-settings` is a new sibling route — `/payroll` itself is not a route)
    - _Requirements: 4.1, 4.2_

  - [x] 12.2 Create `frontend-v2/src/pages/payroll/PayrollTaxSettings.tsx`
    - Fetch `GET /api/v2/payroll-tax-settings`; per field show the effective value and an Inherited/Override badge; editing issues `PUT`; per-field "Reset to default" issues the field `DELETE`; "Reset all" issues the collection `DELETE`; after reset the field re-renders as Inherited showing the platform value
    - `tax_year_label` is platform-only: render it as always **Inherited** with no override/edit/reset control
    - _Requirements: 4.3, 9.1, 9.2, 9.4_

  - [x] 12.3 Route the org settings view
    - Add the `/payroll/tax-settings` route in `App.tsx`
    - _Requirements: 4.1_

  - [x] 12.4 Write rendering tests for the Payroll settings surfaces (vitest)
    - Settings control renders for `org_admin` (4.1) and is omitted for other roles (4.2); the org view shows Inherited vs Override badges per field and re-renders a reset field as Inherited (9.4)
    - _Requirements: 4.1, 4.2, 9.4_

- [ ] 13. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references the specific requirement clauses (and, for tests, the design correctness property) it covers, for traceability.
- Properties 1–3 and 10–13 are pure in-memory tests; Properties 4–9 exercise the service/router layers against a test session and inspect `audit_log` rows.
- Step 1 is a zero-behaviour-change cutover: `config` defaults to `SAFETY_NET`, so the existing PAYE test battery must keep passing before any new tier is added.
- Checkpoints (tasks 6, 10, 13) ensure incremental validation before moving between layers.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.2"] },
    { "id": 1, "tasks": ["1.2", "3.1", "4.1", "5.1"] },
    { "id": 2, "tasks": ["1.3", "1.4", "3.2", "3.3", "3.4", "4.2", "4.3", "4.4", "5.2", "5.3", "7.1"] },
    { "id": 3, "tasks": ["7.2", "8.1", "9.1"] },
    { "id": 4, "tasks": ["8.2", "7.3", "7.4", "7.5", "7.6", "7.7"] },
    { "id": 5, "tasks": ["8.3", "9.2", "11.1"] },
    { "id": 6, "tasks": ["8.4", "8.5", "11.2", "12.1", "12.2"] },
    { "id": 7, "tasks": ["12.3", "11.3"] },
    { "id": 8, "tasks": ["12.4"] }
  ]
}
```
