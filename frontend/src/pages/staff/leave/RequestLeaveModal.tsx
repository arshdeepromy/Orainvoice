/**
 * RequestLeaveModal — submit a leave request for a single staff member.
 *
 * Auto-computes hours_requested as `weekdays_in_range × std_daily_hours`
 * but lets the user override (e.g., for partial-day or non-standard
 * shifts). On submit calls `submitLeaveRequest(...)` and surfaces the
 * documented 422 service errors inline.
 *
 * Branches:
 * - **Bereavement** (`leave_type.code === 'bereavement'`): renders a
 *   required relationship_to_subject select (close_family / other) and
 *   a per-event-cap banner (3 working days for close family, 1 for
 *   other). Submit disabled until relationship is set.
 * - **Partial-day** (single date AND hours_requested < std_daily_hours):
 *   renders a partial_day_start_time picker, defaulted to the staff's
 *   shift_start (or weekday availability_schedule entry).
 * - **Confidential** (`leave_type.confidential_visibility === true`):
 *   renders a one-line privacy banner.
 * - **Doctor's note** (`leave_type.requires_doctor_note === true`):
 *   renders a file input. NOTE: actual upload to the attachments API
 *   is out of scope for D2 — this version captures the file in state
 *   only and surfaces the upload control. Wiring to the attachments
 *   endpoint is tracked separately.
 *
 * Documented service errors (per design §9):
 * - 422 `relationship_required`         → field error on the relationship select
 * - 422 `bereavement_cap_exceeded`      → banner with cap_hours
 * - 422 `insufficient_balance`          → banner with available
 * - 422 `insufficient_toil_balance`     → banner with available
 *
 * **Validates: Staff Management Phase 2 task D2**
 */

import { useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import {
  submitLeaveRequest,
  type LeaveRequest,
  type LeaveType,
  type RelationshipToSubject,
} from '../../../api/leave'
import {
  countWeekdaysInRange,
  defaultPartialDayStart,
  stdDailyHours,
  type Staff,
} from './types'

interface Props {
  staffId: string
  staff: Staff
  leaveTypes: LeaveType[]
  onClose: () => void
  onSubmitted: (request: LeaveRequest) => void
}

interface FormState {
  leaveTypeId: string
  startDate: string
  endDate: string
  /** Stored as string so users can type freely; coerced on submit. */
  hoursRequested: string
  /** True while the user has not manually edited the hours field. */
  hoursIsAuto: boolean
  reason: string
  relationship: RelationshipToSubject | ''
  partialDayStartTime: string
  /** Captured but not yet uploaded (see header comment). */
  doctorNoteFile: File | null
}

interface ApiFieldError {
  banner?: string | null
  /** Field-level error keyed by form field name. */
  fieldErrors?: Partial<Record<keyof FormState, string>>
}

const EMPTY_FORM: FormState = {
  leaveTypeId: '',
  startDate: '',
  endDate: '',
  hoursRequested: '',
  hoursIsAuto: true,
  reason: '',
  relationship: '',
  partialDayStartTime: '',
  doctorNoteFile: null,
}

function pickDefaultLeaveType(types: LeaveType[]): string {
  const active = (types ?? []).filter((lt) => lt.active)
  // Prefer annual leave if present; otherwise the first active type.
  const annual = active.find((lt) => lt.code === 'annual')
  return (annual ?? active[0])?.id ?? ''
}

function readApiError(err: unknown, stdDay: number): ApiFieldError {
  if (!axios.isAxiosError(err)) {
    if (err instanceof Error) return { banner: err.message }
    return { banner: 'Failed to submit leave request' }
  }
  const status = err.response?.status
  const detail = err.response?.data?.detail

  // FastAPI returns either a string, a {reason, ...} object, or a list of
  // pydantic validation issues. We care most about the {reason, ...} form.
  let reason: string | null = null
  let extras: Record<string, unknown> = {}
  if (typeof detail === 'string') {
    reason = detail
  } else if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    if (typeof (detail as { reason?: unknown }).reason === 'string') {
      reason = (detail as { reason: string }).reason
      extras = detail as Record<string, unknown>
    } else if (typeof (detail as { detail?: unknown }).detail === 'string') {
      reason = (detail as { detail: string }).detail
    }
  }

  if (status === 422 && reason === 'relationship_required') {
    return {
      fieldErrors: {
        relationship: 'Relationship to the deceased is required for bereavement leave.',
      },
    }
  }
  if (status === 422 && reason === 'bereavement_cap_exceeded') {
    const capHours = parseFloat(String(extras.cap_hours ?? '')) || 0
    const capDays = stdDay > 0 ? Math.round(capHours / stdDay) : 0
    return {
      banner: `Bereavement leave is capped at ${capHours}h${
        capDays ? ` (${capDays} working day${capDays === 1 ? '' : 's'})` : ''
      } for the selected relationship.`,
    }
  }
  if (status === 422 && reason === 'insufficient_balance') {
    const available = parseFloat(String(extras.available ?? '')) || 0
    return {
      banner: `Insufficient balance — only ${available}h available.`,
    }
  }
  if (status === 422 && reason === 'insufficient_toil_balance') {
    const available = parseFloat(String(extras.available ?? '')) || 0
    return {
      banner: `TOIL accrual starts in Phase 3 — only ${available}h available right now.`,
    }
  }
  // Fallback: surface whatever the server said.
  if (typeof reason === 'string' && reason) return { banner: reason }
  if (err.message) return { banner: err.message }
  return { banner: 'Failed to submit leave request' }
}

