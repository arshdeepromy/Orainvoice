/**
 * OverviewTab — Staff Detail tabbed shell, task E3.
 *
 * Sections: Personal, Employment, Tax & Pay, Schedule, Clock-in & roster
 * delivery, Skills (per design §6.2). View vs edit mode controlled at the
 * card level. On Save → PUT /api/v2/staff/:id; on 422 with
 * ``minimum_wage_below_threshold`` the MinimumWageWarningModal pops up
 * and the user can confirm to re-PUT with ``minimum_wage_override: true``.
 *
 * G2 — `residency_type` select (citizen / permanent_resident / work_visa /
 * student_visa / other, default ``citizen``); `visa_expiry_date` is
 * conditionally rendered when residency is one of work_visa/student_visa/
 * other; switching residency back to citizen/PR hides the input but does
 * not null the value.
 *
 * G1 — amber inline warning + quick-set input above the Employment
 *      section when `staff.employee_id === null`.
 * G3 — amber inline warning + quick-set date picker above the Employment
 *      section when `staff.employment_start_date === null`.
 *
 * IRD + bank inputs honour the `is_masked_*` heuristic — when typed
 * fresh the raw value is sent as plaintext; when cleared the field is
 * sent as null (which the backend skips so the existing ciphertext
 * stays put).
 *
 * Refs: Staff Management Phase 1 — R2, R3, R4, R6, G1, G2, G3.
 *
 * Logic copied verbatim; presentation remapped onto the design-system tokens.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui'
import WorkSchedule, { type WeekSchedule } from '@/components/WorkSchedule'
import MinimumWageWarningModal from '../components/MinimumWageWarningModal'
import PayRateHistoryPanel from '../components/PayRateHistoryPanel'
import RecurringAllowancesPanel from '../components/RecurringAllowancesPanel'
import ThisMonthPanel from '../components/ThisMonthPanel'
import CreateAccountModal from '../components/CreateAccountModal'
import StaffPhotoUploader from '../components/StaffPhotoUploader'
import AuthorizedAvatar from '@/components/AuthorizedAvatar'
import {
  getStaffMonthStats,
  getOnboardingLinkStatus,
  resendOnboardingLink,
  revokeOnboardingLink,
  type StaffMonthStats,
  type OnboardingLinkStatus,
} from '@/api/staff'

// ---------------------------------------------------------------------------
// Types — mirrors `app/modules/staff/schemas.py::StaffMemberResponse`.
// ---------------------------------------------------------------------------

type ResidencyType =
  | 'citizen'
  | 'permanent_resident'
  | 'work_visa'
  | 'student_visa'
  | 'other'

const VISA_RESIDENCY_TYPES: ResidencyType[] = [
  'work_visa',
  'student_visa',
  'other',
]

interface StaffMember {
  id: string
  org_id: string
  user_id: string | null
  name: string
  first_name: string
  last_name: string | null
  email: string | null
  phone: string | null
  employee_id: string | null
  position: string | null
  reporting_to: string | null
  reporting_to_name: string | null
  shift_start: string | null
  shift_end: string | null
  role_type: string
  hourly_rate: string | null
  overtime_rate: string | null
  is_active: boolean
  availability_schedule: WeekSchedule
  skills: string[]
  // Phase 1 employment record
  employment_start_date: string | null
  employment_end_date: string | null
  employment_type: string
  employment_basis?: string | null
  working_arrangement?: string | null
  standard_hours_per_week: string | null
  tax_code: string | null
  ird_number: string | null // masked on the wire
  student_loan: boolean
  kiwisaver_enrolled: boolean
  kiwisaver_employee_rate: string | null
  kiwisaver_employer_rate: string
  bank_account_number: string | null // masked on the wire
  probation_end_date: string | null
  residency_type: ResidencyType
  visa_expiry_date: string | null
  self_service_clock_enabled: boolean
  on_file_photo_url: string | null
  emergency_contact_name: string | null
  emergency_contact_phone: string | null
  weekly_roster_email_enabled: boolean
  weekly_roster_sms_enabled: boolean
  last_pay_review_date: string | null
  employment_agreement_upload_id: string | null
  // Per-staff pay cycle (per-staff-pay-cycle feature). Read-only resolved
  // fields; all null/false when the staff member has no resolved cycle
  // (no matching assignment and no default — REQ 5.3).
  pay_cycle_id: string | null
  pay_cycle_name: string | null
  pay_cycle_is_default: boolean
}

/**
 * Active pay cycle as returned by `GET /api/v2/pay-cycles/` (the endpoint
 * filters to `active == True`, so every item is an Active_Cycle). Mirrors the
 * shape consumed by the StaffList Add modal and the timesheets/pay-run tabs.
 */
interface PayCycle {
  id: string
  name: string
  frequency: string
  anchor_date: string
  pay_date_offset_days: number
  is_default: boolean
}

interface OverviewTabProps {
  staffId: string
  onDirtyChange?: (checker: () => boolean) => void
}

// ---------------------------------------------------------------------------
// Form-state shape — mirrors StaffMemberUpdate but kept as strings for
// inputs (we coerce on submit). Optional fields use `undefined` for "leave
// alone" and `null` for "clear".
// ---------------------------------------------------------------------------

interface FormState {
  first_name: string
  last_name: string
  email: string
  phone: string
  emergency_contact_name: string
  emergency_contact_phone: string
  on_file_photo_url: string

  employment_type: string
  employment_start_date: string
  employment_end_date: string
  position: string
  employee_id: string
  reporting_to: string
  role_type: string
  employment_basis: string
  working_arrangement: string
  probation_end_date: string
  residency_type: ResidencyType
  visa_expiry_date: string
  standard_hours_per_week: string

  tax_code: string
  ird_number: string
  kiwisaver_enrolled: boolean
  kiwisaver_employee_rate: string
  kiwisaver_employer_rate: string
  student_loan: boolean
  hourly_rate: string
  overtime_rate: string
  bank_account_number: string

  self_service_clock_enabled: boolean
  weekly_roster_email_enabled: boolean
  weekly_roster_sms_enabled: boolean

  skills: string

  availability_schedule: WeekSchedule

  /**
   * Selected pay cycle (per-staff-pay-cycle feature). Empty string means
   * "Use organisation default" — clears any staff-level assignment so the
   * staff member resolves to the org Default_Cycle (REQ 1.4, 3.3).
   */
  pay_cycle_id: string
}

const EMPTY_FORM: FormState = {
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  emergency_contact_name: '',
  emergency_contact_phone: '',
  on_file_photo_url: '',

  employment_type: 'permanent',
  employment_start_date: '',
  employment_end_date: '',
  position: '',
  employee_id: '',
  reporting_to: '',
  role_type: 'employee',
  employment_basis: 'full_time',
  working_arrangement: 'rostered',
  probation_end_date: '',
  residency_type: 'citizen',
  visa_expiry_date: '',
  standard_hours_per_week: '',

  tax_code: '',
  ird_number: '',
  kiwisaver_enrolled: false,
  kiwisaver_employee_rate: '',
  kiwisaver_employer_rate: '3.00',
  student_loan: false,
  hourly_rate: '',
  overtime_rate: '',
  bank_account_number: '',

  self_service_clock_enabled: false,
  weekly_roster_email_enabled: true,
  weekly_roster_sms_enabled: false,

  skills: '',
  availability_schedule: {},

  pay_cycle_id: '',
}

// A masked display value (from the API) always contains asterisks; a real,
// freshly-typed IRD / bank number never does. Detecting "contains an asterisk"
// is therefore both sufficient and immune to mask-format drift between the
// frontend and the backend mask helpers (app/modules/staff/security.py).
function isMaskedIrd(v: string | null | undefined): boolean {
  return !!v && v.includes('*')
}
function isMaskedBank(v: string | null | undefined): boolean {
  return !!v && v.includes('*')
}

