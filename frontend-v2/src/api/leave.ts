/**
 * Typed API client for the Leave engine (Staff Management Phase 2).
 *
 * Mirrors the schemas in `app/modules/leave/schemas.py` and the routes
 * in `app/modules/leave/router.py` (registered at `/api/v2`) plus
 * `app/modules/leave/permissions_router.py` (registered at
 * `/api/v2/permissions/fv-leave-view`).
 *
 * Conventions (per `.kiro/steering/safe-api-consumption.md` and the
 * project rules):
 *
 * - Every list endpoint returns `{ items, total }`.
 * - Pagination params are `offset` + `limit` (NOT `skip`).
 * - All Decimal fields are serialised as strings on the wire.
 * - Every call accepts an optional `AbortSignal` for cleanup.
 * - Typed generics on every `apiClient.*` call — never `as any`.
 *
 * **Validates: Staff Management Phase 2 task D9**
 */

import apiClient from './client'

// ===========================================================================
// Type definitions — mirror app/modules/leave/schemas.py
// ===========================================================================

export type AccrualMethod =
  | 'anniversary'
  | 'fixed_annual'
  | 'per_period'
  | 'unaccrued'
  | 'event_based'

export type AccrualUnit = 'hours' | 'days'

export type LeaveRequestStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'cancelled'

export type RelationshipToSubject = 'close_family' | 'other'

export type LedgerReason =
  | 'accrual'
  | 'request_approved'
  | 'request_cancelled'
  | 'adjustment'
  | 'carry_over'
  | 'expiry'

export interface LeaveType {
  id: string
  org_id: string
  code: string
  name: string
  is_paid: boolean
  accrual_method: AccrualMethod
  /** Decimal serialised as string. */
  accrual_amount: string | null
  accrual_unit: AccrualUnit
  /** Decimal serialised as string. */
  carry_over_max: string | null
  is_statutory: boolean
  requires_doctor_note: boolean
  confidential_visibility: boolean
  active: boolean
  display_order: number
  created_at?: string
  updated_at?: string
}

export interface LeaveBalance {
  id: string
  leave_type_id: string
  leave_type_code: string | null
  leave_type_name: string | null
  /** Decimal serialised as string. */
  accrued_hours: string
  /** Decimal serialised as string. */
  used_hours: string
  /** Decimal serialised as string. */
  pending_hours: string
  /** Computed server-side: accrued - used - pending. */
  available_hours: string
  anniversary_date: string | null
  last_accrual_at: string | null
  updated_at: string
}

export interface LeaveLedgerEntry {
  id: string
  leave_type_id: string
  leave_type_code: string | null
  /** Decimal serialised as string; can be negative. */
  delta_hours: string
  reason: LedgerReason | string
  request_id: string | null
  request_relationship_to_subject: RelationshipToSubject | string | null
  occurred_at: string
  created_at: string
  created_by: string | null
  created_by_email: string | null
}

export interface LeaveRequest {
  id: string
  org_id: string
  staff_id: string
  staff_name: string | null
  leave_type_id: string
  leave_type_code: string | null
  leave_type_name: string | null
  start_date: string
  end_date: string
  /** Decimal serialised as string. */
  hours_requested: string
  status: LeaveRequestStatus
  reason: string | null
  relationship_to_subject: RelationshipToSubject | string | null
  partial_day_start_time: string | null
  attachment_upload_id: string | null
  requested_by: string | null
  requested_by_name: string | null
  decided_by: string | null
  decided_at: string | null
  decision_notes: string | null
  created_at: string
  updated_at: string
}

export interface ListResponse<T> {
  items: T[]
  total: number
}

// ===========================================================================
// Payload types
// ===========================================================================

export interface LeaveTypeCreatePayload {
  code: string
  name: string
  is_paid?: boolean
  accrual_method: AccrualMethod
  accrual_amount?: string | null
  accrual_unit?: AccrualUnit
  carry_over_max?: string | null
  requires_doctor_note?: boolean
  confidential_visibility?: boolean
  active?: boolean
  display_order?: number
}

