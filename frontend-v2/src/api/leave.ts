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
