# Requirements Document

## Introduction

The redesigned Pay Run console (`frontend-v2/src/pages/payroll/PayRunPage.tsx`, route `/payroll/run`) is the admin screen for reviewing and finalising payslips for a pay period. The design reference (`OraInvoice_Handoff/app/Payroll.html`) shows per-employee **PAYE**, **KiwiSaver**, and **ACC** figures in the payslip table and a **"KiwiSaver + ACC"** KPI summary across the run.

Today those figures cannot be rendered on this screen. The list endpoint `GET /api/v2/pay-periods/{period_id}/payslips` returns `PayslipResponse`, which carries only `gross_pay`, `gross_ytd`, and `net_pay` — it has **no deduction breakdown**. The per-deduction amounts exist only as individual `payslip_deductions` rows (`kind`, `amount`), and those are hydrated solely by the detail endpoint (`GET /api/v2/payslips/{id}` via `_serialise_payslip_detail`), i.e. one payslip at a time inside the drawer. As a result the redesigned list currently collapses everything into a single derived "Tax & deductions" figure (`gross − net`), which cannot distinguish PAYE from KiwiSaver from ACC and silently miscounts the employer KiwiSaver contribution (which does not reduce net pay).

This feature exposes **per-payslip deduction subtotals** on the admin payslip list responses so the Pay Run screen can render the PAYE / KiwiSaver / ACC split and the matching KPI, without losing or fabricating any figure. The subtotals are derived from the existing `payslip_deductions` rows — the established source of truth — so there is no change to how deductions are calculated or stored.

This document specifies WHAT the feature must do. Implementation specifics (the exact aggregation query, the precise nested schema shape, how the three named groups map onto the seven deduction kinds, and which list endpoints are populated) are resolved in the design phase; the genuinely ambiguous product decisions are flagged as **Open Decisions for Design** in Requirement 7.

## Glossary

- **Payslips_Service**: The backend payslips module (`app/modules/payslips/`) responsible for pay periods, payslips, deduction lines, and their API responses.
- **Pay_Run_Screen**: The redesigned admin console at `frontend-v2/src/pages/payroll/PayRunPage.tsx` (route `/payroll/run`), module-gated by `payroll`.
- **Deduction_Line**: A row in `payslip_deductions` (`payslip_id`, `kind`, `label`, `amount`). The authoritative per-payslip record of a single deduction.
- **Deduction_Kind**: One of the seven enum values defined in `app/modules/payslips/schemas.py` / models (`DeductionKind` CHECK constraint): `paye`, `acc_levy`, `kiwisaver_employee`, `kiwisaver_employer`, `student_loan`, `child_support`, `voluntary`.
- **Deduction_Subtotals**: A per-payslip aggregate giving the summed `amount` for each Deduction_Kind, derived from that payslip's Deduction_Lines.
- **Payslip_List_Response**: The `{ items, total }` envelope (`PayslipListResponse`) returned by the admin payslip list endpoints, whose items are `PayslipResponse` records.
- **Admin_List_Endpoints**: The admin-facing endpoints that return `PayslipListResponse` — period payslip listing (`GET /api/v2/pay-periods/{period_id}/payslips`), draft generation (`POST /api/v2/pay-periods/{period_id}/payslips`), and per-staff payslip history (`GET /api/v2/staff/{staff_id}/payslips`).
- **Self_Service_Surface**: The redacted employee-facing payslip endpoints (`GET /api/v2/staff/me/payslips` and its detail) returning `MyPayslipResponse` / `MyPayslipDetailResponse`, which deliberately exclude internal fields.
- **Employer_KiwiSaver**: The `kiwisaver_employer` Deduction_Line — informational only; it is NOT subtracted from `net_pay` (see `compute_payslip` in `app/modules/payslips/calc.py`).
- **Net_Affecting_KiwiSaver**: The `kiwisaver_employee` Deduction_Line — the KiwiSaver amount that reduces the employee's net pay.
- **Other_Deductions**: The grouping of `student_loan`, `child_support`, and `voluntary` Deduction_Kinds, surfaced as a single combined figure on the Pay_Run_Screen table while remaining individually available in the response.

## Requirements