export interface LeaveTypeUpdatePayload {
  code?: string
  name?: string
  is_paid?: boolean
  accrual_method?: AccrualMethod
  accrual_amount?: string | null
  accrual_unit?: AccrualUnit
  carry_over_max?: string | null
  requires_doctor_note?: boolean
  confidential_visibility?: boolean
  active?: boolean
  display_order?: number
}

export interface LeaveRequestCreatePayload {
  leave_type_id: string
  start_date: string
  end_date: string
  /** Decimal — sent as string so we don't lose precision. */
  hours_requested: string
  reason?: string | null
  relationship_to_subject?: RelationshipToSubject | null
  partial_day_start_time?: string | null
  attachment_upload_id?: string | null
}

export interface LeaveDecisionPayload {
  decision_notes?: string | null
}

export interface AdjustBalancePayload {
  staff_id: string
  leave_type_id: string
  /** Decimal serialised as string; positive credits, negative debits. */
  delta_hours: string
  reason: string
  notes?: string | null
}

export interface AdjustBalanceResult {
  ledger_id: string
  delta_hours: string
  occurred_at: string
}

export interface FvLeaveViewUser {
  user_id: string
  email: string
  name: string | null
  role: string
  has_fv_view: boolean
  granted_at: string | null
}

export interface FvLeaveViewGrantResult {
  user_id: string
  permission_key: string
  is_granted: boolean
}

export interface FvLeaveViewRevokeResult {
  user_id: string
  permission_key: string
  deleted: boolean
}

// ===========================================================================
// Helpers
// ===========================================================================

/** Common shape for list-endpoint query params. */
export interface ListParams {
  offset?: number
  limit?: number
}

export interface ListLeaveTypesParams extends ListParams {
  include_inactive?: boolean
}

export interface ListLedgerParams extends ListParams {
  leave_type_id?: string
}

export interface ListRequestsParams extends ListParams {
  status?: LeaveRequestStatus
}

export interface ListApprovalQueueParams extends ListParams {
  status?: LeaveRequestStatus | 'all'
}

// ===========================================================================
// Leave type endpoints
// ===========================================================================

