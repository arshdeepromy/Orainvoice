/**
 * ManualEntryModal — Task 34 port of
 * frontend/src/pages/staff/components/ManualEntryModal.tsx.
 *
 * Admin-only modal to insert/edit a clock entry by hand. ALL logic copied
 * VERBATIM: POST `/api/v2/staff/{id}/clock/manual` (create) / PATCH
 * `.../{entryId}` (edit), ISO↔local datetime conversion, break minutes, submit
 * guards, 403/409 week_locked/invalid_range mapping, AbortController.
 * Presentation remapped onto the design-system tokens. Every data-testid
 * preserved.
 *
 * Refs: Phase 3 R5 + R8.4 + R16.
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

  const inputCls =
    'mt-1 w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="manual-entry-title"
      data-testid="manual-entry-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-card bg-card shadow-pop">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 id="manual-entry-title" className="text-lg font-semibold text-text">
            {isEdit ? 'Edit clock entry' : 'Add clock entry'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="min-h-[44px] min-w-[44px] rounded-ctl p-2 text-muted-2 hover:text-text focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          >
            <span aria-hidden="true" className="text-xl leading-none">×</span>
          </button>
        </header>

        <div className="space-y-4 px-6 py-4">
          <p className="rounded-ctl border border-accent/30 bg-accent-soft px-3 py-2 text-xs text-accent">
            Manual entries are recorded with <code>source=admin_manual</code> and audited under your user. Photos are not required.
          </p>

          <div>
            <label htmlFor="manual-clock-in" className="block text-sm font-medium text-text">
              Clock-in
            </label>
            <input
              id="manual-clock-in"
              type="datetime-local"
              value={clockInLocal}
              onChange={(e) => setClockInLocal(e.target.value)}
              disabled={submitting}
              className={`mono ${inputCls}`}
              data-testid="manual-clock-in-input"
            />
          </div>

          <div>
            <label htmlFor="manual-clock-out" className="block text-sm font-medium text-text">
              Clock-out (optional — leave blank for an open entry)
            </label>
            <input
              id="manual-clock-out"
              type="datetime-local"
              value={clockOutLocal}
              onChange={(e) => setClockOutLocal(e.target.value)}
              disabled={submitting}
              className={`mono ${inputCls}`}
              data-testid="manual-clock-out-input"
            />
          </div>

          <div>
            <label htmlFor="manual-break-minutes" className="block text-sm font-medium text-text">
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
              className={`mono ${inputCls}`}
              data-testid="manual-break-minutes-input"
            />
          </div>

          <div>
            <label htmlFor="manual-notes" className="block text-sm font-medium text-text">
              Notes
            </label>
            <textarea
              id="manual-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 500))}
              disabled={submitting}
              rows={3}
              placeholder="Why is this entry being added by hand?"
              className={inputCls}
              data-testid="manual-notes-input"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
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
              className="min-h-[44px] rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit}
              className="min-h-[44px] rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:cursor-not-allowed disabled:opacity-50"
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
