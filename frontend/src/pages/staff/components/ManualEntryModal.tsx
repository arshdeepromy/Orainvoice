/**
 * ManualEntryModal — admin-only modal for inserting or editing a clock
 * entry by hand from the Hours tab.
 *
 *   POST   /api/v2/staff/{staff_id}/clock/manual          — create
 *   PATCH  /api/v2/staff/{staff_id}/clock/manual/{entry_id} — update
 *
 * Server sets `source='admin_manual'` and `created_by=user_id`. Manual
 * entries don't require a photo.
 *
 * Refs: Phase 3 R5 + R8.4 + R16. Touch targets ≥ 44×44.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'

export interface ManualEntryInitialValues {
  entryId?: string | null
  clockInAt?: string | null
  clockOutAt?: string | null
  breakMinutes?: number | null
  notes?: string | null
}

export interface ManualEntryModalProps {
  open: boolean
  onClose: () => void
  staffId: string
  /** When supplied, the modal renders in edit mode (PATCH). */
  initialValues?: ManualEntryInitialValues | null
  onSaved?: () => void
}

interface ManualEntryPayload {
  clock_in_at: string
  clock_out_at: string | null
  break_minutes: number
  notes: string | null
}

/** Convert an ISO datetime to the local <input type="datetime-local"> shape. */
function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return ''
  }
}

/** Convert a local datetime-input value back to an ISO timestamp. */
function localInputToIso(local: string): string | null {
  if (!local) return null
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return null
  return d.toISOString()
}

function readErrorDetail(err: unknown): string | null {
  if (axios.isCancel?.(err)) return null
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  return null
}

export default function ManualEntryModal({
  open,
  onClose,
  staffId,
  initialValues,
  onSaved,
}: ManualEntryModalProps) {
  const isEdit = !!initialValues?.entryId
  const [clockInLocal, setClockInLocal] = useState<string>('')
  const [clockOutLocal, setClockOutLocal] = useState<string>('')
  const [breakMinutes, setBreakMinutes] = useState<string>('0')
  const [notes, setNotes] = useState<string>('')
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setClockInLocal(isoToLocalInput(initialValues?.clockInAt ?? null))
    setClockOutLocal(isoToLocalInput(initialValues?.clockOutAt ?? null))
    setBreakMinutes(String(initialValues?.breakMinutes ?? 0))
    setNotes(initialValues?.notes ?? '')
    setError(null)
    setSubmitting(false)
  }, [open, initialValues])

  const parsedBreak = useMemo(() => {
    const n = Number.parseInt(breakMinutes, 10)
    if (!Number.isFinite(n) || n < 0) return 0
    return n
  }, [breakMinutes])

  const canSubmit = useMemo(() => {
    if (submitting) return false
    if (!clockInLocal) return false
    if (clockOutLocal) {
      const inMs = Date.parse(clockInLocal)
      const outMs = Date.parse(clockOutLocal)
      if (Number.isFinite(inMs) && Number.isFinite(outMs) && outMs <= inMs) {
        return false
      }
    }
    return true
  }, [submitting, clockInLocal, clockOutLocal])

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    const inIso = localInputToIso(clockInLocal)
    if (!inIso) {
      setError('Clock-in time is required and must be a valid date.')
      return
    }
    const outIso = clockOutLocal ? localInputToIso(clockOutLocal) : null
    setError(null)
    setSubmitting(true)
    const controller = new AbortController()
    const trimmedNotes = notes.trim()
    const payload: ManualEntryPayload = {
      clock_in_at: inIso,
      clock_out_at: outIso,
      break_minutes: parsedBreak,
      notes: trimmedNotes ? trimmedNotes : null,
    }
    try {
      if (isEdit && initialValues?.entryId) {
        await apiClient.patch(
          `/api/v2/staff/${staffId}/clock/manual/${initialValues.entryId}`,
          payload,
          { signal: controller.signal },
        )
      } else {
        await apiClient.post(
          `/api/v2/staff/${staffId}/clock/manual`,
          payload,
          { signal: controller.signal },
        )
      }
      if (controller.signal.aborted) return
      onSaved?.()
      onClose()
    } catch (err) {
      if (controller.signal.aborted) return
      const detail = readErrorDetail(err)
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        setError('You do not have permission to edit clock entries.')
      } else if (status === 409) {
        setError(
          detail === 'week_locked'
            ? 'This week has been approved. Re-open the week to edit.'
            : 'This entry conflicts with another open clock entry.',
        )
      } else if (detail === 'invalid_range') {
        setError('Clock-out must be after clock-in.')
      } else if (detail) {
        setError(detail)
      } else {
        setError("Couldn't save the entry. Please try again.")
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [
    canSubmit,
    clockInLocal,
    clockOutLocal,
    parsedBreak,
    notes,
    isEdit,
    initialValues,
    staffId,
    onSaved,
    onClose,
  ])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="manual-entry-title"
      data-testid="manual-entry-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-lg bg-white shadow-xl dark:bg-gray-900">
        <header className="flex items-center justify-between border-b border-gray-200 px-6 py-4 dark:border-gray-700">
          <h2
            id="manual-entry-title"
            className="text-lg font-semibold text-gray-900 dark:text-gray-100"
          >
            {isEdit ? 'Edit clock entry' : 'Add clock entry'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="min-h-[44px] min-w-[44px] rounded p-2 text-gray-400 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:hover:text-gray-200"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </header>

        <div className="space-y-4 px-6 py-4">
          <p className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300">
            Manual entries are recorded with <code>source=admin_manual</code>{' '}
            and audited under your user. Photos are not required.
          </p>

          <div>
            <label
              htmlFor="manual-clock-in"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              Clock-in
            </label>
            <input
              id="manual-clock-in"
              type="datetime-local"
              value={clockInLocal}
              onChange={(e) => setClockInLocal(e.target.value)}
              disabled={submitting}
              className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              data-testid="manual-clock-in-input"
            />
          </div>

          <div>
            <label
              htmlFor="manual-clock-out"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              Clock-out (optional — leave blank for an open entry)
            </label>
            <input
              id="manual-clock-out"
              type="datetime-local"
              value={clockOutLocal}
              onChange={(e) => setClockOutLocal(e.target.value)}
              disabled={submitting}
              className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              data-testid="manual-clock-out-input"
            />
          </div>

          <div>
            <label
              htmlFor="manual-break-minutes"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              Break minutes (deducted from worked time)
            </label>
            <input
              id="manual-break-minutes"
              type="number"
              min={0}
              max={600}
              step={5}
              value={breakMinutes}
              onChange={(e) => setBreakMinutes(e.target.value)}
              disabled={submitting}
              className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              data-testid="manual-break-minutes-input"
            />
          </div>

          <div>
            <label
              htmlFor="manual-notes"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              Notes
            </label>
            <textarea
              id="manual-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 500))}
              disabled={submitting}
              rows={3}
              placeholder="Why is this entry being added by hand?"
              className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              data-testid="manual-notes-input"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300"
              data-testid="manual-entry-error"
            >
              {error}
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="min-h-[44px] rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit}
              className="min-h-[44px] rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="manual-entry-submit-button"
            >
              {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Add entry'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