### Requirement 1: Expose Per-Payslip Deduction Subtotals on the Admin List

**User Story:** As a payroll admin reviewing a pay run, I want each employee row to show how much of their pay is PAYE, KiwiSaver, and ACC, so that I can review the deductions for the whole period without opening every payslip individually.

#### Acceptance Criteria

1. WHEN a client requests an Admin_List_Endpoint, THE Payslips_Service SHALL include, for each payslip item, a Deduction_Subtotals value derived from that payslip's Deduction_Lines.
2. THE Deduction_Subtotals SHALL provide a separate summed amount for each of the seven Deduction_Kinds.
3. WHERE a payslip has no Deduction_Line of a given Deduction_Kind, THE Payslips_Service SHALL report that kind's subtotal as zero rather than omitting it.
4. THE Payslips_Service SHALL compute each Deduction_Subtotals value as the sum of `amount` across all Deduction_Lines of that kind for that payslip.
5. THE Payslips_Service SHALL keep `kiwisaver_employee` and `kiwisaver_employer` as separate values within the Deduction_Subtotals.

### Requirement 2: Derive Subtotals From the Existing Source of Truth

**User Story:** As a business owner, I want the deduction figures on the pay-run screen to always match the underlying payslip, so that the summary can never drift from the real deductions.

#### Acceptance Criteria

1. THE Payslips_Service SHALL derive Deduction_Subtotals exclusively from existing `payslip_deductions` rows.
2. THE Payslips_Service SHALL NOT introduce a separate stored copy of the subtotals that could diverge from the Deduction_Lines.
3. THE Payslips_Service SHALL NOT change how deductions are calculated, attached, or persisted.
4. WHEN a payslip's Deduction_Lines change, THE Deduction_Subtotals returned on the next list request SHALL reflect that change without any additional recomputation step.

### Requirement 3: Pay Run Screen Renders the PAYE / KiwiSaver / ACC Split

**User Story:** As a payroll admin, I want the pay-run table and summary to show PAYE, KiwiSaver, and ACC distinctly, so that the screen matches the intended payroll design and gives me an accurate breakdown.

#### Acceptance Criteria

1. WHEN the Pay_Run_Screen displays a period's payslips, THE Pay_Run_Screen SHALL show, per employee row, a PAYE amount, a KiwiSaver amount, and an ACC amount sourced from that payslip's Deduction_Subtotals.
2. THE Pay_Run_Screen SHALL source the per-row KiwiSaver amount from the Net_Affecting_KiwiSaver subtotal.
3. THE Pay_Run_Screen SHALL present the Other_Deductions grouping as a single combined per-row figure such that no Deduction_Kind is hidden from the admin.
4. WHEN the Pay_Run_Screen shows the period KPI summary, THE Pay_Run_Screen SHALL show a PAYE total and a combined KiwiSaver-plus-ACC total aggregated across the period's payslips.
5. THE Pay_Run_Screen SHALL compute the combined KiwiSaver-plus-ACC KPI as the sum of Net_Affecting_KiwiSaver, Employer_KiwiSaver, and ACC across the period's payslips.
6. THE Pay_Run_Screen SHALL replace the previous single derived "Tax & deductions" (`gross − net`) figure with the breakdown sourced from Deduction_Subtotals.
7. THE Pay_Run_Screen SHALL include the per-deduction breakdown in its CSV export of the period's payslips.

### Requirement 4: Safe Consumption and Defensive Defaults

**User Story:** As a developer, I want the new field consumed defensively, so that a payslip with missing or partial data never crashes the pay-run screen.

#### Acceptance Criteria

1. WHERE the Deduction_Subtotals or any of its values are absent from a response item, THE Pay_Run_Screen SHALL treat the missing value as zero and SHALL NOT throw.
2. THE Pay_Run_Screen SHALL access every Deduction_Subtotals value using the project's safe-consumption patterns (optional chaining and zero fallbacks per `safe-api-consumption.md`).
3. THE Pay_Run_Screen SHALL field-name-align its consumption of the Deduction_Subtotals with the backend Pydantic schema.

### Requirement 5: No Regression to Existing Payslip Consumers

