/**
 * Typed API client for Payroll Tax Settings (feature: payroll-tax-settings).
 *
 * Covers both tiers of the two-tier, GUI-editable NZ payroll tax model:
 *
 *   - Platform tier (Global Admin):   GET/PUT  /api/v2/admin/platform-tax-default
 *   - Organisation tier (Org Admin):  GET/PUT  /api/v2/payroll-tax-settings
 *                                     DELETE   /api/v2/payroll-tax-settings/{field}
 *                                     DELETE   /api/v2/payroll-tax-settings
 *
 * Mirrors the Pydantic schemas in `app/modules/payroll_tax/schemas.py`
 * (`PlatformTaxDefaultView`, `PlatformTaxDefaultUpdate`, `OrgTaxSettingsView`,
 * `OrgOverridesUpdate`, `FieldError`).
 *
 * Conventions (per `.kiro/steering/safe-api-consumption.md` and project rules):
 *
 *   - Absolute paths beginning with `/api/v2/...` (the axios client in
 *     `client.ts` strips the `/api/v1` baseURL when the URL starts with `/api/`).
 *   - Every call accepts an optional `AbortSignal` forwarded via the request
 *     config (`{ signal }`).
 *   - Typed generics on every `apiClient.*` call — never `as any`.
 *   - Read sites use `?.` / `?? []` / `?? 0` so a partial/blank response can
 *     never crash a consumer.
 *   - Tax values are serialised as JSON numbers on the wire (consistent with the
 *     backend `Decimal` → number serialisation), typed as `number` here.
 *
 * **Validates: Requirements 2.1, 2.2 (and reused by task 12 for the org tier)**
 */

import apiClient from './client'

// ===========================================================================
// Tax-field shapes — shared by both tiers
// ===========================================================================

/** The five supported secondary tax codes. */
export type SecondaryTaxCode = 'SB' | 'S' | 'SH' | 'ST' | 'SA'

/** Ordered list of the secondary codes for stable UI rendering. */
export const SECONDARY_TAX_CODES: SecondaryTaxCode[] = [
  'SB',
  'S',
  'SH',
  'ST',
  'SA',
]

/**
 * One progressive PAYE income-tax band. The open-ended top band has
 * `upper_limit === null` (no income ceiling).
 */
export interface PAYEBracket {
  upper_limit: number | null
  rate: number
}

/** Map of secondary tax code → flat annual rate. */
export type SecondaryRates = Record<SecondaryTaxCode, number>

/** Independent Earner Tax Credit (IETC) parameters for the ME tax code. */
export interface IETCParams {
  amount: number
  lower: number
  abatement_start: number
  abatement_rate: number
  upper: number
}

/**
 * The full set of editable tax fields, shared by the platform view/update and
 * the org override payload. `tax_year_label` is platform-only (display label).
 */
export interface TaxConfigFields {
  paye_brackets: PAYEBracket[]
  secondary_rates: SecondaryRates
  acc_levy_rate: number
  acc_max_liable_earnings: number
  student_loan_rate: number
  student_loan_threshold: number
  ietc: IETCParams
  default_kiwisaver_employee_rate: number
  default_kiwisaver_employer_rate: number
  tax_year_label: string
}

// ===========================================================================
// Platform tier — PlatformTaxDefaultView / PlatformTaxDefaultUpdate
// ===========================================================================

/** Read view of the single Platform_Tax_Default record. */
export interface PlatformTaxDefaultView extends TaxConfigFields {
  updated_at: string | null
  updated_by: string | null
}

/** PUT body for the platform default — every field is required. */
export type PlatformTaxDefaultUpdate = TaxConfigFields

// ===========================================================================
// Org tier — OrgTaxSettingsView / OrgOverridesUpdate
// ===========================================================================

/** Whether a single org field is inherited from platform or set as an override. */
export interface FieldStatus {
  inherited: boolean
  override: boolean
  source: string
}

/**
 * Read view of an organisation's tax settings: the effective (resolved) value
 * of every field plus a per-field `inherited`/`override` status map.
 */
export interface OrgTaxSettingsView extends TaxConfigFields {
  field_status: Record<string, FieldStatus>
}

/**
 * Sparse PUT body for org overrides — only the fields the org is overriding are
 * present. (`tax_year_label` is platform-only and never overridable.)
 */
export type OrgOverridesUpdate = Partial<Omit<TaxConfigFields, 'tax_year_label'>>

// ===========================================================================
// Validation error shape — 422 detail = [{ field, message }]
// ===========================================================================

/** A single per-field validation error returned with a 422 response. */
export interface FieldError {
  field: string
  message: string
}

