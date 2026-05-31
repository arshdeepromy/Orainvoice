/**
 * Typed API client for the Payslips engine (Staff Management Phase 4).
 *
 * Mirrors the schemas in `app/modules/payslips/schemas.py` and the
 * routes in `app/modules/payslips/router.py` (registered at
 * `/api/v2`). Covers:
 *
 *   - Pay periods CRUD + reopen (R1, R1a, G21).
 *   - Payslips CRUD + finalise / email / pdf / void (R3, R4, R6, R7).
 *   - Per-staff history + recurring allowances (R3.5, G4).
 *   - Termination (R10).
 *   - Self-service /staff/me/payslips (R8a, G9).
 *   - Allowance types CRUD (R2).
 *   - Wage variance report (R12).
 *
 * Conventions (per `.kiro/steering/safe-api-consumption.md` and the
 * project rules):
 *
 *   - Every list endpoint returns `{ items, total }`; wrappers
 *     normalise to `{ items: res.data?.items ?? [], total: res.data?.total ?? 0 }`.
 *   - Pagination params are `offset` + `limit` (NOT `skip`).
 *   - All Decimal fields are serialised as strings on the wire — typed
 *     as `string` in TypeScript.
 *   - Every async function accepts an optional `AbortSignal` and
 *     forwards it via the axios request config (`{ signal }`).
 *   - Typed generics on every `apiClient.*` call — never `as any`.
 *   - Absolute paths beginning with `/api/v2/...` (the client's
 *     `client.ts` strips the `/api/v1` baseURL when the URL starts
 *     with `/api/`).
 *
 * **Validates: Staff Management Phase 4 task D9**
 */

import apiClient from './client'

// ===========================================================================
// Type definitions — mirror app/modules/payslips/schemas.py
// ===========================================================================

export type PayPeriodStatus = 'open' | 'finalised' | 'paid'

export type PayslipStatus = 'draft' | 'finalised' | 'voided'

export type AllowanceUnit = 'shift' | 'period' | 'km'

export type DeductionKind =
  | 'paye'
  | 'acc_levy'
  | 'kiwisaver_employee'
  | 'kiwisaver_employer'
  | 'student_loan'
  | 'child_support'
  | 'voluntary'

export type PayPeriodCadence = 'weekly' | 'fortnightly' | 'monthly'

/** Common wrapper shape per project rule. */
export interface ListResponse<T> {
  items: T[]
  total: number
}

// ---------------------------------------------------------------------------
// Pay periods
// ---------------------------------------------------------------------------

export interface PayPeriod {
  id: string
  org_id: string
  start_date: string
  end_date: string
  pay_date: string
  status: PayPeriodStatus | string
  created_at: string
  finalised_at: string | null
  paid_at: string | null
}

export interface PayPeriodCreatePayload {
  start_date: string
  end_date: string
  pay_date: string
}

export interface PayPeriodUpdatePayload {
  pay_date?: string
  status?: PayPeriodStatus
}

export interface PayPeriodReopenPayload {
  reason: string
}

// ---------------------------------------------------------------------------
// Allowance types
// ---------------------------------------------------------------------------

export interface AllowanceType {
  id: string
  org_id: string
  code: string
  name: string
  taxable: boolean
  /** Decimal serialised as string. */
  default_amount: string | null
  unit: AllowanceUnit | string
  active: boolean
  display_order: number
  created_at: string
  updated_at: string
}

export interface AllowanceTypeCreatePayload {
  code: string
  name: string
  taxable?: boolean
  /** Decimal — sent as string. */
  default_amount?: string | null
  unit?: AllowanceUnit
  active?: boolean
  display_order?: number
}

export interface AllowanceTypeUpdatePayload {
  name?: string
  taxable?: boolean
  default_amount?: string | null
  unit?: AllowanceUnit
  active?: boolean
  display_order?: number
}

// ---------------------------------------------------------------------------
// Payslip line schemas
// ---------------------------------------------------------------------------

export interface PayslipAllowance {
  id: string
  payslip_id: string
  allowance_type_id: string | null
  label: string
  /** Decimal serialised as string. */
  quantity: string
  unit: AllowanceUnit | string
  /** Decimal serialised as string. */
  amount: string
  taxable: boolean
}

export interface PayslipDeduction {
  id: string
  payslip_id: string
  kind: DeductionKind | string
  label: string
  /** Decimal serialised as string. */
  amount: string
}

export interface PayslipReimbursement {
  id: string
  payslip_id: string
  label: string
  /** Decimal serialised as string. */
  amount: string
}

export interface PayslipLeaveLine {
  id: string
  payslip_id: string
  leave_type_id: string
  leave_type_code: string | null
  leave_type_name: string | null
  /** Decimal serialised as string. */
  hours: string
  /** Decimal serialised as string. */
  rate: string
  /** Decimal serialised as string. */
  amount: string
  /** Decimal serialised as string. */
  balance_after: string
}