**User Story:** As a platform operator, I want adding deduction subtotals to be backward compatible, so that existing screens and self-service flows that read payslips keep working unchanged.

#### Acceptance Criteria

1. WHEN an existing consumer reads a `PayslipResponse` without referencing the new Deduction_Subtotals, THE response SHALL remain valid and SHALL NOT break that consumer.
2. THE Payslips_Service SHALL keep the existing `gross_pay`, `gross_ytd`, and `net_pay` fields unchanged in shape and meaning.
3. THE Payslips_Service SHALL keep the payslip detail response's nested `deductions` line list unchanged in shape and content; WHERE the detail response inherits the Deduction_Subtotals field (because `PayslipDetailResponse` extends `PayslipResponse`), THE Payslips_Service SHALL populate it from that payslip's already-loaded Deduction_Lines so the detail subtotals are consistent rather than zero.
4. WHERE the new field is added to a schema shared by multiple endpoints, THE Payslips_Service SHALL ensure every endpoint returning that schema serialises without error.

### Requirement 6: Multi-Tenant and Role Scoping Preserved

**User Story:** As a platform operator, I want the subtotals to respect the same access controls as the payslips they describe, so that no deduction data leaks across organisations or roles.

#### Acceptance Criteria

1. THE Payslips_Service SHALL scope the Deduction_Subtotals aggregation to the same organisation as the payslips being listed.
2. THE Payslips_Service SHALL NOT aggregate any Deduction_Line that belongs to a payslip outside the requesting organisation.
3. THE Payslips_Service SHALL preserve the existing role and module gating (`payroll`) of the Admin_List_Endpoints.

### Requirement 7: Self-Service Scope and Open Decisions for Design

**User Story:** As a product owner, I want the scope of the new subtotals defined, so that the admin experience is consistent without unnecessarily expanding the redacted employee-facing surface.

#### Acceptance Criteria

1. THE Payslips_Service SHALL make a definite, documented decision in the design about whether the Self_Service_Surface also exposes Deduction_Subtotals.
2. WHERE the design excludes the Self_Service_Surface, THE Payslips_Service SHALL leave `MyPayslipResponse` / `MyPayslipDetailResponse` unchanged.

#### Open Decisions for Design (to be resolved in the design phase)

- **D1 — Nested shape:** Whether Deduction_Subtotals is a nested object keyed by Deduction_Kind, a flat set of fields on `PayslipResponse`, or a list of `{ kind, amount }` pairs. **Resolved direction:** a nested object with one field per Deduction_Kind (reusing the `DeductionKind` enum names), each defaulting to zero, plus a `total` exposed as a derived/computed field (sum of the seven) so it can never disagree with the parts. The design MUST fix the exact field names so the frontend can align.
- **D2 — Aggregation mechanism:** Whether subtotals are computed on read via a single grouped query over `payslip_deductions`, or denormalised onto the `payslips` table via a migration. **Resolved direction:** compute-on-read (no migration, no denormalisation) to guarantee Requirement 2.2 and avoid drift; the design MUST confirm there is no N+1 (one aggregate query per list call, not per row).
- **D3 — Endpoint scope:** Which of the Admin_List_Endpoints are populated (period list only, or also generate + per-staff history). **Resolved direction:** all admin endpoints returning `PayslipListResponse`, for a consistent admin experience.
- **D4 — Self-service scope:** Whether `MyPayslip*` is extended (Requirement 7). **Resolved direction:** excluded from this feature; the self-service surface stays redacted and unchanged.
- **D5 — "Other" grouping:** Whether `student_loan` / `child_support` / `voluntary` get their own columns or are folded into a single "Other" column on the table. **Resolved direction:** exposed individually in the API, but folded into one "Other" column in the table to keep it readable, with nothing hidden.

## Non-Functional Requirements

### NFR 1: Backward Compatibility and Data Safety

1. THE Payslips_Service SHALL add the Deduction_Subtotals field with a safe default so existing `PayslipResponse.model_validate(orm_row)` paths continue to serialise without error.
2. THE Payslips_Service SHALL NOT require any database migration to deliver this feature.
3. THE Payslips_Service SHALL leave the deduction calculation and persistence paths (`calc.py`, `service.py` attach logic) unchanged.