/**
 * Narrow an axios error body to a `FieldError[]`. The backend returns
 * `{ detail: [{ field, message }, ...] }` on a 422. Returns `[]` when the body
 * is not in the expected shape so callers can fall back to a generic message.
 */
export function parseFieldErrors(detail: unknown): FieldError[] {
  if (!Array.isArray(detail)) return []
  return detail
    .filter(
      (d): d is FieldError =>
        !!d &&
        typeof d === 'object' &&
        typeof (d as FieldError).field === 'string' &&
        typeof (d as FieldError).message === 'string',
    )
    .map((d) => ({ field: d.field, message: d.message }))
}

// ===========================================================================
// Platform-tier endpoints (Global Admin)
// ===========================================================================

export async function getPlatformTaxDefault(
  signal?: AbortSignal,
): Promise<PlatformTaxDefaultView> {
  const res = await apiClient.get<PlatformTaxDefaultView>(
    '/api/v2/admin/platform-tax-default',
    { signal },
  )
  const d = res.data
  return {
    paye_brackets: d?.paye_brackets ?? [],
    secondary_rates: d?.secondary_rates ?? ({} as SecondaryRates),
    acc_levy_rate: d?.acc_levy_rate ?? 0,
    acc_max_liable_earnings: d?.acc_max_liable_earnings ?? 0,
    student_loan_rate: d?.student_loan_rate ?? 0,
    student_loan_threshold: d?.student_loan_threshold ?? 0,
    ietc: {
      amount: d?.ietc?.amount ?? 0,
      lower: d?.ietc?.lower ?? 0,
      abatement_start: d?.ietc?.abatement_start ?? 0,
      abatement_rate: d?.ietc?.abatement_rate ?? 0,
      upper: d?.ietc?.upper ?? 0,
    },
    default_kiwisaver_employee_rate: d?.default_kiwisaver_employee_rate ?? 0,
    default_kiwisaver_employer_rate: d?.default_kiwisaver_employer_rate ?? 0,
    tax_year_label: d?.tax_year_label ?? '',
    updated_at: d?.updated_at ?? null,
    updated_by: d?.updated_by ?? null,
  }
}

export async function updatePlatformTaxDefault(
  payload: PlatformTaxDefaultUpdate,
  signal?: AbortSignal,
): Promise<PlatformTaxDefaultView> {
  const res = await apiClient.put<PlatformTaxDefaultView>(
    '/api/v2/admin/platform-tax-default',
    payload,
    { signal },
  )
  const d = res.data
  return {
    paye_brackets: d?.paye_brackets ?? [],
    secondary_rates: d?.secondary_rates ?? ({} as SecondaryRates),
    acc_levy_rate: d?.acc_levy_rate ?? 0,
    acc_max_liable_earnings: d?.acc_max_liable_earnings ?? 0,
    student_loan_rate: d?.student_loan_rate ?? 0,
    student_loan_threshold: d?.student_loan_threshold ?? 0,
    ietc: {
      amount: d?.ietc?.amount ?? 0,
      lower: d?.ietc?.lower ?? 0,
      abatement_start: d?.ietc?.abatement_start ?? 0,
      abatement_rate: d?.ietc?.abatement_rate ?? 0,
      upper: d?.ietc?.upper ?? 0,
    },
    default_kiwisaver_employee_rate: d?.default_kiwisaver_employee_rate ?? 0,
    default_kiwisaver_employer_rate: d?.default_kiwisaver_employer_rate ?? 0,
    tax_year_label: d?.tax_year_label ?? '',
    updated_at: d?.updated_at ?? null,
    updated_by: d?.updated_by ?? null,
  }
}

// ===========================================================================
// Org-tier endpoints (Org Admin) — reused by task 12
// ===========================================================================

export async function getOrgTaxSettings(
  signal?: AbortSignal,
): Promise<OrgTaxSettingsView> {
  const res = await apiClient.get<OrgTaxSettingsView>(
    '/api/v2/payroll-tax-settings',
    { signal },
  )
  const d = res.data
  return {
    paye_brackets: d?.paye_brackets ?? [],
    secondary_rates: d?.secondary_rates ?? ({} as SecondaryRates),
    acc_levy_rate: d?.acc_levy_rate ?? 0,
    acc_max_liable_earnings: d?.acc_max_liable_earnings ?? 0,
    student_loan_rate: d?.student_loan_rate ?? 0,
    student_loan_threshold: d?.student_loan_threshold ?? 0,
    ietc: {
      amount: d?.ietc?.amount ?? 0,
      lower: d?.ietc?.lower ?? 0,
      abatement_start: d?.ietc?.abatement_start ?? 0,
      abatement_rate: d?.ietc?.abatement_rate ?? 0,
      upper: d?.ietc?.upper ?? 0,
    },
    default_kiwisaver_employee_rate: d?.default_kiwisaver_employee_rate ?? 0,
    default_kiwisaver_employer_rate: d?.default_kiwisaver_employer_rate ?? 0,
    tax_year_label: d?.tax_year_label ?? '',
    field_status: d?.field_status ?? {},
  }
}

