/**
 * Typed wrappers for fleet portal API endpoints.
 *
 * Each function consumes responses safely per the
 * `safe-api-consumption.md` rules: `?? []` on arrays, `?? 0` on
 * numbers, optional chaining on every nested access. No `as any`.
 *
 * Implements: B2B Fleet Portal task 14.1 — Requirements 18.1, 18.2.
 */
import type { AxiosRequestConfig } from 'axios'

import { fleetClient } from './client'
import type {
  BookingRequest,
  ChecklistSubmission,
  ChecklistTemplate,
  CurrentUser,
  DashboardSummary,
  DriverListItem,
  LoginResult,
  MfaChallengeResponse,
  PaginatedResponse,
  QuoteRequest,
  ReminderPreference,
  VehicleDetail,
  VehicleListItem,
  VersionInfo,
} from './types'

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Custom error thrown when MFA is required after login. */
export class MfaChallengeRequired extends Error {
  public readonly challenge: MfaChallengeResponse
  constructor(challenge: MfaChallengeResponse) {
    super('MFA verification required')
    this.name = 'MfaChallengeRequired'
    this.challenge = challenge
  }
}

export async function loginFleet(
  email: string,
  password: string,
  config?: AxiosRequestConfig,
): Promise<CurrentUser> {
  const res = await fleetClient.post<LoginResult>('/auth/login', { email, password }, config)
  const data = res.data
  if (data && 'mfa_required' in data && data.mfa_required === true) {
    throw new MfaChallengeRequired(data as MfaChallengeResponse)
  }
  return data as CurrentUser
}

export async function verifyMfa(
  mfaToken: string,
  code: string,
  method: 'totp' | 'sms' | 'backup_codes' = 'totp',
  config?: AxiosRequestConfig,
): Promise<CurrentUser> {
  const res = await fleetClient.post<CurrentUser>(
    '/auth/mfa/verify',
    { mfa_token: mfaToken, code, method },
    config,
  )
  return res.data
}

export async function logoutFleet(config?: AxiosRequestConfig): Promise<void> {
  await fleetClient.post('/auth/logout', {}, config)
}

export async function forgotPassword(
  email: string,
  config?: AxiosRequestConfig,
): Promise<void> {
  await fleetClient.post('/auth/forgot-password', { email }, config)
}

export async function resetPassword(
  token: string,
  newPassword: string,
  email: string,
  config?: AxiosRequestConfig,
): Promise<void> {
  await fleetClient.post(
    `/auth/reset-password/${encodeURIComponent(token)}`,
    { new_password: newPassword, email },
    config,
  )
}

export async function acceptInvite(
  token: string,
  newPassword: string,
  email: string,
  config?: AxiosRequestConfig,
): Promise<void> {
  await fleetClient.post(
    `/auth/accept-invite/${encodeURIComponent(token)}`,
    { new_password: newPassword, email },
    config,
  )
}