// ---------------------------------------------------------------------------
// Payslips (admin view)
// ---------------------------------------------------------------------------

export interface Payslip {
  id: string
  org_id: string
  staff_id: string
  staff_name: string | null
  pay_period_id: string
  pay_period: PayPeriod | null
  status: PayslipStatus | string
  /** Decimal serialised as string. */
  ordinary_hours: string
  /** Decimal serialised as string. */
  overtime_hours: string
  /** Decimal serialised as string. */
  public_holiday_hours: string
  /** Decimal serialised as string. */
  ordinary_rate: string | null
  /** Decimal serialised as string. */
  overtime_rate: string | null
  /** Decimal serialised as string. */
  public_holiday_rate: string | null
  /** Decimal serialised as string. */
  gross_pay: string
  /** Decimal serialised as string; year-to-date gross. */
  gross_ytd: string
  /** Decimal serialised as string. */
  net_pay: string
  pdf_file_key: string | null
  emailed_at: string | null
  finalised_at: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface PayslipDetail extends Payslip {
  allowances: PayslipAllowance[]
  deductions: PayslipDeduction[]
  reimbursements: PayslipReimbursement[]
  leave_lines: PayslipLeaveLine[]
}

export interface PayslipUpdatePayload {
  ordinary_hours?: string | null
  overtime_hours?: string | null
  public_holiday_hours?: string | null
  ordinary_rate?: string | null
  overtime_rate?: string | null
  public_holiday_rate?: string | null
  notes?: string | null
}

// ---------------------------------------------------------------------------
// Self-service payslips (G9)
// ---------------------------------------------------------------------------

export interface MyPayslip {
  id: string
  pay_period_id: string
  pay_period: PayPeriod | null
  status: PayslipStatus | string
  ordinary_hours: string
  overtime_hours: string
  public_holiday_hours: string
  ordinary_rate: string | null
  overtime_rate: string | null
  public_holiday_rate: string | null
  gross_pay: string
  gross_ytd: string
  net_pay: string
  finalised_at: string | null
  emailed_at: string | null
  /** Server-built download URL — `/api/v2/staff/me/payslips/:id/pdf`. */
  pdf_url: string | null
}

export interface MyPayslipDetail extends MyPayslip {
  allowances: PayslipAllowance[]
  deductions: PayslipDeduction[]
  reimbursements: PayslipReimbursement[]
  leave_lines: PayslipLeaveLine[]
}

// ---------------------------------------------------------------------------
// Recurring allowances (G4)
// ---------------------------------------------------------------------------

export interface StaffRecurringAllowance {
  id: string
  org_id: string
  staff_id: string
  allowance_type_id: string
  allowance_type: AllowanceType | null
  /** Decimal serialised as string; null = use type default. */
  amount: string | null
  /** Decimal serialised as string; null = derived from unit. */
  quantity: string | null
  active: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

export interface StaffRecurringAllowanceCreatePayload {
  allowance_type_id: string
  amount?: string | null
  quantity?: string | null
  active?: boolean
  notes?: string | null
}

export interface StaffRecurringAllowanceUpdatePayload {
  amount?: string | null
  quantity?: string | null
  active?: boolean
  notes?: string | null
}

// ---------------------------------------------------------------------------
// Termination (R10)
// ---------------------------------------------------------------------------

export interface TerminationFinalPayOptions {
  pay_annual_leave?: boolean
  pay_alt_days?: boolean
  pay_casual_8pct_remainder?: boolean
}

export interface TerminationPayload {
  end_date: string
  reason: string
  final_pay_options?: TerminationFinalPayOptions
}

/**
 * Server returns a free-form result dict per `terminate_employment`.
 * The shape is intentionally loose — admin UI surfaces whatever
 * fields the service includes (final payslip id, payout summary,
 * etc.).
 */
export interface TerminationResult {
  staff_id: string
  end_date: string
  final_payslip_id?: string | null
  pay_period_id?: string | null
  payout_summary?: {
    annual_hours?: string
    alt_days?: number
    casual_8pct_remaining?: string
  } | null
  cancelled_leave_request_count?: number
  [extra: string]: unknown
}

// ---------------------------------------------------------------------------
// Wage variance report (R12)
// ---------------------------------------------------------------------------

export interface WageVarianceRow {
  staff_id: string
  /** Decimal serialised as string. */
  current_gross: string
  /** Decimal serialised as string. */
  previous_gross: string
  /** Decimal serialised as string; current - previous. */
  delta: string
  /** Decimal serialised as string; percentage change. */
  delta_pct: string
  above_threshold: boolean
}

export interface WageVarianceReport {
  items: WageVarianceRow[]
  total: number
  threshold_pct: string
  current_period_id: string | null
  previous_period_id: string | null
}

// ---------------------------------------------------------------------------
// Bulk-finalise result
// ---------------------------------------------------------------------------

export interface BulkFinaliseResult {
  finalised_count: number
  emailed_count?: number
  failed_count?: number
  failed_payslip_ids?: string[]
  [extra: string]: unknown
}

// ===========================================================================
// Helpers — list query shapes
// ===========================================================================

export interface ListParams {
  offset?: number
  limit?: number
}

export interface ListPayPeriodsParams extends ListParams {
  status?: PayPeriodStatus
}

export interface ListAllowanceTypesParams {
  include_inactive?: boolean
}

export interface BulkFinaliseParams {
  email_all?: boolean
}

export interface VoidPayslipParams {
  reason?: string
}

export interface WageVarianceParams {
  /** Decimal — sent as string for parity with other Decimal params. */
  threshold_pct?: string | number
}

// ===========================================================================
// Pay-period endpoints
// ===========================================================================

export async function listPayPeriods(
  params: ListPayPeriodsParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<PayPeriod>> {
  const res = await apiClient.get<ListResponse<PayPeriod>>(
    '/api/v2/pay-periods',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function createPayPeriod(
  payload: PayPeriodCreatePayload,
  signal?: AbortSignal,
): Promise<PayPeriod> {
  const res = await apiClient.post<PayPeriod>(
    '/api/v2/pay-periods',
    payload,
    { signal },
  )
  return res.data
}

export async function getPayPeriod(
  id: string,
  signal?: AbortSignal,
): Promise<PayPeriod> {
  const res = await apiClient.get<PayPeriod>(
    `/api/v2/pay-periods/${id}`,
    { signal },
  )
  return res.data
}

export async function updatePayPeriod(
  id: string,
  payload: PayPeriodUpdatePayload,
  signal?: AbortSignal,
): Promise<PayPeriod> {
  const res = await apiClient.patch<PayPeriod>(
    `/api/v2/pay-periods/${id}`,
    payload,
    { signal },
  )
  return res.data
}

export async function reopenPayPeriod(
  id: string,
  payload: PayPeriodReopenPayload,
  signal?: AbortSignal,
): Promise<PayPeriod> {
  const res = await apiClient.post<PayPeriod>(
    `/api/v2/pay-periods/${id}/reopen`,
    payload,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Pay-period payslip operations
// ===========================================================================

export async function listPeriodPayslips(
  periodId: string,
  params: ListParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<Payslip>> {
  const res = await apiClient.get<ListResponse<Payslip>>(
    `/api/v2/pay-periods/${periodId}/payslips`,
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function generatePeriodPayslips(
  periodId: string,
  signal?: AbortSignal,
): Promise<ListResponse<Payslip>> {
  const res = await apiClient.post<ListResponse<Payslip>>(
    `/api/v2/pay-periods/${periodId}/payslips`,
    {},
    { signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function bulkFinalisePeriod(
  periodId: string,
  params: BulkFinaliseParams = {},
  signal?: AbortSignal,
): Promise<BulkFinaliseResult> {
  const res = await apiClient.post<BulkFinaliseResult>(
    `/api/v2/pay-periods/${periodId}/finalise`,
    {},
    { params, signal },
  )
  return res.data
}

// ===========================================================================
// Payslip endpoints (admin view)
// ===========================================================================

export async function getPayslip(
  id: string,
  signal?: AbortSignal,
): Promise<PayslipDetail> {
  const res = await apiClient.get<PayslipDetail>(
    `/api/v2/payslips/${id}`,
    { signal },
  )
  return res.data
}

export async function updatePayslip(
  id: string,
  payload: PayslipUpdatePayload,
  signal?: AbortSignal,
): Promise<Payslip> {
  const res = await apiClient.patch<Payslip>(
    `/api/v2/payslips/${id}`,
    payload,
    { signal },
  )
  return res.data
}

export async function finalisePayslip(
  id: string,
  signal?: AbortSignal,
): Promise<Payslip> {
  const res = await apiClient.post<Payslip>(
    `/api/v2/payslips/${id}/finalise`,
    {},
    { signal },
  )
  return res.data
}

export async function emailPayslip(
  id: string,
  signal?: AbortSignal,
): Promise<Payslip> {
  const res = await apiClient.post<Payslip>(
    `/api/v2/payslips/${id}/email`,
    {},
    { signal },
  )
  return res.data
}

export async function downloadPayslipPdf(
  id: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await apiClient.get<Blob>(`/api/v2/payslips/${id}/pdf`, {
    responseType: 'blob',
    signal,
  })
  return res.data
}

export async function voidPayslip(
  id: string,
  params: VoidPayslipParams = {},
  signal?: AbortSignal,
): Promise<Payslip> {
  const res = await apiClient.post<Payslip>(
    `/api/v2/payslips/${id}/void`,
    {},
    { params, signal },
  )
  return res.data
}

// ===========================================================================
// Per-staff history (admin)
// ===========================================================================

export async function listStaffPayslips(
  staffId: string,
  params: ListParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<Payslip>> {
  const res = await apiClient.get<ListResponse<Payslip>>(
    `/api/v2/staff/${staffId}/payslips`,
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

// ===========================================================================
// Recurring allowance rules (G4)
// ===========================================================================

export async function listRecurringAllowances(
  staffId: string,
  signal?: AbortSignal,
): Promise<ListResponse<StaffRecurringAllowance>> {
  const res = await apiClient.get<ListResponse<StaffRecurringAllowance>>(
    `/api/v2/staff/${staffId}/payslips/recurring-allowances`,
    { signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function createRecurringAllowance(
  staffId: string,
  payload: StaffRecurringAllowanceCreatePayload,
  signal?: AbortSignal,
): Promise<StaffRecurringAllowance> {
  const res = await apiClient.post<StaffRecurringAllowance>(
    `/api/v2/staff/${staffId}/payslips/recurring-allowances`,
    payload,
    { signal },
  )
  return res.data
}

export async function updateRecurringAllowance(
  staffId: string,
  ruleId: string,
  payload: StaffRecurringAllowanceUpdatePayload,
  signal?: AbortSignal,
): Promise<StaffRecurringAllowance> {
  const res = await apiClient.patch<StaffRecurringAllowance>(
    `/api/v2/staff/${staffId}/payslips/recurring-allowances/${ruleId}`,
    payload,
    { signal },
  )
  return res.data
}

export async function deactivateRecurringAllowance(
  staffId: string,
  ruleId: string,
  signal?: AbortSignal,
): Promise<{ id: string; active: boolean }> {
  const res = await apiClient.delete<{ id: string; active: boolean }>(
    `/api/v2/staff/${staffId}/payslips/recurring-allowances/${ruleId}`,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Termination (R10)
// ===========================================================================

export async function terminateStaff(
  staffId: string,
  payload: TerminationPayload,
  signal?: AbortSignal,
): Promise<TerminationResult> {
  const res = await apiClient.post<TerminationResult>(
    `/api/v2/staff/${staffId}/terminate`,
    payload,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Self-service payslips (G9)
// ===========================================================================

export async function listMyPayslips(
  params: ListParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<MyPayslip>> {
  const res = await apiClient.get<ListResponse<MyPayslip>>(
    '/api/v2/staff/me/payslips',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function getMyPayslip(
  id: string,
  signal?: AbortSignal,
): Promise<MyPayslipDetail> {
  const res = await apiClient.get<MyPayslipDetail>(
    `/api/v2/staff/me/payslips/${id}`,
    { signal },
  )
  return res.data
}

export async function downloadMyPayslipPdf(
  id: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await apiClient.get<Blob>(
    `/api/v2/staff/me/payslips/${id}/pdf`,
    { responseType: 'blob', signal },
  )
  return res.data
}

// ===========================================================================
// Allowance types CRUD (R2)
// ===========================================================================

export async function listAllowanceTypes(
  params: ListAllowanceTypesParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<AllowanceType>> {
  const res = await apiClient.get<ListResponse<AllowanceType>>(
    '/api/v2/allowance-types',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function createAllowanceType(
  payload: AllowanceTypeCreatePayload,
  signal?: AbortSignal,
): Promise<AllowanceType> {
  const res = await apiClient.post<AllowanceType>(
    '/api/v2/allowance-types',
    payload,
    { signal },
  )
  return res.data
}

export async function updateAllowanceType(
  id: string,
  payload: AllowanceTypeUpdatePayload,
  signal?: AbortSignal,
): Promise<AllowanceType> {
  const res = await apiClient.patch<AllowanceType>(
    `/api/v2/allowance-types/${id}`,
    payload,
    { signal },
  )
  return res.data
}

export async function deactivateAllowanceType(
  id: string,
  signal?: AbortSignal,
): Promise<{ id: string; active: boolean }> {
  const res = await apiClient.delete<{ id: string; active: boolean }>(
    `/api/v2/allowance-types/${id}`,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Wage variance report (R12)
// ===========================================================================

export async function getWageVarianceReport(
  params: WageVarianceParams = {},
  signal?: AbortSignal,
): Promise<WageVarianceReport> {
  const res = await apiClient.get<WageVarianceReport>(
    '/api/v2/reports/wage-variance',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    threshold_pct: res.data?.threshold_pct ?? '0',
    current_period_id: res.data?.current_period_id ?? null,
    previous_period_id: res.data?.previous_period_id ?? null,
  }
}
