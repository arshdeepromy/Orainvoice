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
// Per-staff pay cycle (per-staff-pay-cycle feature).
//
// Mirrors `app/modules/staff/schemas.py`:
//   - `StaffMemberCreate` / `StaffMemberUpdate` gain a request-only,
//     optional `pay_cycle_id`.
//   - `StaffMemberResponse` gains read-only `pay_cycle_id`, `pay_cycle_name`,
//     and `pay_cycle_is_default`.
//
// These are factored out as small, reusable contracts so the staff Add modal
// (`StaffList.tsx`) and Edit form (`tabs/OverviewTab.tsx`) can intersect them
// with their local staff payload/response shapes without duplicating field
// definitions.
// ---------------------------------------------------------------------------

/**
 * Request-only pay-cycle selection included in the staff create/update
 * payload. Tri-state semantics (mirrors the backend `exclude_unset`
 * discipline):
 *
 *   - `string` (cycle UUID): assign / replace the staff-level pay cycle.
 *   - `null`: clear any existing staff-level assignment so the staff member
 *     resolves to the organisation's default cycle.
 *   - omitted (`undefined`): leave the existing assignment unchanged (update
 *     only).
 *
 * _Requirements: 1.1, 2.1, 2.2, 3.3_
 */
export interface StaffPayCyclePayload {
  pay_cycle_id?: string | null
}

/**
 * Read-only resolved pay-cycle fields returned on the staff response. All
 * three are null / false when the staff member has no resolved cycle (no
 * matching assignment and no default — REQ 5.3).
 *
 * _Requirements: 5.1, 5.2_
 */