/**
 * Format an ISO timestamp (e.g. users.last_login_at) to a readable date.
 * Returns "—" for null/empty/unparseable values (R9.4).
 */
function formatLastSignIn(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/**
 * Format an ISO timestamp to a readable date (no time component).
 * Returns "—" for null/empty/unparseable values.
 */
function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/**
 * Format an ISO timestamp to a readable date + time (for "last saved").
 * Returns "—" for null/empty/unparseable values.
 */
function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function staffToForm(s: StaffMember): FormState {
  return {
    first_name: s.first_name ?? '',
    last_name: s.last_name ?? '',
    email: s.email ?? '',
    phone: s.phone ?? '',
    emergency_contact_name: s.emergency_contact_name ?? '',
    emergency_contact_phone: s.emergency_contact_phone ?? '',
    on_file_photo_url: s.on_file_photo_url ?? '',

    employment_type: s.employment_type ?? 'permanent',
    employment_start_date: s.employment_start_date ?? '',
    employment_end_date: s.employment_end_date ?? '',
    position: s.position ?? '',
    employee_id: s.employee_id ?? '',
    reporting_to: s.reporting_to ?? '',
    role_type: s.role_type ?? 'employee',
    employment_basis: s.employment_basis ?? 'full_time',
    working_arrangement: s.working_arrangement ?? 'rostered',
    probation_end_date: s.probation_end_date ?? '',
    residency_type: (s.residency_type ?? 'citizen') as ResidencyType,
    visa_expiry_date: s.visa_expiry_date ?? '',
    standard_hours_per_week: s.standard_hours_per_week ?? '',

    tax_code: s.tax_code ?? '',
    ird_number: s.ird_number ?? '',
    kiwisaver_enrolled: !!s.kiwisaver_enrolled,
    kiwisaver_employee_rate: s.kiwisaver_employee_rate ?? '',
    kiwisaver_employer_rate: s.kiwisaver_employer_rate ?? '3.00',
    student_loan: !!s.student_loan,
    hourly_rate: s.hourly_rate ?? '',
    overtime_rate: s.overtime_rate ?? '',
    bank_account_number: s.bank_account_number ?? '',

    self_service_clock_enabled: !!s.self_service_clock_enabled,
    weekly_roster_email_enabled: !!s.weekly_roster_email_enabled,
    weekly_roster_sms_enabled: !!s.weekly_roster_sms_enabled,

    skills: (s.skills ?? []).join(', '),
    availability_schedule:
      s.availability_schedule && typeof s.availability_schedule === 'object'
        ? { ...s.availability_schedule }
        : {},

    // Prefill the pay-cycle selector from the resolved cycle ONLY when it is an
    // explicit staff-level assignment (pay_cycle_is_default === false). When the
    // staff resolves via the org default, leave the empty "Use organisation
    // default" option selected (REQ 1.3, 1.4).
    pay_cycle_id:
      s.pay_cycle_id && !s.pay_cycle_is_default ? s.pay_cycle_id : '',
  }
}

/**
 * Build the PUT payload from form state. Encodes the IRD/bank masking
 * heuristic: a value identical to the masked display we received → not
 * sent (undefined). A cleared field → null. Fresh plaintext → string.
 */
function formToPayload(
  form: FormState,
  original: StaffMember,
  overrideMinWage: boolean,
  includePayCycle: boolean,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    first_name: form.first_name.trim() || null,
    last_name: form.last_name.trim() || null,
    email: form.email.trim() || null,
    phone: form.phone.trim() || null,
    emergency_contact_name: form.emergency_contact_name.trim() || null,
    emergency_contact_phone: form.emergency_contact_phone.trim() || null,
    on_file_photo_url: form.on_file_photo_url.trim() || null,
    position: form.position.trim() || null,
    employee_id: form.employee_id.trim() || null,
    reporting_to: form.reporting_to || null,
    role_type: form.role_type || null,
    employment_basis: form.employment_basis || null,
    working_arrangement: form.working_arrangement || null,

    employment_type: form.employment_type || null,
    employment_start_date: form.employment_start_date || null,
    employment_end_date: form.employment_end_date || null,
    probation_end_date: form.probation_end_date || null,
    residency_type: form.residency_type,
    // Preserve visa_expiry_date even when the residency switch hides
    // the input (G2). Only null it out when the user explicitly clears
    // the field while it is visible.
    visa_expiry_date: form.visa_expiry_date || null,
    standard_hours_per_week: form.standard_hours_per_week || null,

    tax_code: form.tax_code || null,
    kiwisaver_enrolled: form.kiwisaver_enrolled,
    kiwisaver_employee_rate: form.kiwisaver_employee_rate || null,
    kiwisaver_employer_rate: form.kiwisaver_employer_rate || null,
    student_loan: form.student_loan,
    hourly_rate: form.hourly_rate || null,
    overtime_rate: form.overtime_rate || null,

    self_service_clock_enabled: form.self_service_clock_enabled,
    weekly_roster_email_enabled: form.weekly_roster_email_enabled,
    weekly_roster_sms_enabled: form.weekly_roster_sms_enabled,

    skills: form.skills
      ? form.skills.split(',').map((s) => s.trim()).filter(Boolean)
      : [],
    // Schedule only applies to a Fixed working arrangement; for Rostered /
    // Casual it is cleared so stale work-days don't linger (mirrors the modal).
    availability_schedule:
      form.working_arrangement === 'fixed'
        ? (form.availability_schedule ?? {})
        : {},
  }

  // IRD: skip when unchanged-masked; null on explicit clear; otherwise plaintext.
  const irdOriginal = original.ird_number ?? ''
  if (form.ird_number === '') {
    // Treat empty-after-non-empty as explicit clear; empty-from-empty as no-op.
    payload.ird_number = irdOriginal ? null : null
  } else if (form.ird_number === irdOriginal && isMaskedIrd(form.ird_number)) {
    // Unchanged masked display — don't send.
  } else if (isMaskedIrd(form.ird_number)) {
    // User pasted the masked display back → also don't send (defensive).
  } else {
    payload.ird_number = form.ird_number
  }

  const bankOriginal = original.bank_account_number ?? ''
  if (form.bank_account_number === '') {
    payload.bank_account_number = bankOriginal ? null : null
  } else if (
    form.bank_account_number === bankOriginal &&
    isMaskedBank(form.bank_account_number)
  ) {
    // Unchanged masked display — don't send.
  } else if (isMaskedBank(form.bank_account_number)) {
    // Defensive — masked display somehow re-typed.
  } else {
    payload.bank_account_number = form.bank_account_number
  }

  if (overrideMinWage) {
    payload.minimum_wage_override = true
  }
  // Per-staff pay cycle (REQ 2.2, 3.3). Only send when the org has at least one
  // active cycle and the selector is therefore shown — otherwise the field is
  // hidden and the existing assignment must be left untouched. A chosen cycle
  // sends its uuid (set/replace); "Use organisation default" (empty string)
  // sends null to clear any existing staff-level assignment so the staff member
  // resolves to the org Default_Cycle.
  if (includePayCycle) {
    payload.pay_cycle_id = form.pay_cycle_id || null
  }
  return payload
}

// ---------------------------------------------------------------------------
// Inline warning component (G1 + G3).
// ---------------------------------------------------------------------------

interface InlineWarningProps {
  testId: string
  message: React.ReactNode
  children?: React.ReactNode
}