export async function updateOrgTaxSettings(
  payload: OrgOverridesUpdate,
  signal?: AbortSignal,
): Promise<OrgTaxSettingsView> {
  const res = await apiClient.put<OrgTaxSettingsView>(
    '/api/v2/payroll-tax-settings',
    payload,
    { signal },
  )
  const d = res.data
  return {
    paye_brackets: d?.paye_brackets ?? [],
    secondary_rates: d?.secondary_rates ?? ({} as SecondaryRates),
    acc_levy_rate: d?.acc_levy_rate ?? 0,
    acc_max_liable_earnings: d?.acc_max_liable_earnings ?? 0,
    student_loan_rate: d?.student_loan_rate ?? 0,
    student_loan_threshold: d?.student_loan_threshold ?? 0,
    ietc: {
      amount: d?.ietc?.amount ?? 0,
      lower: d?.ietc?.lower ?? 0,
      abatement_start: d?.ietc?.abatement_start ?? 0,
      abatement_rate: d?.ietc?.abatement_rate ?? 0,
      upper: d?.ietc?.upper ?? 0,
    },
    default_kiwisaver_employee_rate: d?.default_kiwisaver_employee_rate ?? 0,
    default_kiwisaver_employer_rate: d?.default_kiwisaver_employer_rate ?? 0,
    tax_year_label: d?.tax_year_label ?? '',
    field_status: d?.field_status ?? {},
  }
}

/** Reset a single org override field so it falls back to the platform default. */
export async function resetOrgTaxField(
  field: string,
  signal?: AbortSignal,
): Promise<OrgTaxSettingsView> {
  const res = await apiClient.delete<OrgTaxSettingsView>(
    `/api/v2/payroll-tax-settings/${field}`,
    { signal },
  )
  const d = res.data
  return {
    paye_brackets: d?.paye_brackets ?? [],
    secondary_rates: d?.secondary_rates ?? ({} as SecondaryRates),
    acc_levy_rate: d?.acc_levy_rate ?? 0,
    acc_max_liable_earnings: d?.acc_max_liable_earnings ?? 0,
    student_loan_rate: d?.student_loan_rate ?? 0,
    student_loan_threshold: d?.student_loan_threshold ?? 0,
    ietc: {
      amount: d?.ietc?.amount ?? 0,
      lower: d?.ietc?.lower ?? 0,
      abatement_start: d?.ietc?.abatement_start ?? 0,
      abatement_rate: d?.ietc?.abatement_rate ?? 0,
      upper: d?.ietc?.upper ?? 0,
    },
    default_kiwisaver_employee_rate: d?.default_kiwisaver_employee_rate ?? 0,
    default_kiwisaver_employer_rate: d?.default_kiwisaver_employer_rate ?? 0,
    tax_year_label: d?.tax_year_label ?? '',
    field_status: d?.field_status ?? {},
  }
}

/** Reset all org overrides so every field inherits the platform default. */
export async function resetAllOrgTaxFields(
  signal?: AbortSignal,
): Promise<OrgTaxSettingsView> {
  const res = await apiClient.delete<OrgTaxSettingsView>(
    '/api/v2/payroll-tax-settings',
    { signal },
  )
  const d = res.data
  return {
    paye_brackets: d?.paye_brackets ?? [],
    secondary_rates: d?.secondary_rates ?? ({} as SecondaryRates),
    acc_levy_rate: d?.acc_levy_rate ?? 0,
    acc_max_liable_earnings: d?.acc_max_liable_earnings ?? 0,
    student_loan_rate: d?.student_loan_rate ?? 0,
    student_loan_threshold: d?.student_loan_threshold ?? 0,
    ietc: {
      amount: d?.ietc?.amount ?? 0,
      lower: d?.ietc?.lower ?? 0,
      abatement_start: d?.ietc?.abatement_start ?? 0,
      abatement_rate: d?.ietc?.abatement_rate ?? 0,
      upper: d?.ietc?.upper ?? 0,
    },
    default_kiwisaver_employee_rate: d?.default_kiwisaver_employee_rate ?? 0,
    default_kiwisaver_employer_rate: d?.default_kiwisaver_employer_rate ?? 0,
    tax_year_label: d?.tax_year_label ?? '',
    field_status: d?.field_status ?? {},
  }
}