### NFR 2: Backend Implementation Patterns

1. THE Payslips_Service SHALL implement the aggregation using async SQLAlchemy consistent with the existing payslips module.
2. THE Payslips_Service SHALL aggregate all payslips in a single list call using one grouped query, avoiding a per-row (N+1) query.
3. THE Payslips_Service SHALL add the new field to the Pydantic response schema (not only to a service dict), per the Pydantic schema gate in `frontend-backend-contract-alignment.md` (Rule 8).
4. THE Payslips_Service SHALL return responses in the project's wrapped `{ items, total }` shape.

### NFR 3: Frontend Safety

1. WHERE the Pay_Run_Screen consumes the Deduction_Subtotals, THE frontend SHALL apply the safe API consumption patterns in `safe-api-consumption.md` (typed generics, optional chaining, `?? 0` fallbacks, `AbortController` cleanup, no `as any`).
2. THE frontend SHALL field-name-align its TypeScript type with the backend Pydantic schema.

### NFR 4: Numeric Correctness

1. THE Payslips_Service SHALL represent each Deduction_Subtotals amount with the same monetary precision as the underlying `payslip_deductions.amount` (two-decimal currency).
2. THE Payslips_Service SHALL serialise monetary subtotals on the wire consistently with the rest of the payslips API (decimal-as-string convention).

## Correctness Properties (Property-Based Test Candidates)

The following properties are derived from the requirements and are strong candidates for property-based tests during design and implementation. Each runs cheaply against a transactional test database (testing OraInvoice's own aggregation, not external services).

1. **Per-kind subtotal equals sum of lines (Req 1.4):** For any random set of Deduction_Lines on a payslip, each returned subtotal equals the exact sum of that payslip's lines of that kind. (model-based)
2. **All kinds always present (Req 1.2, 1.3):** For any payslip, the Deduction_Subtotals contains exactly the seven Deduction_Kinds, with absent kinds reported as zero. (invariant)
3. **Subtotals reconcile to net (Req 2.1):** For any payslip, `gross_pay − (sum of all subtotals except `kiwisaver_employer`) + reimbursements` equals `net_pay`, consistent with `compute_payslip`. (metamorphic / invariant)
4. **Employer KiwiSaver is non-net-affecting (Req 1.5, 3.5):** For any payslip, changing only the `kiwisaver_employer` line never changes `net_pay`, while it does change the combined KiwiSaver-plus-ACC KPI input. (metamorphic)
5. **Source-of-truth consistency (Req 2.4):** After mutating a payslip's Deduction_Lines, the next list response's subtotals reflect the mutation with no separate recompute call. (round-trip)
6. **Org isolation (Req 6.1, 6.2):** For two organisations with payslips of identical shape, each org's subtotals aggregate only its own Deduction_Lines. (security invariant)
7. **No N+1 / aggregate-once (NFR2.2):** For a period with N payslips, the number of deduction-aggregation queries issued by one list call is constant (one), independent of N. (performance invariant)
8. **Backward-compatible default (Req 5.1, NFR1.1):** A `PayslipResponse` built from an ORM row with no preloaded subtotals serialises successfully with every subtotal defaulting to zero. (invariant)

### Example-Based / Edge-Case Tests (not property-based)

- **Empty deductions (Req 1.3):** A draft payslip with zero Deduction_Lines returns all seven subtotals as zero. (example)
- **Mixed kinds (Req 1.1, 1.2):** A payslip with PAYE + employee + employer KiwiSaver + ACC + a voluntary line returns each kind correctly and folds nothing. (example)
- **Detail unchanged (Req 5.3):** `GET /api/v2/payslips/{id}` still returns the full `deductions` line list with identical shape. (example)
- **Self-service unchanged (Req 7.2, D4):** `GET /api/v2/staff/me/payslips` response shape is unchanged. (example)
- **Frontend KPI math (Req 3.4, 3.5):** Given fixture subtotals, the KiwiSaver+ACC KPI equals employee + employer + ACC summed across rows. (example / UI)
- **CSV export (Req 3.7):** The exported CSV contains the PAYE / KiwiSaver / ACC / Other columns matching the table. (example / UI)