function InlineWarning({ testId, message, children }: InlineWarningProps) {
  return (
    <div
      data-testid={testId}
      role="status"
      className="mb-3 rounded-ctl border border-warn/40 bg-warn-soft p-3"
    >
      <p className="text-sm text-warn">{message}</p>
      {children && <div className="mt-2 flex flex-wrap gap-2">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ManagerFallbackChip — Phase 3 D9 (cross-phase X7).
//
// Walks `staff.reporting_to` up the chain to find a manager with a
// `user_id`. If the chain doesn't terminate at a user-linked manager,
// the running-late SMS will fall back to the first org_admin — surface
// that with an amber chip on Overview so the org owner can fix the
// chain before it bites in production.
//
// Strategy: page through the staff list (max 200 active rows) and
// build an in-memory map keyed by staff id. Walk the chain locally,
// stopping at a manager with a non-null `user_id` or after 10 hops
// (cycle guard). The component is best-effort — when the staff list
// can't be loaded the chip is hidden so a permission glitch doesn't
// surface as a misleading warning.
// ---------------------------------------------------------------------------

interface ManagerFallbackChipStaff {
  id: string
  reporting_to: string | null
}

interface StaffListRow {
  id: string
  user_id: string | null
  reporting_to: string | null
  first_name?: string | null
  last_name?: string | null
}

function ManagerFallbackChip({ staff }: { staff: ManagerFallbackChipStaff }) {
  const [resolution, setResolution] = useState<
    'unknown' | 'resolves_to_user' | 'resolves_to_org_admin' | 'no_manager_set'
  >('unknown')

  useEffect(() => {
    if (!staff?.id) return
    if (!staff.reporting_to) {
      setResolution('no_manager_set')
      return
    }
    const controller = new AbortController()
    const load = async () => {
      try {
        const res = await apiClient.get<{
          staff: StaffListRow[]
          total: number
        }>('/api/v2/staff', {
          params: { is_active: 'true', page_size: 200 },
          signal: controller.signal,
        })
        if (controller.signal.aborted) return
        const list = res.data?.staff ?? []
        const byId = new Map<string, StaffListRow>()
        for (const row of list) {
          if (row?.id) byId.set(row.id, row)
        }
        let cursor: string | null = staff.reporting_to ?? null
        const seen = new Set<string>()
        let resolvedToUser = false
        let hops = 0
        while (cursor && !seen.has(cursor) && hops < 10) {
          seen.add(cursor)
          const manager = byId.get(cursor) ?? null
          if (!manager) break
          if (manager.user_id) {
            resolvedToUser = true
            break
          }
          cursor = manager.reporting_to ?? null
          hops += 1
        }
        if (controller.signal.aborted) return
        setResolution(
          resolvedToUser ? 'resolves_to_user' : 'resolves_to_org_admin',
        )
      } catch {
        if (!controller.signal.aborted) setResolution('unknown')
      }
    }
    void load()
    return () => controller.abort()
  }, [staff?.id, staff?.reporting_to])

  if (resolution === 'unknown' || resolution === 'resolves_to_user') {
    return null
  }

  const message =
    resolution === 'no_manager_set'
      ? 'No manager set — running-late SMS will go to the org owner instead.'
      : 'Manager has no app login — running-late SMS will go to the org owner instead.'

  return (
    <div
      role="status"
      data-testid="manager-fallback-chip"
      className="mb-3 flex items-start gap-2 rounded-ctl border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn"
    >
      <span aria-hidden="true" className="text-base leading-none">
        ⚠
      </span>
      <p>{message}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component.
// ---------------------------------------------------------------------------

const RESIDENCY_OPTIONS: { value: ResidencyType; label: string }[] = [
  { value: 'citizen', label: 'Citizen' },
  { value: 'permanent_resident', label: 'Permanent resident' },
  { value: 'work_visa', label: 'Work visa' },
  { value: 'student_visa', label: 'Student visa' },
  { value: 'other', label: 'Other' },
]

const TAX_CODE_OPTIONS = [
  '',
  'M',
  'ME',
  'S',
  'SH',
  'ST',
  'SB',
  'CAE',
  'NSW',
  'ND',
]

const KIWISAVER_RATES = ['3.00', '4.00', '6.00', '8.00', '10.00']

// ---------------------------------------------------------------------------
// OnboardingLinkCard — staff-detail "Onboarding link" lifecycle card (R10, R13).
//
// On mount fetches GET /staff/{id}/onboarding-link via the api/staff.ts status
// helper and renders the lifecycle state (not_started / in_progress / completed
// / expired / revoked / none) with Resend / Revoke / Send actions. When the
// state is in_progress it also shows a progress bar with the server-computed
// completion percentage and the last-saved timestamp (R13.2, R13.5).
//
// - Resend → POST .../resend; surfaces an inline error when the email send
//   fails (onboarding_email_sent === false), then refetches the status.
// - Revoke → POST .../revoke, then refetches the status.
// - Send (from a terminal/none state) → calls resend, which revokes any prior
//   token (a no-op when none), mints a fresh one, and emails it.
//
// Safe API consumption throughout: the helper already defaults to
// `state: 'none'` and null timestamps, and any fetch failure here falls back
// to a 'none' status so the tab never crashes.
// ---------------------------------------------------------------------------

// Lifecycle states that have an active/usable link → show Resend + Revoke.
// Per design.md §Frontend Design, revoked/expired/none have no active link and
// instead surface a single "Send onboarding link" button (which mints fresh).
const ONBOARDING_ACTION_STATES: ReadonlySet<OnboardingLinkStatus['state']> =
  new Set(['not_started', 'in_progress'])

const ONBOARDING_NONE_STATUS: OnboardingLinkStatus = {
  state: 'none',
  expires_at: null,
  created_at: null,
  consumed_at: null,
  completion_percentage: null,
  last_saved_at: null,
}

function OnboardingLinkCard({ staffId }: { staffId: string }) {
  const [status, setStatus] = useState<OnboardingLinkStatus>(
    ONBOARDING_NONE_STATUS,
  )
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<null | 'resend' | 'revoke' | 'send'>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const cardCls = 'rounded-card border border-border bg-card shadow-card mb-4'

  // Fetch status; default to a 'none' status on any failure so the tab never
  // crashes (R13.5, safe-api-consumption).
  const fetchStatus = useCallback(
    async (signal?: AbortSignal): Promise<void> => {
      try {
        const res = await getOnboardingLinkStatus(staffId, signal)
        if (signal?.aborted) return
        setStatus(res ?? ONBOARDING_NONE_STATUS)
      } catch {
        if (signal?.aborted) return
        setStatus(ONBOARDING_NONE_STATUS)
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [staffId],
  )

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setActionError(null)
    void fetchStatus(controller.signal)
    return () => controller.abort()
  }, [fetchStatus])

  const handleResend = useCallback(
    async (kind: 'resend' | 'send') => {
      setBusy(kind)
      setActionError(null)
      try {
        const res = await resendOnboardingLink(staffId)
        if (!res.onboarding_email_sent) {
          setActionError(
            'The onboarding email could not be sent. Please check the staff email address and try again.',
          )
        }
        await fetchStatus()
      } catch {
        setActionError('Could not send the onboarding link. Please try again.')
      } finally {
        setBusy(null)
      }
    },
    [fetchStatus, staffId],
  )

  const handleRevoke = useCallback(async () => {
    setBusy('revoke')
    setActionError(null)
    try {
      await revokeOnboardingLink(staffId)
      await fetchStatus()
    } catch {
      setActionError('Could not revoke the onboarding link. Please try again.')
    } finally {
      setBusy(null)
    }
  }, [fetchStatus, staffId])

  const pct = Math.max(0, Math.min(100, status.completion_percentage ?? 0))
  const showActions = ONBOARDING_ACTION_STATES.has(status.state)

  // Headline + secondary line per lifecycle state (R13.5).
  let headline = 'No active onboarding link'
  let detail: string | null = null
  switch (status.state) {
    case 'not_started':
      headline = 'Onboarding link sent — not started yet'
      detail = `Expires ${formatDate(status.expires_at)}`
      break
    case 'in_progress':
      headline = 'Onboarding in progress'
      detail = `Expires ${formatDate(status.expires_at)}`
      break
    case 'completed':
      headline = 'Onboarding completed'
      detail = `Completed ${formatDate(status.consumed_at)}`
      break
    case 'expired':
      headline = 'Onboarding link expired'
      detail = `Expired ${formatDate(status.expires_at)}`
      break
    case 'revoked':
      headline = 'Onboarding link revoked'
      break
    case 'none':
    default:
      headline = 'No active onboarding link'
      break
  }

  const btnSecondaryCls =
    'inline-flex min-h-[44px] items-center justify-center rounded-ctl border border-border px-3 text-[13px] font-medium text-text hover:bg-canvas disabled:opacity-50'
  const btnPrimaryCls =
    'inline-flex min-h-[44px] items-center justify-center rounded-ctl bg-accent px-3 text-[13px] font-semibold text-white hover:brightness-95 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card'

  return (
    <section
      className={cardCls}
      aria-label="Onboarding link"
      data-testid="onboarding-link-card"
    >
      <div className="p-5">
        <div className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-muted-2">
          Onboarding link
        </div>

        {loading ? (
          <p className="text-[13px] text-muted">Loading…</p>
        ) : (
          <>
            <p
              className="text-[13px] font-medium text-text"
              data-testid="onboarding-link-state"
            >
              {headline}
            </p>
            {detail && (
              <p className="mt-1 text-[12px] leading-relaxed text-muted">
                {detail}
              </p>
            )}

            {/* in_progress → progress bar + percentage + last-saved (R13.2). */}
            {status.state === 'in_progress' && (
              <div className="mt-3" data-testid="onboarding-progress">
                <div className="flex items-center justify-between">
                  <span className="text-[12px] text-muted">Completion</span>
                  <span className="mono text-[12px] font-medium text-text">
                    {pct}%
                  </span>
                </div>
                <div
                  className="mt-1 h-2 w-full overflow-hidden rounded-full bg-canvas"
                  role="progressbar"
                  aria-valuenow={pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="h-full rounded-full bg-accent transition-all"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <p className="mt-2 text-[12px] text-muted">
                  Last saved {formatDateTime(status.last_saved_at)}
                </p>
              </div>
            )}

            {actionError && (
              <p
                role="alert"
                data-testid="onboarding-link-error"
                className="mt-3 rounded-ctl border border-danger/40 bg-danger-soft px-3 py-2 text-[12px] text-danger"
              >
                {actionError}
              </p>
            )}

            <div className="mt-4 flex flex-wrap gap-2">
              {showActions && (
                <>
                  <button
                    type="button"
                    onClick={() => void handleResend('resend')}
                    disabled={busy !== null}
                    className={btnSecondaryCls}
                    data-testid="onboarding-resend-btn"
                  >
                    {busy === 'resend' ? 'Sending…' : 'Resend'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleRevoke()}
                    disabled={busy !== null}
                    className={btnSecondaryCls}
                    data-testid="onboarding-revoke-btn"
                  >
                    {busy === 'revoke' ? 'Revoking…' : 'Revoke'}
                  </button>
                </>
              )}
              {(status.state === 'none' ||
                status.state === 'revoked' ||
                status.state === 'expired') && (
                <button
                  type="button"
                  onClick={() => void handleResend('send')}
                  disabled={busy !== null}
                  className={btnPrimaryCls}
                  data-testid="onboarding-send-btn"
                >
                  {busy === 'send' ? 'Sending…' : 'Send onboarding link'}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  )
}


export default function OverviewTab({ staffId, onDirtyChange }: OverviewTabProps) {
  const [staff, setStaff] = useState<StaffMember | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // Min-wage modal state
  const [minWageModal, setMinWageModal] = useState<{
    threshold: number
    proposed: number
  } | null>(null)

  // Quick-set inputs (G1 + G3)
  const [quickEmployeeId, setQuickEmployeeId] = useState('')
  const [quickStartDate, setQuickStartDate] = useState('')
  const [quickSaving, setQuickSaving] = useState(false)

  // Month stats — lifted here so both the This-month panel and the Account
  // panel share a single fetch (single source, R8.6). Keyed on staffId with
  // an AbortController (R8.7).
  const [monthStats, setMonthStats] = useState<StaffMonthStats | null>(null)
  const [monthStatsFailed, setMonthStatsFailed] = useState(false)

  // All staff (for the "Reports to" manager picker in edit mode). Best-effort;
  // an empty list just yields a manager dropdown with only "— None —".
  const [allStaff, setAllStaff] = useState<
    { id: string; first_name: string; last_name: string | null; position: string | null }[]
  >([])
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get('/staff', { baseURL: '/api/v2', params: { page_size: '200' }, signal: controller.signal })
      .then((res) => setAllStaff(((res.data as any)?.staff ?? []) as typeof allStaff))
      .catch(() => { /* non-blocking */ })
    return () => controller.abort()
  }, [])

  // Active pay cycles for the per-staff pay-cycle selector (per-staff-pay-cycle).
  // The endpoint returns only active cycles wrapped in `{ items, total }`;
  // consume defensively and default to an empty list so the selector simply
  // hides (and the "configure under Timesheets → Settings" hint shows) when
  // none exist (REQ 1.1, 1.5, 1.6). AbortController cancels on unmount.
  const [payCycles, setPayCycles] = useState<PayCycle[]>([])
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .get<{ items: PayCycle[]; total: number }>('/api/v2/pay-cycles/', {
        signal: controller.signal,
      })
      .then((res) => setPayCycles(res.data?.items ?? []))
      .catch(() => setPayCycles([]))
    return () => controller.abort()
  }, [])

  // Deep-link: open directly in edit mode when navigated with ?edit=1 (the
  // Staff list "Edit" action routes here). One-shot, then the param is stripped
  // so a refresh / back-navigation doesn't re-enter edit mode.
  const [searchParams, setSearchParams] = useSearchParams()
  const autoEditAppliedRef = useRef(false)
  useEffect(() => {
    if (autoEditAppliedRef.current) return
    if (staff && searchParams.get('edit') === '1') {
      autoEditAppliedRef.current = true
      setEditing(true)
      const next = new URLSearchParams(searchParams)
      next.delete('edit')
      setSearchParams(next, { replace: true })
    }
  }, [staff, searchParams, setSearchParams])

  // Create-account modal (R9.5, R9.6) — opened from the Account panel when
  // the staff member has no linked user account.
  const [createAccountOpen, setCreateAccountOpen] = useState(false)

  // ------------------------------------------------------------------
  // Load staff. AbortController on every useEffect.
  // ------------------------------------------------------------------
  const loadStaff = useCallback(
    async (signal?: AbortSignal): Promise<StaffMember | null> => {
      setLoading(true)
      setLoadError(null)
      try {
        const res = await apiClient.get<StaffMember>(
          `/api/v2/staff/${staffId}`,
          signal ? { signal } : undefined,
        )
        if (signal?.aborted) return null
        const data = (res.data as StaffMember | undefined) ?? null
        if (data) {
          setStaff(data)
          setForm(staffToForm(data))
        }
        return data
      } catch (err) {
        if (signal?.aborted) return null
        setLoadError('Failed to load staff record.')
        return null
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [staffId],
  )

  useEffect(() => {
    const controller = new AbortController()
    void loadStaff(controller.signal)
    return () => controller.abort()
  }, [loadStaff])

  // ------------------------------------------------------------------
  // Month stats fetch — single source shared by the This-month panel and
  // the Account panel (R8.6). Keyed on staffId; aborts on unmount / change.
  // ------------------------------------------------------------------
  useEffect(() => {
    const controller = new AbortController()
    setMonthStats(null)
    setMonthStatsFailed(false)
    const fetchStats = async () => {
      try {
        const data = await getStaffMonthStats(
          staffId,
          'this_month',
          controller.signal,
        )
        if (controller.signal.aborted) return
        setMonthStats(data)
      } catch (err) {
        if (controller.signal.aborted) return
        setMonthStatsFailed(true)
      }
    }
    void fetchStats()
    return () => controller.abort()
  }, [staffId])

  // ------------------------------------------------------------------
  // Dirty checker registration for the parent shell.
  // ------------------------------------------------------------------
  const editingRef = useRef(false)
  editingRef.current = editing
  useEffect(() => {
    onDirtyChange?.(() => editingRef.current)
  }, [onDirtyChange])

  // ------------------------------------------------------------------
  // Save flow.
  // ------------------------------------------------------------------
  const submitSave = useCallback(
    async (overrideMinWage: boolean) => {
      if (!staff) return
      // A Fixed working arrangement requires at least one configured work day.
      if (
        form.working_arrangement === 'fixed' &&
        Object.keys(form.availability_schedule ?? {}).length === 0
      ) {
        setFormError(
          'A Fixed working arrangement requires a schedule — enable at least one work day and set its hours.',
        )
        return
      }
      setSaving(true)
      setFormError(null)
      try {
        const payload = formToPayload(form, staff, overrideMinWage, payCycles.length > 0)
        const res = await apiClient.put<StaffMember>(
          `/api/v2/staff/${staffId}`,
          payload,
        )
        const updated = (res.data as StaffMember | undefined) ?? null
        if (updated) {
          setStaff(updated)
          setForm(staffToForm(updated))
        }
        setEditing(false)
        setMinWageModal(null)
      } catch (err) {
        const response = (err as { response?: { status?: number; data?: any } })
          .response
        const detail = response?.data?.detail
        // 422 with min-wage payload → trigger modal.
        if (
          response?.status === 422 &&
          typeof detail === 'object' &&
          detail !== null &&
          (detail as { detail?: string; reason?: string }).detail ===
            'minimum_wage_below_threshold'
        ) {
          const thresholdRaw =
            (detail as { threshold?: number | string }).threshold ?? 23.15
          const threshold =
            typeof thresholdRaw === 'string'
              ? parseFloat(thresholdRaw)
              : thresholdRaw
          const proposed = parseFloat(form.hourly_rate || '0') || 0
          setMinWageModal({ threshold, proposed })
          return
        }
        // Fallback: backend sometimes wraps the literal string in detail.
        if (
          response?.status === 422 &&
          typeof detail === 'string' &&
          detail.includes('minimum_wage_below_threshold')
        ) {
          const proposed = parseFloat(form.hourly_rate || '0') || 0
          setMinWageModal({ threshold: 23.15, proposed })
          return
        }
        const message =
          typeof detail === 'string'
            ? detail
            : 'Failed to save changes. Please try again.'
        setFormError(message)
      } finally {
        setSaving(false)
      }
    },
    [form, staff, staffId],
  )

  const handleSave = useCallback(() => {
    void submitSave(false)
  }, [submitSave])

  const handleConfirmMinWage = useCallback(() => {
    void submitSave(true)
  }, [submitSave])

  const handleCancel = useCallback(() => {
    if (staff) setForm(staffToForm(staff))
    setEditing(false)
    setFormError(null)
  }, [staff])

  // ------------------------------------------------------------------
  // Quick-set actions (G1 / G3 banners).
  // ------------------------------------------------------------------
  const quickSet = useCallback(
    async (patch: Record<string, unknown>) => {
      setQuickSaving(true)
      try {
        await apiClient.put(`/api/v2/staff/${staffId}`, patch)
        setQuickEmployeeId('')
        setQuickStartDate('')
        await loadStaff()
      } catch {
        // Surface failure inline; the banner stays visible.
      } finally {
        setQuickSaving(false)
      }
    },
    [loadStaff, staffId],
  )

  // ------------------------------------------------------------------
  // Render helpers.
  // ------------------------------------------------------------------
  const showVisaExpiry = useMemo(
    () => VISA_RESIDENCY_TYPES.includes(form.residency_type),
    [form.residency_type],
  )

  const updateForm = useCallback(<K extends keyof FormState>(
    key: K,
    value: FormState[K],
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }, [])

  if (loading) {
    return <div className="p-6 text-muted">Loading…</div>
  }
  if (loadError || !staff) {
    return (
      <div role="alert" className="p-6 text-danger">
        {loadError ?? 'Staff record not found.'}
      </div>
    )
  }

  // Class constants restyled to the StaffDetail.html design language
  // (.input / .ro / .field label / .card / .sec-head). Shared across every
  // card so the whole tab matches the prototype from one place.
  const inputCls =
    'h-[42px] w-full rounded-ctl border border-border-strong bg-card px-[13px] text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'
  const readonlyCls =
    'flex h-[42px] items-center rounded-ctl border border-border bg-canvas px-[13px] text-[13.5px] text-text'
  const labelCls =
    'block text-[12.5px] font-medium text-muted mb-[7px]'
  const cardCls =
    'rounded-card border border-border bg-card shadow-card mb-4'
  // .sec-head — mono uppercase micro-label with a bottom divider.
  const sectionHeaderCls =
    'border-b border-border px-5 py-4 font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-muted-2'

  // Hero presentation — large avatar initials + "position · employee ID ·
  // branch" sub-line. Per R7.2/R7.3 every one of the three components renders,
  // substituting "—" when absent (never dropped). The employee ID uses the
  // monospace font per the design system (R14.4). Branch resolves to "—"
  // because the staff response exposes no branch/location *name* (only opaque
  // location_assignments ids), so it is rendered as an absent component.
  const initials =
    (staff.name || '?')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase() ?? '')
      .join('') || '?'
  const sublinePosition = staff.position?.trim() || '—'
  const sublineEmployeeId = staff.employee_id?.trim() || '—'
  const sublineBranch = '—'

  return (
    <div className="mx-auto max-w-[1280px] p-6" data-testid="overview-tab">
      {/* Breadcrumb */}
      <div className="mb-3 text-[13px] text-muted">
        <Link to="/staff" className="hover:text-text">Staff</Link>
        <span className="mx-2 text-muted-2">/</span>
        <span className="text-text">{staff.name}</span>
      </div>

      {/* Page head — staff hero + actions (StaffDetail.html .page-head). */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <AuthorizedAvatar
            src={staff.on_file_photo_url}
            initials={initials}
            className="h-16 w-16 flex-shrink-0 overflow-hidden rounded-[16px] bg-purple"
            fallbackClassName="text-2xl font-bold text-white"
            alt={`Profile photo of ${staff.name}`}
          />
          <div>
            <div className="flex items-center gap-[10px]">
              <h1 className="text-2xl font-bold tracking-[-0.02em] text-text">{staff.name}</h1>
              <Badge variant={staff.is_active ? 'active' : 'neutral'}>
                {staff.is_active ? 'Active' : 'Inactive'}
              </Badge>
            </div>
            <p className="mt-1 text-sm text-muted" data-testid="overview-hero-subline">
              <span>{sublinePosition}</span>
              <span className="mx-2 text-muted-2" aria-hidden="true">·</span>
              <span className="font-mono">{sublineEmployeeId}</span>
              <span className="mx-2 text-muted-2" aria-hidden="true">·</span>
              <span>{sublineBranch}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {!editing && (
            <>
              {staff.user_id && (
                <span className="mr-1"><Badge variant="sent">Has login</Badge></span>
              )}
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="min-h-[44px] rounded-ctl border border-border px-4 py-2 text-sm font-medium text-text hover:bg-canvas"
              >
                Edit
              </button>
            </>
          )}
          {editing && (
            <>
              <button
                type="button"
                onClick={handleCancel}
                disabled={saving}
                className="min-h-[44px] rounded-ctl border border-border px-4 py-2 text-sm font-medium text-text hover:bg-canvas disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="min-h-[44px] rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save changes'}
              </button>
            </>
          )}
        </div>
      </div>

      {formError && (
        <div
          role="alert"
          data-testid="overview-form-error"
          className="mb-4 rounded-ctl bg-danger-soft border border-danger/40 px-4 py-3 text-sm text-danger"
        >
          {formError}
        </div>
      )}

      {/* Two-column detail grid: cards (left) + account sidebar (right). */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1fr_320px]">
        <div>
      {/* Personal */}
      <section className={cardCls} aria-label="Personal">
        <div className={sectionHeaderCls}>Personal</div>
        <div className="px-6 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>First name {editing && '*'}</label>
            {editing ? (
              <input
                type="text"
                value={form.first_name}
                onChange={(e) => updateForm('first_name', e.target.value)}
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>{staff.first_name || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Last name</label>
            {editing ? (
              <input
                type="text"
                value={form.last_name}
                onChange={(e) => updateForm('last_name', e.target.value)}
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>{staff.last_name || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Email</label>
            {editing ? (
              <input
                type="email"
                value={form.email}
                onChange={(e) => updateForm('email', e.target.value)}
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>{staff.email || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Phone</label>
            {editing ? (
              <input
                type="tel"
                value={form.phone}
                onChange={(e) => updateForm('phone', e.target.value)}
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>{staff.phone || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Emergency contact name</label>
            {editing ? (
              <input
                type="text"
                value={form.emergency_contact_name}
                onChange={(e) =>
                  updateForm('emergency_contact_name', e.target.value)
                }
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>
                {staff.emergency_contact_name || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Emergency contact phone</label>
            {editing ? (
              <input
                type="tel"
                value={form.emergency_contact_phone}
                onChange={(e) =>
                  updateForm('emergency_contact_phone', e.target.value)
                }
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>
                {staff.emergency_contact_phone || '—'}
              </div>
            )}
          </div>
          <div className="md:col-span-2">
            <label className={labelCls}>Profile photo</label>
            <StaffPhotoUploader
              value={editing ? form.on_file_photo_url : staff.on_file_photo_url}
              initials={initials}
              editing={editing}
              onChange={(value) => updateForm('on_file_photo_url', value ?? '')}
            />
          </div>
        </div>
      </section>

      {/* Manager-fallback warning chip (cross-phase X7 / Phase 3 D9).
          Surfaces when the staff's `reporting_to` chain does not
          resolve to a manager with a `user_id` — i.e. running-late
          SMS would fall back to the org_admin. */}
      <ManagerFallbackChip staff={staff} />

      {/* Inline warnings — G1 + G3 — sit above the Employment section. */}
      {staff.employee_id === null && (
        <InlineWarning
          testId="warning-missing-employee-id"
          message={
            <>
              This staff has no employee code. Kiosk clock-in (Phase 3) won't
              work until you set one. Tip: use the format <code>EMP-001</code>{' '}
              or <code>JD-2024</code>.
            </>
          }
        >
          <input
            type="text"
            value={quickEmployeeId}
            onChange={(e) => setQuickEmployeeId(e.target.value)}
            placeholder="Employee code"
            aria-label="Employee code"
            className="rounded-ctl border border-warn/40 bg-card px-3 py-2 text-sm text-text"
            data-testid="quick-employee-id-input"
          />
          <button
            type="button"
            onClick={() =>
              quickEmployeeId.trim() &&
              quickSet({ employee_id: quickEmployeeId.trim() })
            }
            disabled={quickSaving || !quickEmployeeId.trim()}
            className="px-3 py-2 min-h-[44px] rounded-ctl bg-warn text-white text-sm font-medium hover:brightness-95 disabled:opacity-50"
            data-testid="quick-employee-id-save"
          >
            {quickSaving ? 'Saving…' : 'Save'}
          </button>
        </InlineWarning>
      )}
      {staff.employment_start_date === null && (
        <InlineWarning
          testId="warning-missing-start-date"
          message="Employment start date is required for Phase 2 leave accrual. Please set it before Phase 2 ships."
        >
          <input
            type="date"
            value={quickStartDate}
            onChange={(e) => setQuickStartDate(e.target.value)}
            aria-label="Employment start date"
            className="rounded-ctl border border-warn/40 bg-card px-3 py-2 text-sm text-text"
            data-testid="quick-start-date-input"
          />
          <button
            type="button"
            onClick={() =>
              quickStartDate &&
              quickSet({ employment_start_date: quickStartDate })
            }
            disabled={quickSaving || !quickStartDate}
            className="px-3 py-2 min-h-[44px] rounded-ctl bg-warn text-white text-sm font-medium hover:brightness-95 disabled:opacity-50"
            data-testid="quick-start-date-save"
          >
            {quickSaving ? 'Saving…' : 'Save'}
          </button>
        </InlineWarning>
      )}

      {/* Employment */}
      <section className={cardCls} aria-label="Employment">
        <div className={sectionHeaderCls}>Employment</div>
        <div className="px-6 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>Employment type</label>
            {editing ? (
              <select
                value={form.employment_type}
                onChange={(e) => updateForm('employment_type', e.target.value)}
                className={inputCls}
                aria-label="Employment type"
              >
                <option value="permanent">Permanent</option>
                <option value="fixed_term">Fixed-term</option>
                <option value="casual">Casual</option>
                <option value="contractor">Contractor</option>
              </select>
            ) : (
              <div className={readonlyCls}>{staff.employment_type || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Position</label>
            {editing ? (
              <input
                type="text"
                value={form.position}
                onChange={(e) => updateForm('position', e.target.value)}
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>{staff.position || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Employee ID</label>
            {editing ? (
              <input
                type="text"
                value={form.employee_id}
                onChange={(e) => updateForm('employee_id', e.target.value)}
                className={inputCls}
                aria-label="Employee ID"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>{staff.employee_id || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Reports to (manager)</label>
            {editing ? (
              <select
                value={form.reporting_to}
                onChange={(e) => updateForm('reporting_to', e.target.value)}
                className={inputCls}
                aria-label="Reports to"
              >
                <option value="">— None —</option>
                {allStaff
                  .filter((m) => m.id !== staffId)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {`${m.first_name} ${m.last_name ?? ''}`.trim()}
                      {m.position ? ` (${m.position})` : ''}
                    </option>
                  ))}
              </select>
            ) : (
              <div className={readonlyCls}>{staff.reporting_to_name || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Role type</label>
            {editing ? (
              <select
                value={form.role_type}
                onChange={(e) => updateForm('role_type', e.target.value)}
                className={inputCls}
                aria-label="Role type"
              >
                <option value="employee">Employee</option>
                <option value="contractor">Contractor</option>
              </select>
            ) : (
              <div className={`${readonlyCls} capitalize`}>{staff.role_type || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Employment basis</label>
            {editing ? (
              <select
                value={form.employment_basis}
                onChange={(e) => updateForm('employment_basis', e.target.value)}
                className={inputCls}
                aria-label="Employment basis"
              >
                <option value="full_time">Full-time</option>
                <option value="part_time">Part-time</option>
                <option value="casual">Casual</option>
                <option value="contractor">Contractor</option>
              </select>
            ) : (
              <div className={readonlyCls}>
                {(staff.employment_basis ?? '').replace(/_/g, ' ') || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Working arrangement</label>
            {editing ? (
              <select
                value={form.working_arrangement}
                onChange={(e) => updateForm('working_arrangement', e.target.value)}
                className={inputCls}
                aria-label="Working arrangement"
              >
                <option value="rostered">Rostered</option>
                <option value="fixed">Fixed</option>
                <option value="casual_on_demand">Casual / on-demand</option>
              </select>
            ) : (
              <div className={readonlyCls}>
                {(staff.working_arrangement ?? '').replace(/_/g, ' ') || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Start date</label>
            {editing ? (
              <input
                type="date"
                value={form.employment_start_date}
                onChange={(e) =>
                  updateForm('employment_start_date', e.target.value)
                }
                className={inputCls}
                aria-label="Start date"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>
                {staff.employment_start_date || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>End date</label>
            {editing ? (
              <input
                type="date"
                value={form.employment_end_date}
                onChange={(e) =>
                  updateForm('employment_end_date', e.target.value)
                }
                className={inputCls}
                aria-label="End date"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>
                {staff.employment_end_date || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Probation end date</label>
            {editing ? (
              <input
                type="date"
                value={form.probation_end_date}
                onChange={(e) =>
                  updateForm('probation_end_date', e.target.value)
                }
                className={inputCls}
                aria-label="Probation end date"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>
                {staff.probation_end_date || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Standard hours per week</label>
            {editing ? (
              <input
                type="number"
                step="0.5"
                min="0"
                value={form.standard_hours_per_week}
                onChange={(e) =>
                  updateForm('standard_hours_per_week', e.target.value)
                }
                className={inputCls}
                aria-label="Standard hours per week"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>
                {staff.standard_hours_per_week || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Reporting to</label>
            <div className={readonlyCls}>{staff.reporting_to_name || '—'}</div>
          </div>
          <div>
            <label className={labelCls}>Residency type</label>
            {editing ? (
              <select
                value={form.residency_type}
                onChange={(e) =>
                  updateForm(
                    'residency_type',
                    e.target.value as ResidencyType,
                  )
                }
                className={inputCls}
                aria-label="Residency type"
                data-testid="residency-type-select"
              >
                {RESIDENCY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <div className={readonlyCls}>{staff.residency_type}</div>
            )}
          </div>
          {/* G2 — visa expiry only when residency is a visa type. */}
          {showVisaExpiry && (
            <div data-testid="visa-expiry-row">
              <label className={labelCls}>Visa expiry date</label>
              {editing ? (
                <input
                  type="date"
                  value={form.visa_expiry_date}
                  onChange={(e) =>
                    updateForm('visa_expiry_date', e.target.value)
                  }
                  className={inputCls}
                  aria-label="Visa expiry date"
                  data-testid="visa-expiry-input"
                />
              ) : (
                <div className={`${readonlyCls} mono`}>
                  {staff.visa_expiry_date || '—'}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* Tax & Pay */}
      <section className={cardCls} aria-label="Tax and Pay">
        <div className={sectionHeaderCls}>Tax & Pay</div>
        <div className="px-6 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>Tax code</label>
            {editing ? (
              <select
                value={form.tax_code}
                onChange={(e) => updateForm('tax_code', e.target.value)}
                className={inputCls}
                aria-label="Tax code"
              >
                {TAX_CODE_OPTIONS.map((o) => (
                  <option key={o || 'none'} value={o}>
                    {o || '—'}
                  </option>
                ))}
              </select>
            ) : (
              <div className={readonlyCls}>{staff.tax_code || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>IRD number</label>
            {editing ? (
              <input
                type="text"
                value={form.ird_number}
                onChange={(e) => updateForm('ird_number', e.target.value)}
                placeholder={staff.ird_number ?? 'XXX-XXX-XXX'}
                className={inputCls}
                aria-label="IRD number"
                data-testid="ird-input"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>{staff.ird_number || '—'}</div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <input
              id="kiwisaver-enrolled"
              type="checkbox"
              disabled={!editing}
              checked={form.kiwisaver_enrolled}
              onChange={(e) =>
                updateForm('kiwisaver_enrolled', e.target.checked)
              }
              className="h-5 w-5 rounded border-border"
            />
            <label
              htmlFor="kiwisaver-enrolled"
              className="text-sm text-muted"
            >
              KiwiSaver enrolled
            </label>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="student-loan"
              type="checkbox"
              disabled={!editing}
              checked={form.student_loan}
              onChange={(e) => updateForm('student_loan', e.target.checked)}
              className="h-5 w-5 rounded border-border"
            />
            <label
              htmlFor="student-loan"
              className="text-sm text-muted"
            >
              Student loan
            </label>
          </div>
          <div>
            <label className={labelCls}>KiwiSaver employee rate (%)</label>
            {editing ? (
              <select
                value={form.kiwisaver_employee_rate}
                onChange={(e) =>
                  updateForm('kiwisaver_employee_rate', e.target.value)
                }
                className={inputCls}
                aria-label="KiwiSaver employee rate"
                disabled={!form.kiwisaver_enrolled}
              >
                <option value="">—</option>
                {KIWISAVER_RATES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            ) : (
              <div className={`${readonlyCls} mono`}>
                {staff.kiwisaver_employee_rate || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>KiwiSaver employer rate (%)</label>
            {editing ? (
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.kiwisaver_employer_rate}
                onChange={(e) =>
                  updateForm('kiwisaver_employer_rate', e.target.value)
                }
                className={inputCls}
                aria-label="KiwiSaver employer rate"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>
                {staff.kiwisaver_employer_rate || '—'}
              </div>
            )}
          </div>
          <div>
            <label className={labelCls}>Hourly rate ($)</label>
            {editing ? (
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.hourly_rate}
                onChange={(e) => updateForm('hourly_rate', e.target.value)}
                className={inputCls}
                aria-label="Hourly rate"
                data-testid="hourly-rate-input"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>{staff.hourly_rate || '—'}</div>
            )}
          </div>
          <div>
            <label className={labelCls}>Overtime rate ($)</label>
            {editing ? (
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.overtime_rate}
                onChange={(e) => updateForm('overtime_rate', e.target.value)}
                className={inputCls}
                aria-label="Overtime rate"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>{staff.overtime_rate || '—'}</div>
            )}
          </div>
          <div className="md:col-span-2">
            <label className={labelCls}>Bank account number</label>
            {editing ? (
              <input
                type="text"
                value={form.bank_account_number}
                onChange={(e) =>
                  updateForm('bank_account_number', e.target.value)
                }
                placeholder={staff.bank_account_number ?? '00-0000-0000000-00'}
                className={inputCls}
                aria-label="Bank account number"
                data-testid="bank-input"
              />
            ) : (
              <div className={`${readonlyCls} mono`}>
                {staff.bank_account_number || '—'}
              </div>
            )}
          </div>

          {/* Pay cycle (per-staff-pay-cycle). In edit mode: a selector when the
              org has at least one active cycle, otherwise a hint to configure
              one under Timesheets → Settings (REQ 1.3, 1.4, 1.5, 1.6). In view
              mode: the staff member's resolved cycle, flagged when it comes from
              the org default. */}
          <div className="md:col-span-2" data-testid="pay-cycle-field">
            <label className={labelCls}>Pay cycle</label>
            {editing ? (
              payCycles.length > 0 ? (
                <>
                  <select
                    value={form.pay_cycle_id}
                    onChange={(e) => updateForm('pay_cycle_id', e.target.value)}
                    className={inputCls}
                    aria-label="Pay cycle"
                    data-testid="pay-cycle-select"
                  >
                    {/* "Use organisation default" — sends null so any existing
                        staff-level assignment is cleared and the org
                        Default_Cycle applies (REQ 1.4, 3.3). */}
                    <option value="">
                      Use organisation default
                      {(() => {
                        const def = payCycles.find((c) => c.is_default)
                        return def ? ` (${def.name})` : ''
                      })()}
                    </option>
                    {payCycles.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <p className="mt-[7px] text-[12px] text-muted-2">
                    Choose a pay cycle for this staff member, or leave as “Use
                    organisation default” to pay them on your organisation’s
                    default cycle.
                  </p>
                </>
              ) : (
                <div
                  className="rounded-ctl border border-dashed border-border bg-canvas p-4"
                  data-testid="pay-cycle-empty-hint"
                >
                  <p className="text-[12px] text-muted-2">
                    No pay cycle configured — set one up under Timesheets →
                    Settings to assign a pay cycle to this staff member.
                  </p>
                </div>
              )
            ) : (
              <div className={readonlyCls}>
                {staff.pay_cycle_name
                  ? `${staff.pay_cycle_name}${
                      staff.pay_cycle_is_default ? ' (organisation default)' : ''
                    }`
                  : '—'}
              </div>
            )}
          </div>
        </div>
        <div className="px-6 pb-6">
          <PayRateHistoryPanel staffId={staffId} />
        </div>
      </section>

      {/* Recurring allowances (Phase 4 D10 / G4 / P4-N31) — appended
          below the Tax & Pay panel. Phase 1 did not pre-allocate a
          slot for this; the new section sits as its own card so the
          existing Overview layout remains stable. */}
      <section className={cardCls} aria-label="Recurring allowances">
        <div className={sectionHeaderCls}>Recurring allowances</div>
        <div className="px-6 py-4">
          <RecurringAllowancesPanel staffId={staffId} />
        </div>
      </section>

      {/* Schedule */}
      <section className={cardCls} aria-label="Schedule">
        <div className={sectionHeaderCls}>Schedule</div>
        <div className="px-6 py-4">
          {(() => {
            const isFixed = form.working_arrangement === 'fixed'
            const scheduleEditable = editing && isFixed
            const dayCount = Object.keys(form.availability_schedule ?? {}).length
            return (
              <>
                {editing && !isFixed && (
                  <p
                    className="mb-3 text-[12.5px] text-muted"
                    data-testid="schedule-disabled-note"
                  >
                    A set work-days schedule applies only to a{' '}
                    <span className="font-medium text-text">Fixed</span> working
                    arrangement. For Rostered or Casual / on-demand staff, hours
                    come from the roster, so this is disabled. Change Working
                    arrangement to “Fixed” to configure work days.
                  </p>
                )}
                {editing && isFixed && (
                  <p
                    className={`mb-3 text-[12.5px] ${
                      dayCount === 0 ? 'text-danger' : 'text-muted'
                    }`}
                    data-testid="schedule-required-note"
                  >
                    Required for a Fixed working arrangement — enable at least one
                    work day and set its hours.
                  </p>
                )}
                <WorkSchedule
                  schedule={form.availability_schedule}
                  onChange={(next) => updateForm('availability_schedule', next)}
                  readOnly={!scheduleEditable}
                />
              </>
            )
          })()}
        </div>
      </section>

      {/* Clock-in & roster delivery */}
      <section className={cardCls} aria-label="Clock-in and roster delivery">
        <div className={sectionHeaderCls}>Clock-in & roster delivery</div>
        <div className="px-6 py-4 space-y-3">
          <label className="flex items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              disabled={!editing}
              checked={form.self_service_clock_enabled}
              onChange={(e) =>
                updateForm('self_service_clock_enabled', e.target.checked)
              }
              className="h-5 w-5 rounded border-border"
            />
            Self-service kiosk clock-in
          </label>
          <label className="flex items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              disabled={!editing}
              checked={form.weekly_roster_email_enabled}
              onChange={(e) =>
                updateForm('weekly_roster_email_enabled', e.target.checked)
              }
              className="h-5 w-5 rounded border-border"
            />
            Email weekly roster
          </label>
          <label className="flex items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              disabled={!editing}
              checked={form.weekly_roster_sms_enabled}
              onChange={(e) =>
                updateForm('weekly_roster_sms_enabled', e.target.checked)
              }
              className="h-5 w-5 rounded border-border"
            />
            SMS weekly roster
          </label>
        </div>
      </section>

      {/* Skills */}
      <section className={cardCls} aria-label="Skills">
        <div className={sectionHeaderCls}>Skills</div>
        <div className="p-5">
          {editing ? (
            <>
              <label className={labelCls}>Skills (comma-separated)</label>
              <input
                type="text"
                value={form.skills}
                onChange={(e) => updateForm('skills', e.target.value)}
                placeholder="e.g. Brakes, Engine, Electrical"
                className={inputCls}
                aria-label="Skills"
              />
            </>
          ) : (staff.skills ?? []).length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {(staff.skills ?? []).map((skill) => (
                <span
                  key={skill}
                  className="inline-flex items-center rounded-chip bg-accent-soft px-[11px] py-1 text-[12px] font-medium text-accent"
                >
                  {skill}
                </span>
              ))}
            </div>
          ) : (
            <div className={readonlyCls}>—</div>
          )}
        </div>
      </section>
        </div>{/* end left column */}

        {/* Right column — Account sidebar (StaffDetail.html .stack). */}
        <div>
          {/* This-month metrics (R8.x) — sits above the Account panel. */}
          <ThisMonthPanel
            staffId={staffId}
            stats={monthStats}
            failed={monthStatsFailed}
          />
          <section className={cardCls} aria-label="Account">
            <div className="p-5">
              <div className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-muted-2">
                Account
              </div>
              <div className="flex items-center justify-between border-b border-border py-[11px]">
                <span className="text-[13px] text-muted">Login access</span>
                <Badge variant={staff.user_id ? 'active' : 'neutral'}>
                  {staff.user_id ? 'Active' : 'None'}
                </Badge>
              </div>

              {staff.user_id ? (
                <>
                  {/* User role (R9.1, R9.2) — from the stats response. */}
                  <div className="flex items-center justify-between border-b border-border py-[11px]">
                    <span className="text-[13px] text-muted">User role</span>
                    <span className="mono text-[13px] font-medium text-text">
                      {monthStatsFailed ? '—' : monthStats?.user_role ?? '—'}
                    </span>
                  </div>
                  {/* Last sign-in (R9.1, R9.3, R9.4) — from the stats response. */}
                  <div className="flex items-center justify-between py-[11px]">
                    <span className="text-[13px] text-muted">Last sign-in</span>
                    <span className="mono text-[13px] font-medium text-text">
                      {monthStatsFailed
                        ? '—'
                        : formatLastSignIn(monthStats?.last_sign_in)}
                    </span>
                  </div>
                  <p className="mt-3 text-[12px] leading-relaxed text-muted">
                    This staff member has a linked login. Manage their role and
                    access from{' '}
                    <Link to="/settings" className="text-accent hover:underline">
                      Settings → Users
                    </Link>
                    .
                  </p>
                </>
              ) : (
                /* No linked account (R9.5) — "No account?" prompt + action. */
                <div className="mt-3">
                  <p className="text-[13px] font-medium text-text">
                    No account?
                  </p>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    Staff without a login can&apos;t be scheduled or sign in.
                    Create an account so they can sign in with their email.
                  </p>
                  <button
                    type="button"
                    onClick={() => setCreateAccountOpen(true)}
                    className="mt-3 inline-flex h-9 items-center justify-center rounded-ctl bg-accent px-3 text-[13px] font-semibold text-white hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card"
                  >
                    Create user account
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* Onboarding link lifecycle card (R10, R13) — sits below the
              Account panel in the sidebar. Self-contained: fetches its own
              status on mount and manages resend/revoke/send actions. */}
          <OnboardingLinkCard staffId={staffId} />
        </div>
      </div>{/* end detail grid */}

      {minWageModal && (
        <MinimumWageWarningModal
          threshold={minWageModal.threshold}
          proposed={minWageModal.proposed}
          onCancel={() => setMinWageModal(null)}
          onConfirm={handleConfirmMinWage}
        />
      )}

      {createAccountOpen && (
        <CreateAccountModal
          staffId={staffId}
          email={staff.email}
          onCancel={() => setCreateAccountOpen(false)}
          onCreated={() => {
            setCreateAccountOpen(false)
            // Reload so user_id updates and the panel flips to linked state.
            void loadStaff()
          }}
        />
      )}
    </div>
  )
}