export async function listLeaveTypes(
  params: ListLeaveTypesParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<LeaveType>> {
  const res = await apiClient.get<ListResponse<LeaveType>>(
    '/api/v2/leave/types',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function createLeaveType(
  payload: LeaveTypeCreatePayload,
  signal?: AbortSignal,
): Promise<LeaveType> {
  const res = await apiClient.post<LeaveType>(
    '/api/v2/leave/types',
    payload,
    { signal },
  )
  return res.data
}

export async function updateLeaveType(
  id: string,
  payload: LeaveTypeUpdatePayload,
  signal?: AbortSignal,
): Promise<LeaveType> {
  const res = await apiClient.patch<LeaveType>(
    `/api/v2/leave/types/${id}`,
    payload,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Per-staff balances + ledger + requests
// ===========================================================================

export async function listStaffBalances(
  staffId: string,
  signal?: AbortSignal,
): Promise<ListResponse<LeaveBalance>> {
  const res = await apiClient.get<ListResponse<LeaveBalance>>(
    `/api/v2/staff/${staffId}/leave/balances`,
    { signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function listStaffLedger(
  staffId: string,
  params: ListLedgerParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<LeaveLedgerEntry>> {
  const res = await apiClient.get<ListResponse<LeaveLedgerEntry>>(
    `/api/v2/staff/${staffId}/leave/ledger`,
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function listStaffRequests(
  staffId: string,
  params: ListRequestsParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<LeaveRequest>> {
  const res = await apiClient.get<ListResponse<LeaveRequest>>(
    `/api/v2/staff/${staffId}/leave/requests`,
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function submitLeaveRequest(
  staffId: string,
  payload: LeaveRequestCreatePayload,
  signal?: AbortSignal,
): Promise<LeaveRequest> {
  const res = await apiClient.post<LeaveRequest>(
    `/api/v2/staff/${staffId}/leave/requests`,
    payload,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Decision endpoints
// ===========================================================================

export async function approveLeaveRequest(
  requestId: string,
  payload: LeaveDecisionPayload = {},
  signal?: AbortSignal,
): Promise<LeaveRequest> {
  const res = await apiClient.post<LeaveRequest>(
    `/api/v2/leave/requests/${requestId}/approve`,
    payload,
    { signal },
  )
  return res.data
}

export async function rejectLeaveRequest(
  requestId: string,
  payload: LeaveDecisionPayload = {},
  signal?: AbortSignal,
): Promise<LeaveRequest> {
  const res = await apiClient.post<LeaveRequest>(
    `/api/v2/leave/requests/${requestId}/reject`,
    payload,
    { signal },
  )
  return res.data
}

export async function cancelLeaveRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<LeaveRequest> {
  const res = await apiClient.post<LeaveRequest>(
    `/api/v2/leave/requests/${requestId}/cancel`,
    {},
    { signal },
  )
  return res.data
}

// ===========================================================================
// Manual balance adjustment (admin)
// ===========================================================================

export async function adjustLeaveBalance(
  staffId: string,
  leaveTypeId: string,
  payload: AdjustBalancePayload,
  signal?: AbortSignal,
): Promise<AdjustBalanceResult> {
  const res = await apiClient.post<AdjustBalanceResult>(
    `/api/v2/staff/${staffId}/leave/balances/${leaveTypeId}/adjust`,
    payload,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Approval queue
// ===========================================================================

export async function listApprovalQueue(
  params: ListApprovalQueueParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<LeaveRequest>> {
  const res = await apiClient.get<ListResponse<LeaveRequest>>(
    '/api/v2/leave/approvals',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

// ===========================================================================
// Family-violence leave-view permission management (D11)
// ===========================================================================

export async function listFvLeaveViewPermissions(
  signal?: AbortSignal,
): Promise<ListResponse<FvLeaveViewUser>> {
  const res = await apiClient.get<ListResponse<FvLeaveViewUser>>(
    '/api/v2/permissions/fv-leave-view',
    { signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export async function grantFvLeaveView(
  userId: string,
  signal?: AbortSignal,
): Promise<FvLeaveViewGrantResult> {
  const res = await apiClient.post<FvLeaveViewGrantResult>(
    `/api/v2/permissions/fv-leave-view/${userId}/grant`,
    {},
    { signal },
  )
  return res.data
}

export async function revokeFvLeaveView(
  userId: string,
  signal?: AbortSignal,
): Promise<FvLeaveViewRevokeResult> {
  const res = await apiClient.post<FvLeaveViewRevokeResult>(
    `/api/v2/permissions/fv-leave-view/${userId}/revoke`,
    {},
    { signal },
  )
  return res.data
}

// ===========================================================================
// Mark-day leave (Roster Grid "paint leave" action)
// ===========================================================================

export interface MarkDayLeavePayload {
  staff_id: string
  leave_type_id: string
  /** YYYY-MM-DD */
  date: string
  publish_to_open_shifts?: boolean
}

export interface MarkDayLeaveResult {
  leave_request_id: string
  status: string
  displaced_shift_count: number
  open_shift_ids: string[]
}

export async function markDayLeave(
  payload: MarkDayLeavePayload,
  signal?: AbortSignal,
): Promise<MarkDayLeaveResult> {
  const res = await apiClient.post<MarkDayLeaveResult>(
    '/api/v2/leave/mark-day',
    payload,
    { signal },
  )
  return res.data
}

export interface UnmarkDayLeavePayload {
  staff_id: string
  /** YYYY-MM-DD */
  date: string
}

export interface UnmarkDayLeaveResult {
  cancelled_request_ids: string[]
  cancelled_cover_ids: string[]
  leave_entries_removed: number
}

export async function unmarkDayLeave(
  payload: UnmarkDayLeavePayload,
  signal?: AbortSignal,
): Promise<UnmarkDayLeaveResult> {
  const res = await apiClient.post<UnmarkDayLeaveResult>(
    '/api/v2/leave/unmark-day',
    payload,
    { signal },
  )
  return res.data
}

// ===========================================================================
// Org-wide Leave Balances list + reference guide (Leave Balances & Eligibility)
// ===========================================================================

export interface EligibilityNote {
  leave_type_id: string
  leave_type_code: string | null
  rule_set_version: string
  milestone_key: string
  hours_test_met: boolean | null
  condition_text: string
  vested_on: string
}

export interface StaffLeaveBalances {
  staff_id: string
  staff_name: string
  employment_type: string
  holiday_pay_method: string
  balances: LeaveBalance[]
  eligibility_notes: EligibilityNote[]
}

export interface ListOrgBalancesParams {
  employment_type?: string
  group_by?: 'employment_type'
  offset?: number
  limit?: number
}

export async function listOrgLeaveBalances(
  params: ListOrgBalancesParams = {},
  signal?: AbortSignal,
): Promise<ListResponse<StaffLeaveBalances>> {
  const res = await apiClient.get<ListResponse<StaffLeaveBalances>>(
    '/api/v2/leave/balances',
    { params, signal },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
  }
}

export interface ReferenceGuideSection {
  key: string
  title: string
  body: string
}

export interface ReferenceGuide {
  rule_set_version: string
  sections: ReferenceGuideSection[]
}

export async function getLeaveReferenceGuide(
  signal?: AbortSignal,
): Promise<ReferenceGuide> {
  const res = await apiClient.get<ReferenceGuide>(
    '/api/v2/leave/reference-guide',
    { signal },
  )
  return {
    rule_set_version: res.data?.rule_set_version ?? 'holidays_act_2003',
    sections: res.data?.sections ?? [],
  }
}

/**
 * The full staff fields the per-staff `LeaveTab` needs for the drill-in.
 * Fetched from `GET /api/v2/staff/{id}` because the org-wide balances row is a
 * lightweight projection (no standard hours / shift / availability).
 */
export interface StaffLeaveContext {
  id: string
  name?: string
  employment_type: string
  standard_hours_per_week: string | null
  shift_start: string | null
  shift_end: string | null
  availability_schedule: Record<string, { start: string; end: string } | undefined>
}

export async function getStaffLeaveContext(
  staffId: string,
  signal?: AbortSignal,
): Promise<StaffLeaveContext> {
  const res = await apiClient.get<Partial<StaffLeaveContext>>(
    `/api/v2/staff/${staffId}`,
    { signal },
  )
  const d = res.data ?? {}
  return {
    id: d.id ?? staffId,
    name: d.name,
    employment_type: d.employment_type ?? '',
    standard_hours_per_week: d.standard_hours_per_week ?? null,
    shift_start: d.shift_start ?? null,
    shift_end: d.shift_end ?? null,
    availability_schedule: d.availability_schedule ?? {},
  }
}


// ===========================================================================
// Per-staff leave eligibility overview (drill-in Leave view)
// ===========================================================================

export type LeaveEligibilityStatus =
  | 'eligible'
  | 'pending'
  | 'casual_payg'
  | 'always'
  | 'no_start_date'

export interface StaffLeaveEligibilityItem {
  leave_type_id: string
  code: string
  name: string
  is_paid: boolean
  is_statutory: boolean
  accrual_method: string
  confidential_visibility: boolean
  status: LeaveEligibilityStatus
  eligible: boolean
  milestone_key: string | null
  milestone_months: number | null
  eligible_on: string | null
  reason: string | null
  hours_test_required: boolean
  hours_test_met: boolean | null
  accrued_hours: string
  used_hours: string
  pending_hours: string
  available_hours: string
  has_balance: boolean
}

export interface StaffLeaveEligibility {
  staff_id: string
  employment_start_date: string | null
  months_completed: number | null
  days_employed: number | null
  rule_set_version: string | null
  items: StaffLeaveEligibilityItem[]
}

export async function getStaffLeaveEligibility(
  staffId: string,
  signal?: AbortSignal,
): Promise<StaffLeaveEligibility> {
  const res = await apiClient.get<StaffLeaveEligibility>(
    `/api/v2/leave/staff/${staffId}/eligibility`,
    { signal },
  )
  const d = res.data
  return {
    staff_id: d?.staff_id ?? staffId,
    employment_start_date: d?.employment_start_date ?? null,
    months_completed: d?.months_completed ?? null,
    days_employed: d?.days_employed ?? null,
    rule_set_version: d?.rule_set_version ?? null,
    items: d?.items ?? [],
  }
}
