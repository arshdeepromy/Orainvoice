/**
 * OvertimeRequestModal — Task 34 port of
 * frontend/src/pages/staff/components/OvertimeRequestModal.tsx.
 *
 * Submit an overtime pre-approval request. ALL logic copied VERBATIM: POST
 * `/api/v2/overtime-requests` { staff_id?, schedule_entry_id?,
 * proposed_extra_minutes, reason? }, min/max validation, AbortController,
 * invalid_minutes mapping. Presentation remapped onto the design-system tokens.
 * Every data-testid preserved.
 *
 * Refs: Phase 3 R10.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'

export interface OvertimeRequestModalProps {
  open: boolean
  onClose: () => void
  /** When set, the request is associated with a specific schedule entry. */
  scheduleEntryId?: string | null
  /** When set, the request is created on behalf of this staff member. */
  staffId?: string | null
  /** Display label for the shift, shown in the header for context. */
  shiftLabel?: string | null
  onSubmitted?: () => void
}

interface OvertimeRequestResponse {
  id?: string | null
  status?: string | null
}

const MIN_EXTRA_MINUTES = 15
const MAX_EXTRA_MINUTES = 600
const REASON_MAX = 500

function readErrorDetail(err: unknown): string {
  if (axios.isCancel?.(err)) return ''
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
  return ''
}

export default function OvertimeRequestModal({
  open,
  onClose,
  scheduleEntryId,
  staffId,
  shiftLabel,
  onSubmitted,
}: OvertimeRequestModalProps) {
  const [extraMinutes, setExtraMinutes] = useState<string>('60')
  const [reason, setReason] = useState<string>('')
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setExtraMinutes('60')
      setReason('')
      setError(null)
      setSubmitting(false)
    }
  }, [open])

  const parsedMinutes = useMemo(() => {
    const n = Number.parseInt(extraMinutes, 10)
    if (!Number.isFinite(n)) return Number.NaN
    return n
  }, [extraMinutes])

  const canSubmit =
    !submitting &&
    Number.isFinite(parsedMinutes) &&
    parsedMinutes >= MIN_EXTRA_MINUTES &&
    parsedMinutes <= MAX_EXTRA_MINUTES

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setSubmitting(true)
    const controller = new AbortController()
    try {
      const payload: Record<string, unknown> = {
        proposed_extra_minutes: parsedMinutes,
      }
      if (staffId) payload.staff_id = staffId
      if (scheduleEntryId) payload.schedule_entry_id = scheduleEntryId
      const trimmedReason = reason.trim()
      if (trimmedReason) payload.reason = trimmedReason

      await apiClient.post<OvertimeRequestResponse>(
        '/api/v2/overtime-requests',
        payload,
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      onSubmitted?.()
      onClose()
    } catch (err) {
      if (controller.signal.aborted) return
      const detail = readErrorDetail(err)
      if (detail === 'invalid_minutes') {
        setError('The minutes value is out of range.')
      } else if (detail) {
        setError(detail)
      } else {
        setError("Couldn't submit the request. Please try again.")
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [canSubmit, parsedMinutes, reason, staffId, scheduleEntryId, onClose, onSubmitted])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="overtime-request-title"
      data-testid="overtime-request-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-card bg-card shadow-pop">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 id="overtime-request-title" className="text-lg font-semibold text-text">
            Request overtime
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
          {shiftLabel && (
            <p className="text-sm text-muted">
              For shift: <span className="font-medium text-text">{shiftLabel}</span>
            </p>
          )}

          <div>
            <label htmlFor="overtime-minutes" className="block text-sm font-medium text-text">
              Extra minutes
            </label>
            <input
              id="overtime-minutes"
              type="number"
              min={MIN_EXTRA_MINUTES}
              max={MAX_EXTRA_MINUTES}
              step={15}
              value={extraMinutes}
              onChange={(e) => setExtraMinutes(e.target.value)}
              disabled={submitting}
              className="mono mt-1 w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              data-testid="overtime-minutes-input"
            />
            <p className="mt-1 text-xs text-muted">
              Minimum {MIN_EXTRA_MINUTES} minutes; maximum {MAX_EXTRA_MINUTES} minutes ({Math.round(MAX_EXTRA_MINUTES / 60)}h).
            </p>
          </div>

          <div>
            <label htmlFor="overtime-reason" className="block text-sm font-medium text-text">
              Reason
            </label>
            <textarea
              id="overtime-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX))}
              placeholder="Why is this overtime needed?"
              disabled={submitting}
              rows={4}
              className="mt-1 w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              data-testid="overtime-reason-input"
            />
            <p className="mono mt-1 text-right text-xs text-muted-2">
              {(reason ?? '').length} / {REASON_MAX}
            </p>
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
              data-testid="overtime-error"
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
              data-testid="overtime-submit-button"
            >
              {submitting ? 'Sending…' : 'Submit request'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
