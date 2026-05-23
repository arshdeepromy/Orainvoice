/**
 * Fleet Portal API contract types.
 *
 * Mirrors `app/modules/fleet_portal/schemas.py` exactly. Update both
 * sides in the same change set when the contract evolves.
 *
 * Implements: B2B Fleet Portal task 14.1 — Requirements 18.1, 18.2.
 */

export type PortalUserRole = 'fleet_admin' | 'driver'
export type BadgeColour = 'red' | 'amber' | 'green'
export type ChecklistResult = 'pass' | 'fail' | 'na'
export type ChecklistStatus = 'in_progress' | 'completed' | 'cancelled'
export type ReminderType =
  | 'wof_expiry_reminder'
  | 'cof_expiry_reminder'
  | 'service_due_reminder'
  | 'registration_expiry_reminder'
export type ReminderChannel = 'email' | 'sms'
export type ReminderRecipient = 'fleet_admin' | 'assigned_drivers'
export type LeadTimeDays = 7 | 14 | 30
export type BookingSlot = 'morning' | 'afternoon' | 'all_day'
export type BookingStatus = 'pending' | 'accepted' | 'declined' | 'completed' | 'cancelled'
export type QuoteStatus =
  | 'pending'
  | 'quoted'
  | 'accepted'
  | 'declined'
  | 'expired'
  | 'cancelled'

/** Generic paginated wrapper — every list endpoint returns this shape. */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

/** FastAPI HTTPException payload. */
export interface ErrorEnvelope {
  detail: string
}

/** Authenticated user (returned by /auth/login and GET /me). */
export interface CurrentUser {
  portal_account_id: string
  fleet_account_id: string | null
  fleet_account_name: string | null
  portal_user_role: PortalUserRole
  email: string
  first_name: string | null
  last_name: string | null
  sms_provider_configured: boolean
  must_change_password: boolean
}

/** Vehicle list / detail row. */
export interface VehicleListItem {
  customer_vehicle_id: string
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  odometer_last_recorded: number | null
  wof_expiry: string | null
  cof_expiry: string | null
  registration_expiry: string | null
  service_due_date: string | null
  wof_badge: BadgeColour | null
  cof_badge: BadgeColour | null
  service_badge: BadgeColour | null
  assigned_driver_names: string[]
}

export interface VehicleDetail extends VehicleListItem {
  vin: string | null
  chassis: string | null
  engine_no: string | null
  notes: string | null
  fleet_checklist_template_id: string | null
}

/** Reminder preference row. */
export interface ReminderPreference {
  customer_vehicle_id: string
  reminder_type: ReminderType
  enabled: boolean
  lead_time_days: LeadTimeDays
  channels: ReminderChannel[]
  recipients: ReminderRecipient[]
  service_interval_km: number | null
  service_interval_months: number | null
  rego: string | null
}

/** Dashboard summary card values. */
export interface DashboardSummary {
  total_vehicles: number
  valid_wof_cof: number
  expiring_within_28: number
  service_overdue: number
  checklists_completed_today: number
  pending_booking_requests: number
  pending_quote_requests: number
  recent_failures: ChecklistSubmission[]
}

export interface ChecklistTemplateItem {
  id: string
  category: string
  label: string
  description: string | null
  requires_photo_on_fail: boolean
  display_order: number
}

export interface ChecklistTemplate {
  id: string
  name: string
  description: string | null
  is_default: boolean
  is_system_seeded: boolean
  archived_at: string | null
  items: ChecklistTemplateItem[]
  created_at: string
  updated_at: string
}

export interface ChecklistSubmissionItem {
  id: string
  template_item_id: string
  category: string
  label: string
  requires_photo_on_fail: boolean
  result: ChecklistResult | null
  notes: string | null
  photo_urls: string[]
  recorded_at: string | null
}

export interface ChecklistSubmission {
  id: string
  customer_vehicle_id: string
  portal_account_id: string
  template_id: string
  status: ChecklistStatus
  started_at: string
  completed_at: string | null
  passed_item_count: number
  failed_item_count: number
  na_item_count: number
  items: ChecklistSubmissionItem[]
}

export interface BookingRequest {
  id: string
  customer_vehicle_id: string
  rego: string | null
  requested_by_portal_account_id: string
  requested_by_name: string | null
  preferred_date: string
  preferred_slot: BookingSlot
  service_description: string
  notes: string | null
  status: BookingStatus
  decline_reason: string | null
  booking_id: string | null
  created_at: string
  updated_at: string
}

export interface QuoteRequest {
  id: string
  customer_vehicle_id: string
  rego: string | null
  requested_by_portal_account_id: string
  requested_by_name: string | null
  service_description: string
  notes: string | null
  status: QuoteStatus
  quote_id: string | null
  quote_total: string | null
  quote_valid_until: string | null
  created_at: string
  updated_at: string
}

export interface DriverListItem {
  portal_account_id: string
  first_name: string | null
  last_name: string | null
  email: string
  phone: string | null
  is_active: boolean
  last_login_at: string | null
  assigned_vehicle_count: number
  last_submission_at: string | null
}

export interface VersionInfo {
  version: string
  build_sha: string
}

/** MFA challenge response — returned by login when MFA is enrolled. */
export interface MfaChallengeResponse {
  mfa_required: true
  mfa_token: string
  mfa_methods: Array<'totp' | 'sms' | 'backup_codes'>
  default_method: 'totp' | 'sms' | 'backup_codes'
}

/** Login response discriminator — either success or MFA challenge. */
export type LoginResult = (CurrentUser & { mfa_required?: false }) | MfaChallengeResponse
