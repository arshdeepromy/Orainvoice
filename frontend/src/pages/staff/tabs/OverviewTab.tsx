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
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import apiClient from '@/api/client'
import WorkSchedule, { type WeekSchedule } from '@/components/WorkSchedule'
import MinimumWageWarningModal from '../components/MinimumWageWarningModal'
import PayRateHistoryPanel from '../components/PayRateHistoryPanel'
import RecurringAllowancesPanel from '../components/RecurringAllowancesPanel'

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
}

const MASKED_IRD_RE = /^\*+\d{0,3}$/
const MASKED_BANK_RE = /^\*+\d{0,4}$/

function isMaskedIrd(v: string | null | undefined): boolean {
  if (!v) return false
  return MASKED_IRD_RE.test(v.trim())
}
function isMaskedBank(v: string | null | undefined): boolean {
  if (!v) return false
  return MASKED_BANK_RE.test(v.trim())
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
    availability_schedule: form.availability_schedule ?? {},
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
      className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded p-3 mb-3"
    >
      <p className="text-sm text-amber-800 dark:text-amber-200">{message}</p>
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
      className="mb-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-100"
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
      setSaving(true)
      setFormError(null)
      try {
        const payload = formToPayload(form, staff, overrideMinWage)
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
    return <div className="p-6 text-gray-500">Loading…</div>
  }
  if (loadError || !staff) {
    return (
      <div role="alert" className="p-6 text-red-600 dark:text-red-400">
        {loadError ?? 'Staff record not found.'}
      </div>
    )
  }

  const inputCls =
    'w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500'
  const readonlyCls =
    'w-full rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-3 py-2 text-sm text-gray-700 dark:text-gray-300'
  const labelCls =
    'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1'
  const cardCls =
    'bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm mb-4'
  const sectionHeaderCls =
    'px-6 py-3 border-b border-gray-100 dark:border-gray-800 text-sm font-semibold text-gray-900 dark:text-gray-100 uppercase tracking-wider'

  return (
    <div className="p-6 max-w-4xl" data-testid="overview-tab">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {staff.name}
          </h1>
          {staff.position && (
            <p className="text-sm text-gray-600 dark:text-gray-400">
              {staff.position}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          {!editing && (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="px-4 py-2 min-h-[44px] rounded border border-gray-300 dark:border-gray-600 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Edit
            </button>
          )}
          {editing && (
            <>
              <button
                type="button"
                onClick={handleCancel}
                disabled={saving}
                className="px-4 py-2 min-h-[44px] rounded border border-gray-300 dark:border-gray-600 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 min-h-[44px] rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          )}
        </div>
      </div>

      {formError && (
        <div
          role="alert"
          data-testid="overview-form-error"
          className="mb-4 rounded-md bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300"
        >
          {formError}
        </div>
      )}

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
            <label className={labelCls}>Photo URL</label>
            {editing ? (
              <input
                type="url"
                value={form.on_file_photo_url}
                onChange={(e) =>
                  updateForm('on_file_photo_url', e.target.value)
                }
                placeholder="https://…"
                className={inputCls}
              />
            ) : (
              <div className={readonlyCls}>
                {staff.on_file_photo_url || '—'}
              </div>
            )}
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
            className="rounded-md border border-amber-300 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100"
            data-testid="quick-employee-id-input"
          />
          <button
            type="button"
            onClick={() =>
              quickEmployeeId.trim() &&
              quickSet({ employee_id: quickEmployeeId.trim() })
            }
            disabled={quickSaving || !quickEmployeeId.trim()}
            className="px-3 py-2 min-h-[44px] rounded bg-amber-600 text-white text-sm font-medium hover:bg-amber-700 disabled:opacity-50"
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
            className="rounded-md border border-amber-300 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100"
            data-testid="quick-start-date-input"
          />
          <button
            type="button"
            onClick={() =>
              quickStartDate &&
              quickSet({ employment_start_date: quickStartDate })
            }
            disabled={quickSaving || !quickStartDate}
            className="px-3 py-2 min-h-[44px] rounded bg-amber-600 text-white text-sm font-medium hover:bg-amber-700 disabled:opacity-50"
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
              <div className={readonlyCls}>
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
              <div className={readonlyCls}>
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
              <div className={readonlyCls}>
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
              <div className={readonlyCls}>
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
                <div className={readonlyCls}>
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
              <div className={readonlyCls}>{staff.ird_number || '—'}</div>
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
              className="h-5 w-5 rounded border-gray-300"
            />
            <label
              htmlFor="kiwisaver-enrolled"
              className="text-sm text-gray-700 dark:text-gray-300"
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
              className="h-5 w-5 rounded border-gray-300"
            />
            <label
              htmlFor="student-loan"
              className="text-sm text-gray-700 dark:text-gray-300"
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
              <div className={readonlyCls}>
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
              <div className={readonlyCls}>
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
              <div className={readonlyCls}>{staff.hourly_rate || '—'}</div>
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
              <div className={readonlyCls}>{staff.overtime_rate || '—'}</div>
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
              <div className={readonlyCls}>
                {staff.bank_account_number || '—'}
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
          <WorkSchedule
            schedule={form.availability_schedule}
            onChange={(next) => updateForm('availability_schedule', next)}
            readOnly={!editing}
          />
        </div>
      </section>

      {/* Clock-in & roster delivery */}
      <section className={cardCls} aria-label="Clock-in and roster delivery">
        <div className={sectionHeaderCls}>Clock-in & roster delivery</div>
        <div className="px-6 py-4 space-y-3">
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              disabled={!editing}
              checked={form.self_service_clock_enabled}
              onChange={(e) =>
                updateForm('self_service_clock_enabled', e.target.checked)
              }
              className="h-5 w-5 rounded border-gray-300"
            />
            Self-service kiosk clock-in
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              disabled={!editing}
              checked={form.weekly_roster_email_enabled}
              onChange={(e) =>
                updateForm('weekly_roster_email_enabled', e.target.checked)
              }
              className="h-5 w-5 rounded border-gray-300"
            />
            Email weekly roster
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              disabled={!editing}
              checked={form.weekly_roster_sms_enabled}
              onChange={(e) =>
                updateForm('weekly_roster_sms_enabled', e.target.checked)
              }
              className="h-5 w-5 rounded border-gray-300"
            />
            SMS weekly roster
          </label>
        </div>
      </section>

      {/* Skills */}
      <section className={cardCls} aria-label="Skills">
        <div className={sectionHeaderCls}>Skills</div>
        <div className="px-6 py-4">
          <label className={labelCls}>Skills (comma-separated)</label>
          {editing ? (
            <input
              type="text"
              value={form.skills}
              onChange={(e) => updateForm('skills', e.target.value)}
              placeholder="e.g. Brakes, Engine, Electrical"
              className={inputCls}
              aria-label="Skills"
            />
          ) : (
            <div className={readonlyCls}>
              {(staff.skills ?? []).length > 0
                ? (staff.skills ?? []).join(', ')
                : '—'}
            </div>
          )}
        </div>
      </section>

      {minWageModal && (
        <MinimumWageWarningModal
          threshold={minWageModal.threshold}
          proposed={minWageModal.proposed}
          onCancel={() => setMinWageModal(null)}
          onConfirm={handleConfirmMinWage}
        />
      )}
    </div>
  )
}
