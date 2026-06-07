/**
 * Typed API client for the Staff redesign metric/KPI endpoints.
 *
 * Mirrors the schemas in `app/modules/staff/schemas.py`
 * (`StaffMonthStatsResponse`, `StaffListKpisResponse`) and the routes in
 * `app/modules/staff/router.py` (registered at `/api/v2`), plus the
 * existing leave approval queue (`/api/v2/leave/approvals`) used for the
 * pending-leave badge count.
 *
 * Conventions (per `.kiro/steering/safe-api-consumption.md`, the project
 * rules, and the `api/leave.ts` convention):
 *
 * - v2 endpoints use absolute `/api/v2/...` paths (the client strips the
 *   `/api/v1` baseURL for any URL starting with `/api/`).
 * - All responses are structured objects (never bare arrays); v2 list
 *   endpoints return `{ items, total }`.
 * - Backend Decimal fields are serialised as either a string or a number
 *   on the wire — coerce defensively with `Number(...)` and guard `NaN`.
 * - Every call accepts an optional `AbortSignal` for cleanup.
 * - Typed generics on every `apiClient.*` call — never `as any`.
 * - Each function reads response data defensively (`res.data?.x ?? default`)
 *   and returns a fully-populated object so callers never see `undefined`.
 *
 * _Requirements: 8.6, 14.1, 14.5, 5.2_
 */

import apiClient from './client'

// ===========================================================================
// Type definitions — mirror app/modules/staff/schemas.py
// ===========================================================================

export interface StaffMetric {
  /** Numeric value; 0 when has_data is false. */
  value: number
  /** false → render '—'. */
  has_data: boolean
}

export interface StaffMonthStats {
  period: 'this_month'
  /** Hours, one decimal. */
  hours_logged: StaffMetric
  /** Integer count. */
  jobs_completed: StaffMetric
  /** Whole percent 0–100. */
  billable_ratio: StaffMetric
  /** Whole percent 0–100. */
  on_time_rate: StaffMetric
  /** ISO 8601 timestamp, or null when there is no linked user account. */
  last_sign_in: string | null
  /** Linked user's role, or null when there is no account. */
  user_role: string | null
}

export interface StaffListKpis {
  total_staff: number
  employee_count: number
  with_login_count: number
  /** null → render '—'. */
  avg_hourly_rate: number | null
}

// ---------------------------------------------------------------------------
// Wire types — what the backend actually serialises (Decimal → string|number).
// ---------------------------------------------------------------------------

interface StaffMetricWire {
  value?: number | string | null
  has_data?: boolean | null
}

interface StaffMonthStatsWire {
  staff_id?: string
  period?: string
  hours_logged?: StaffMetricWire | null
  jobs_completed?: StaffMetricWire | null
  billable_ratio?: StaffMetricWire | null
  on_time_rate?: StaffMetricWire | null
  last_sign_in?: string | null
  user_role?: string | null
}

interface StaffListKpisWire {
  total_staff?: number | string | null
  employee_count?: number | string | null
  with_login_count?: number | string | null
  avg_hourly_rate?: number | string | null
}

interface LeaveApprovalQueueWire {
  total?: number | string | null
}

// ===========================================================================
// Helpers
// ===========================================================================

/**
 * Coerce a Decimal-from-the-wire value (string | number | null | undefined)
 * to a finite number. Returns `fallback` for anything non-finite.
 */
function toNumber(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

/**
 * Coerce a wire metric sub-object into a fully-populated `StaffMetric`,
 * defaulting to `{ value: 0, has_data: false }`.
 */
function toMetric(wire: StaffMetricWire | null | undefined): StaffMetric {
  return {
    value: toNumber(wire?.value, 0),
    has_data: wire?.has_data ?? false,
  }
}

// ===========================================================================
// Endpoints
// ===========================================================================

/**
 * GET /api/v2/staff/{staffId}/stats?period=this_month
 *
 * Returns a fully-populated `StaffMonthStats`: each metric defaults to
 * `{ value: 0, has_data: false }`, and `last_sign_in` / `user_role` default
 * to null. Decimal values are coerced to numbers with NaN guarded.
 */
export async function getStaffMonthStats(
  staffId: string,
  period: 'this_month' = 'this_month',
  signal?: AbortSignal,
): Promise<StaffMonthStats> {
  const res = await apiClient.get<StaffMonthStatsWire>(
    `/api/v2/staff/${staffId}/stats`,
    { params: { period }, signal },
  )
  const data = res.data
  return {
    period: 'this_month',
    hours_logged: toMetric(data?.hours_logged),
    jobs_completed: toMetric(data?.jobs_completed),
    billable_ratio: toMetric(data?.billable_ratio),
    on_time_rate: toMetric(data?.on_time_rate),
    last_sign_in: data?.last_sign_in ?? null,
    user_role: data?.user_role ?? null,
  }
}

/**
 * GET /api/v2/staff/kpis
 *
 * Returns a fully-populated `StaffListKpis`: counts default to 0 and
 * `avg_hourly_rate` defaults to null (rendered as '—' by callers).
 */
export async function getStaffListKpis(
  signal?: AbortSignal,
): Promise<StaffListKpis> {
  const res = await apiClient.get<StaffListKpisWire>(
    '/api/v2/staff/kpis',
    { signal },
  )
  const data = res.data
  const avgRaw = data?.avg_hourly_rate
  const avg = avgRaw == null ? null : toNumber(avgRaw, NaN)
  return {
    total_staff: toNumber(data?.total_staff, 0),
    employee_count: toNumber(data?.employee_count, 0),
    with_login_count: toNumber(data?.with_login_count, 0),
    avg_hourly_rate: avg == null || Number.isNaN(avg) ? null : avg,
  }
}

/**
 * Pending-leave badge count for the Staff list header.
 *
 * Reads `total` from the EXISTING role-scoped approval queue
 * `GET /api/v2/leave/approvals` (server-scoped to the requester's role).
 * No dedicated count endpoint exists. Returns 0 on any failure so the
 * badge can be hidden (R5.2).
 */
export async function getPendingLeaveCount(
  signal?: AbortSignal,
): Promise<number> {
  try {
    const res = await apiClient.get<LeaveApprovalQueueWire>(
      '/api/v2/leave/approvals',
      { params: { status: 'pending', limit: 1 }, signal },
    )
    return toNumber(res.data?.total, 0)
  } catch {
    return 0
  }
}