export interface StaffPayCycleResponseFields {
  /** Identifier of the staff member's resolved pay cycle, or null. */
  pay_cycle_id: string | null
  /** Name of the resolved pay cycle, or null. */
  pay_cycle_name: string | null
  /**
   * True when the staff member resolves to the organisation's default cycle
   * through the absence of a more specific assignment (REQ 5.2). False when
   * an explicit staff-level cycle is assigned (drives Edit-form prefill).
   */
  pay_cycle_is_default: boolean
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

// ===========================================================================
// Onboarding link admin helpers (R10.1, R10.2, R10.3, R11.6)
// ---------------------------------------------------------------------------
// AUTHENTICATED admin transport for the onboarding-link lifecycle card
// (Task 10.2's OverviewTab). Mirrors `OnboardingLinkStatusResponse` and the
// resend/revoke route bodies in `app/modules/staff/router.py`.
//
// NOTE: the PUBLIC prefill/submit/draft transport is intentionally NOT here —
// it lives in its own raw-axios module (Task 10.3) because it is unauthenticated
// and token-scoped. These helpers all hit `/api/v2/staff/{id}/...` with the
// shared `apiClient` (JWT + branch + CSRF interceptors).
// ===========================================================================

export type OnboardingLinkState =
  | 'not_started'
  | 'in_progress'
  | 'completed'
  | 'expired'
  | 'revoked'
  | 'none'

/**
 * Lifecycle status of a staff member's onboarding link, as consumed by the
 * OverviewTab card (Task 10.2). Mirrors `OnboardingLinkStatusResponse`.
 *
 * `completion_percentage` and `last_saved_at` are populated by the backend
 * only when `state === 'in_progress'` (R13.1, R13.2); null otherwise.
 */
export interface OnboardingLinkStatus {
  /** Admin lifecycle label; defaults to 'none' when absent. */
  state: OnboardingLinkState
  /** ISO 8601 expiry of the resolved token row, or null. */
  expires_at: string | null
  /** ISO 8601 creation timestamp of the resolved token row, or null. */
  created_at: string | null
  /** ISO 8601 consumption timestamp (completed links), or null. */
  consumed_at: string | null
  /** Whole percent 0–100 while in_progress, else null. */
  completion_percentage: number | null
  /** ISO 8601 timestamp of the last draft save while in_progress, else null. */
  last_saved_at: string | null
}

/** Result of a resend (revoke + mint + email) operation. */
export interface ResendOnboardingLinkResult {
  /** Whether the invite email was dispatched. */
  onboarding_email_sent: boolean
  /** Machine error code (e.g. 'send_failed') when the send failed, else null. */
  onboarding_email_error: string | null
  /** ISO 8601 expiry of the freshly minted link, or null. */
  expires_at: string | null
}

/** Result of a revoke operation. */
export interface RevokeOnboardingLinkResult {
  /** Backend-reported status (e.g. 'revoked'). */
  status: string
}

// ---------------------------------------------------------------------------
// Wire types — what the backend actually serialises.
// ---------------------------------------------------------------------------

interface OnboardingLinkStatusWire {
  state?: string | null
  expires_at?: string | null
  created_at?: string | null
  consumed_at?: string | null
  completion_percentage?: number | string | null
  last_saved_at?: string | null
}

interface ResendOnboardingLinkWire {
  onboarding_email_sent?: boolean | null
  onboarding_email_error?: string | null
  expires_at?: string | null
}

interface RevokeOnboardingLinkWire {
  status?: string | null
}

const ONBOARDING_LINK_STATES: readonly OnboardingLinkState[] = [
  'not_started',
  'in_progress',
  'completed',
  'expired',
  'revoked',
  'none',
]

/** Coerce a wire `state` to a known `OnboardingLinkState`, defaulting to 'none'. */
function toOnboardingLinkState(value: unknown): OnboardingLinkState {
  return ONBOARDING_LINK_STATES.includes(value as OnboardingLinkState)
    ? (value as OnboardingLinkState)
    : 'none'
}

/**
 * GET /api/v2/staff/{staffId}/onboarding-link
 *
 * Returns a fully-populated `OnboardingLinkStatus`: `state` defaults to
 * 'none', all timestamps default to null, and `completion_percentage`
 * defaults to null (coerced to a finite number when present).
 */
export async function getOnboardingLinkStatus(
  staffId: string,
  signal?: AbortSignal,
): Promise<OnboardingLinkStatus> {
  const res = await apiClient.get<OnboardingLinkStatusWire>(
    `/api/v2/staff/${staffId}/onboarding-link`,
    { signal },
  )
  const data = res.data
  const pctRaw = data?.completion_percentage
  const pct = pctRaw == null ? null : toNumber(pctRaw, NaN)
  return {
    state: toOnboardingLinkState(data?.state),
    expires_at: data?.expires_at ?? null,
    created_at: data?.created_at ?? null,
    consumed_at: data?.consumed_at ?? null,
    completion_percentage: pct == null || Number.isNaN(pct) ? null : pct,
    last_saved_at: data?.last_saved_at ?? null,
  }
}

/**
 * POST /api/v2/staff/{staffId}/onboarding-link/resend
 *
 * Revokes any active link, mints a fresh 7-day one, and emails it. Returns a
 * fully-populated `ResendOnboardingLinkResult`: `onboarding_email_sent`
 * defaults to false, the error code and expiry default to null.
 */
export async function resendOnboardingLink(
  staffId: string,
  signal?: AbortSignal,
): Promise<ResendOnboardingLinkResult> {
  const res = await apiClient.post<ResendOnboardingLinkWire>(
    `/api/v2/staff/${staffId}/onboarding-link/resend`,
    {},
    { signal },
  )
  const data = res.data
  return {
    onboarding_email_sent: data?.onboarding_email_sent ?? false,
    onboarding_email_error: data?.onboarding_email_error ?? null,
    expires_at: data?.expires_at ?? null,
  }
}

/**
 * POST /api/v2/staff/{staffId}/onboarding-link/revoke
 *
 * Revokes the active onboarding link and purges its draft (idempotent 200
 * no-op when none is pending). Returns `{ status }`, defaulting to 'revoked'.
 */
export async function revokeOnboardingLink(
  staffId: string,
  signal?: AbortSignal,
): Promise<RevokeOnboardingLinkResult> {
  const res = await apiClient.post<RevokeOnboardingLinkWire>(
    `/api/v2/staff/${staffId}/onboarding-link/revoke`,
    {},
    { signal },
  )
  return {
    status: res.data?.status ?? 'revoked',
  }
}