export default function RequestLeaveModal({
  staffId,
  staff,
  leaveTypes,
  onClose,
  onSubmitted,
}: Props) {
  const [form, setForm] = useState<FormState>(() => ({
    ...EMPTY_FORM,
    leaveTypeId: pickDefaultLeaveType(leaveTypes ?? []),
  }))
  const [submitting, setSubmitting] = useState(false)
  const [apiError, setApiError] = useState<ApiFieldError>({})

  const stdDay = useMemo(() => stdDailyHours(staff), [staff])

  const selectedType = useMemo<LeaveType | undefined>(
    () => (leaveTypes ?? []).find((lt) => lt.id === form.leaveTypeId),
    [leaveTypes, form.leaveTypeId],
  )

  const isBereavement = (selectedType?.code ?? '') === 'bereavement'
  const requiresNote = !!selectedType?.requires_doctor_note
  const isConfidential = !!selectedType?.confidential_visibility

  // Auto-compute hours when the user hasn't overridden them.
  useEffect(() => {
    if (!form.hoursIsAuto) return
    const days = countWeekdaysInRange(form.startDate, form.endDate)
    if (days === 0) {
      // Reset only when both dates are present but invalid.
      if (form.startDate && form.endDate) {
        setForm((f) => (f.hoursRequested === '' ? f : { ...f, hoursRequested: '' }))
      }
      return
    }
    const auto = (days * stdDay).toFixed(2)
    setForm((f) => (f.hoursRequested === auto ? f : { ...f, hoursRequested: auto }))
  }, [form.startDate, form.endDate, stdDay, form.hoursIsAuto])

  const isSingleDay = !!form.startDate && form.startDate === form.endDate
  const hoursNum = parseFloat(form.hoursRequested) || 0
  const isPartialDay = isSingleDay && hoursNum > 0 && hoursNum < stdDay

  // Seed partial_day_start_time once we cross into the partial-day branch.
  useEffect(() => {
    if (isPartialDay && !form.partialDayStartTime) {
      const seeded = defaultPartialDayStart(staff, form.startDate)
      setForm((f) => ({ ...f, partialDayStartTime: seeded }))
    }
    if (!isPartialDay && form.partialDayStartTime) {
      // Drop the value when we leave the partial-day branch so we don't
      // accidentally send it to the backend.
      setForm((f) => ({ ...f, partialDayStartTime: '' }))
    }
  }, [isPartialDay, staff, form.startDate, form.partialDayStartTime])

  // Bereavement cap preview.
  const bereavementCap = useMemo(() => {
    if (!isBereavement || !form.relationship) return null
    const days = form.relationship === 'close_family' ? 3 : 1
    return { days, hours: days * stdDay }
  }, [isBereavement, form.relationship, stdDay])

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const submitDisabled =
    submitting ||
    !form.leaveTypeId ||
    !form.startDate ||
    !form.endDate ||
    !form.hoursRequested ||
    Number.isNaN(parseFloat(form.hoursRequested)) ||
    (isBereavement && !form.relationship)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitDisabled) return
    setSubmitting(true)
    setApiError({})
    try {
      const controller = new AbortController()
      const created = await submitLeaveRequest(
        staffId,
        {
          leave_type_id: form.leaveTypeId,
          start_date: form.startDate,
          end_date: form.endDate,
          hours_requested: parseFloat(form.hoursRequested).toFixed(2),
          reason: form.reason.trim() || null,
          relationship_to_subject: isBereavement
            ? (form.relationship as RelationshipToSubject)
            : null,
          partial_day_start_time: isPartialDay
            ? form.partialDayStartTime || null
            : null,
        },
        controller.signal,
      )
      onSubmitted(created)
      onClose()
    } catch (err) {
      setApiError(readApiError(err, stdDay))
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls =
    'w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500'
  const labelCls =
    'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1'

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="request-leave-title"
      data-testid="request-leave-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 dark:bg-black/70 p-4"
    >
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-hidden flex flex-col">
        <header className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2
            id="request-leave-title"
            className="text-lg font-semibold text-gray-900 dark:text-gray-100"
          >
            Request leave
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            aria-label="Close dialog"
            className="rounded p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </header>

        <form
          onSubmit={handleSubmit}
          className="flex-1 overflow-y-auto px-6 py-4 space-y-4"
        >
          {apiError.banner && (
            <div
              role="alert"
              data-testid="request-leave-banner"
              className="rounded-md bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300"
            >
              {apiError.banner}
            </div>
          )}

          <div>
            <label htmlFor="request-leave-type" className={labelCls}>
              Leave type
            </label>
            <select
              id="request-leave-type"
              value={form.leaveTypeId}
              onChange={(e) => {
                update('leaveTypeId', e.target.value)
                // Clear branch-specific state when switching types.
                update('relationship', '')
                setApiError({})
              }}
              disabled={submitting}
              className={inputCls}
            >
              {(leaveTypes ?? [])
                .filter((lt) => lt.active)
                .map((lt) => (
                  <option key={lt.id} value={lt.id}>
                    {lt.name}
                  </option>
                ))}
            </select>
          </div>

          {isConfidential && (
            <div
              role="note"
              data-testid="request-leave-confidential-banner"
              className="rounded-md bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 px-3 py-2 text-xs text-purple-900 dark:text-purple-100"
            >
              This leave type is confidential — only you and your designated
              approver will see this request.
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="request-start-date" className={labelCls}>
                Start date
              </label>
              <input
                id="request-start-date"
                type="date"
                value={form.startDate}
                onChange={(e) => {
                  update('startDate', e.target.value)
                  // If end_date is now before start_date, snap them.
                  if (form.endDate && form.endDate < e.target.value) {
                    update('endDate', e.target.value)
                  }
                }}
                disabled={submitting}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="request-end-date" className={labelCls}>
                End date
              </label>
              <input
                id="request-end-date"
                type="date"
                value={form.endDate}
                min={form.startDate || undefined}
                onChange={(e) => update('endDate', e.target.value)}
                disabled={submitting}
                className={inputCls}
              />
            </div>
          </div>

          <div>
            <label htmlFor="request-hours" className={labelCls}>
              Hours requested
              <span className="ml-1 text-xs text-gray-500 dark:text-gray-400 font-normal">
                {form.hoursIsAuto ? '(auto-calculated)' : '(custom)'}
              </span>
            </label>
            <input
              id="request-hours"
              type="number"
              step="0.25"
              min="0"
              value={form.hoursRequested}
              onChange={(e) => {
                update('hoursRequested', e.target.value)
                update('hoursIsAuto', false)
              }}
              disabled={submitting}
              className={inputCls}
            />
            {!form.hoursIsAuto && (
              <button
                type="button"
                onClick={() => update('hoursIsAuto', true)}
                disabled={submitting}
                className="mt-1 text-xs text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
              >
                Reset to auto-calculated
              </button>
            )}
          </div>

          {isBereavement && (
            <div className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 space-y-2">
              <div>
                <label htmlFor="request-relationship" className={labelCls}>
                  Relationship to the deceased
                  <span className="ml-1 text-red-600">*</span>
                </label>
                <select
                  id="request-relationship"
                  data-testid="request-relationship"
                  value={form.relationship}
                  onChange={(e) =>
                    update(
                      'relationship',
                      e.target.value as RelationshipToSubject | '',
                    )
                  }
                  disabled={submitting}
                  className={inputCls}
                >
                  <option value="">Select…</option>
                  <option value="close_family">
                    Close family (spouse, child, parent, sibling, grandparent,
                    grandchild, in-law)
                  </option>
                  <option value="other">Other person</option>
                </select>
                {apiError.fieldErrors?.relationship && (
                  <p
                    role="alert"
                    className="mt-1 text-xs text-red-700 dark:text-red-300"
                  >
                    {apiError.fieldErrors.relationship}
                  </p>
                )}
              </div>
              <p className="text-xs text-amber-900 dark:text-amber-100">
                Per-event cap: 3 working days for close family, 1 working day
                for other.
                {bereavementCap && (
                  <>
                    {' '}
                    Maximum for selection:{' '}
                    <strong>
                      {bereavementCap.hours}h ({bereavementCap.days} working
                      day{bereavementCap.days === 1 ? '' : 's'})
                    </strong>
                    .
                  </>
                )}
              </p>
            </div>
          )}

          {isPartialDay && (
            <div>
              <label htmlFor="request-partial-start" className={labelCls}>
                Partial-day start time
                <span className="ml-1 text-xs text-gray-500 dark:text-gray-400 font-normal">
                  (single date, less than {stdDay}h)
                </span>
              </label>
              <input
                id="request-partial-start"
                data-testid="request-partial-start"
                type="time"
                value={form.partialDayStartTime}
                onChange={(e) => update('partialDayStartTime', e.target.value)}
                disabled={submitting}
                className={inputCls}
              />
            </div>
          )}

          <div>
            <label htmlFor="request-reason" className={labelCls}>
              Reason
              <span className="ml-1 text-xs text-gray-500 dark:text-gray-400 font-normal">
                (optional)
              </span>
            </label>
            <textarea
              id="request-reason"
              value={form.reason}
              onChange={(e) => update('reason', e.target.value)}
              disabled={submitting}
              rows={3}
              maxLength={500}
              className={inputCls}
            />
          </div>

          {requiresNote && (
            <div>
              <label htmlFor="request-doctor-note" className={labelCls}>
                Doctor's note
                <span className="ml-1 text-xs text-gray-500 dark:text-gray-400 font-normal">
                  (required for this leave type)
                </span>
              </label>
              <input
                id="request-doctor-note"
                data-testid="request-doctor-note"
                type="file"
                accept="image/*,application/pdf"
                onChange={(e) =>
                  update('doctorNoteFile', e.target.files?.[0] ?? null)
                }
                disabled={submitting}
                className="block w-full text-sm text-gray-700 dark:text-gray-300 file:mr-3 file:rounded file:border-0 file:bg-blue-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-blue-700 hover:file:bg-blue-100 dark:file:bg-blue-900/40 dark:file:text-blue-200"
              />
              {form.doctorNoteFile && (
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  Selected: {form.doctorNoteFile.name}
                </p>
              )}
            </div>
          )}
        </form>

        <footer className="flex items-center justify-end gap-2 border-t border-gray-200 dark:border-gray-700 px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-4 py-2 min-h-[44px] rounded border border-gray-300 dark:border-gray-600 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitDisabled}
            className="px-4 py-2 min-h-[44px] rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? 'Submitting…' : 'Submit request'}
          </button>
        </footer>
      </div>
    </div>
  )
}