export async function getCurrentUser(
  config?: AxiosRequestConfig,
): Promise<CurrentUser | null> {
  try {
    const res = await fleetClient.get<CurrentUser>('/me', config)
    return res.data ?? null
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Version
// ---------------------------------------------------------------------------

export async function getVersion(
  config?: AxiosRequestConfig,
): Promise<VersionInfo> {
  const res = await fleetClient.get<VersionInfo>('/version', config)
  return {
    version: res.data?.version ?? 'unknown',
    build_sha: res.data?.build_sha ?? 'unknown',
  }
}

// ---------------------------------------------------------------------------
// Vehicles
// ---------------------------------------------------------------------------

export interface VehiclesPage {
  items: VehicleListItem[]
  total: number
  limit: number
  offset: number
}

export async function listVehicles(
  offset = 0,
  limit = 50,
  config?: AxiosRequestConfig,
): Promise<VehiclesPage> {
  const res = await fleetClient.get<PaginatedResponse<VehicleListItem>>('/vehicles', {
    ...config,
    params: { offset, limit },
  })
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    limit: res.data?.limit ?? limit,
    offset: res.data?.offset ?? offset,
  }
}

export async function getVehicleDetail(
  vehicleId: string,
  config?: AxiosRequestConfig,
): Promise<VehicleDetail | null> {
  const res = await fleetClient.get<VehicleDetail>(
    `/vehicles/${encodeURIComponent(vehicleId)}`,
    config,
  )
  return res.data ?? null
}

export async function logOdometer(
  vehicleId: string,
  odometerKm: number,
  config?: AxiosRequestConfig,
): Promise<void> {
  await fleetClient.post(
    `/vehicles/${encodeURIComponent(vehicleId)}/odometer`,
    { odometer_km: odometerKm },
    config,
  )
}

export async function logHours(
  vehicleId: string,
  startAt: string,
  endAt: string,
  notes: string | null,
  config?: AxiosRequestConfig,
): Promise<void> {
  await fleetClient.post(
    `/vehicles/${encodeURIComponent(vehicleId)}/hours`,
    { start_at: startAt, end_at: endAt, notes },
    config,
  )
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export async function getDashboardSummary(
  config?: AxiosRequestConfig,
): Promise<DashboardSummary> {
  const res = await fleetClient.get<DashboardSummary>('/dashboard', config)
  return {
    total_vehicles: res.data?.total_vehicles ?? 0,
    valid_wof_cof: res.data?.valid_wof_cof ?? 0,
    expiring_within_28: res.data?.expiring_within_28 ?? 0,
    service_overdue: res.data?.service_overdue ?? 0,
    checklists_completed_today: res.data?.checklists_completed_today ?? 0,
    pending_booking_requests: res.data?.pending_booking_requests ?? 0,
    pending_quote_requests: res.data?.pending_quote_requests ?? 0,
    recent_failures: res.data?.recent_failures ?? [],
  }
}

// ---------------------------------------------------------------------------
// Lower-priority endpoints — included for type-safety and forward use.
// ---------------------------------------------------------------------------

// Drivers
export async function listDrivers(
  offset = 0,
  limit = 50,
): Promise<PaginatedResponse<DriverListItem>> {
  const res = await fleetClient.get<PaginatedResponse<DriverListItem>>('/drivers', {
    params: { offset, limit },
  })
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    limit: res.data?.limit ?? limit,
    offset: res.data?.offset ?? offset,
  }
}

// Reminders
export async function listReminders(
  offset = 0,
  limit = 50,
): Promise<PaginatedResponse<ReminderPreference>> {
  const res = await fleetClient.get<PaginatedResponse<ReminderPreference>>(
    '/reminders',
    { params: { offset, limit } },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    limit: res.data?.limit ?? limit,
    offset: res.data?.offset ?? offset,
  }
}

// Bookings
export async function listBookings(
  offset = 0,
  limit = 50,
): Promise<PaginatedResponse<BookingRequest>> {
  const res = await fleetClient.get<PaginatedResponse<BookingRequest>>('/bookings', {
    params: { offset, limit },
  })
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    limit: res.data?.limit ?? limit,
    offset: res.data?.offset ?? offset,
  }
}

// Quotes
export async function listQuotes(
  offset = 0,
  limit = 50,
): Promise<PaginatedResponse<QuoteRequest>> {
  const res = await fleetClient.get<PaginatedResponse<QuoteRequest>>('/quotes', {
    params: { offset, limit },
  })
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    limit: res.data?.limit ?? limit,
    offset: res.data?.offset ?? offset,
  }
}

// Checklists
export async function listChecklistTemplates(
  offset = 0,
  limit = 50,
): Promise<PaginatedResponse<ChecklistTemplate>> {
  const res = await fleetClient.get<PaginatedResponse<ChecklistTemplate>>(
    '/checklists/templates',
    { params: { offset, limit } },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    limit: res.data?.limit ?? limit,
    offset: res.data?.offset ?? offset,
  }
}

export async function listChecklistSubmissions(
  offset = 0,
  limit = 50,
): Promise<PaginatedResponse<ChecklistSubmission>> {
  const res = await fleetClient.get<PaginatedResponse<ChecklistSubmission>>(
    '/checklists/submissions',
    { params: { offset, limit } },
  )
  return {
    items: res.data?.items ?? [],
    total: res.data?.total ?? 0,
    limit: res.data?.limit ?? limit,
    offset: res.data?.offset ?? offset,
  }
}
