/**
 * RunningLateSheet — staff-initiated "I'm running late" sheet.
 *
 * Posts to `POST /api/v2/staff/me/running-late` with a minutes slider
 * (1–180) and an optional reason. The endpoint:
 *   - 422 `no_upcoming_shift`     — shown as "no shift starting nearby".
 *   - 429 `too_many_late_reports` — already reported 3 times for this shift.
 *   - 200 `{ ok, snoozed_until }` — close sheet, surface success toast.
 *
 * Refs: Phase 3 G3 / R14b.6 (mobile UI) + R14b.7 (web UI). Touch targets
 * ≥ 44×44 per mobile-app steering rule. Safe API consumption: every read
 * uses `?.` chaining and `?? null/0` defaults.
 *
 * Presentation remapped onto the design-system tokens. Logic, handlers
 * and every data-testid preserved verbatim.
 */

import { useCallback, useEffect, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'

export interface RunningLateSheetProps {
  open: boolean
  onClose: () => void
  /** Optional callback fired after a successful POST. */
  onSent?: (snoozedUntil: string | null) => void
}

interface RunningLateResponse {
  ok?: boolean
  snoozed_until?: string | null
}

const MIN_MINUTES = 1
const MAX_MINUTES = 180
const DEFAULT_MINUTES = 15
const REASON_MAX = 200

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

function mapError(err: unknown): string {
  const detail = readErrorDetail(err)
  if (detail === 'no_upcoming_shift') {
    return "We couldn't find a scheduled shift starting nearby. Talk to your manager directly."
  }
  if (detail === 'too_many_late_reports') {
    return 'You have already sent the maximum number of late reports for this shift.'
  }
  const status = (err as { response?: { status?: number } })?.response?.status
  if (status === 401 || status === 403) {
    return 'You are not signed in to a staff account.'
  }
  return "Couldn't send your message. Please try again."
}

export default function RunningLateSheet({
  open,
  onClose,
  onSent,
}: RunningLateSheetProps) {
  const [minutes, setMinutes] = useState<number>(DEFAULT_MINUTES)
  const [reason, setReason] = useState<string>('')
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<boolean>(false)

  // Reset whenever the sheet opens.
  useEffect(() => {
    if (open) {
      setMinutes(DEFAULT_MINUTES)
      setReason('')
      setError(null)
      setSubmitting(false)
      setSuccess(false)
    }
  }, [open])

  const handleSend = useCallback(async () => {
    setError(null)
    setSubmitting(true)
    const controller = new AbortController()
    try {
      const trimmedReason = reason.trim()
      const res = await apiClient.post<RunningLateResponse>(
        '/api/v2/staff/me/running-late',
        {
          minutes_late: minutes,
          reason: trimmedReason || null,
        },
        { signal: controller.signal },
      )
      const snoozedUntil = res.data?.snoozed_until ?? null
      setSuccess(true)
      onSent?.(snoozedUntil)
    } catch (err) {
      if (controller.signal.aborted) return
      setError(mapError(err))
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [minutes, reason, onSent])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="running-late-title"
      data-testid="running-late-sheet"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-t-card bg-card shadow-pop sm:rounded-card">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2
            id="running-late-title"
            className="text-lg font-semibold text-text"
          >
            I'm running late
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="min-h-[44px] min-w-[44px] rounded-ctl p-2 text-muted-2 hover:text-text focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </header>

        {success ? (
          <div className="px-6 py-8 text-center">
            <p className="text-base font-semibold text-ok">
              Thanks — your manager has been notified.
            </p>
            <p className="mt-2 text-sm text-muted">
              The automated late-arrival alert has been suppressed for this
              shift.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="mt-6 inline-flex min-h-[44px] items-center justify-center rounded-ctl bg-accent px-6 py-2 text-sm font-medium text-white hover:bg-accent-press"
              data-testid="running-late-close-button"
            >
              Done
            </button>
          </div>
        ) : (
          <div className="space-y-4 px-6 py-4">
            <div>
              <label
                htmlFor="running-late-minutes"
                className="flex items-baseline justify-between text-sm font-medium text-text"
              >
                <span>How late will you be?</span>
                <span
                  className="mono text-base font-semibold text-accent"
                  data-testid="running-late-minutes-display"
                >
                  {minutes} min
                </span>
              </label>
              <input
                id="running-late-minutes"
                type="range"
                min={MIN_MINUTES}
                max={MAX_MINUTES}
                step={1}
                value={minutes}
                onChange={(e) =>
                  setMinutes(Math.max(MIN_MINUTES, Math.min(MAX_MINUTES, Number(e.target.value) || MIN_MINUTES)))
                }
                disabled={submitting}
                aria-valuemin={MIN_MINUTES}
                aria-valuemax={MAX_MINUTES}
                aria-valuenow={minutes}
                className="mt-2 w-full"
                data-testid="running-late-minutes-slider"
              />
              <div className="mono mt-1 flex justify-between text-xs text-muted">
                <span>{MIN_MINUTES} min</span>
                <span>{MAX_MINUTES} min</span>
              </div>
            </div>

            <div>
              <label
                htmlFor="running-late-reason"
                className="block text-sm font-medium text-text"
              >
                Reason (optional)
              </label>
              <textarea
                id="running-late-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX))}
                placeholder="Traffic, kids, …"
                disabled={submitting}
                rows={3}
                className="mt-1 w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                data-testid="running-late-reason-input"
              />
              <p className="mono mt-1 text-right text-xs text-muted-2">
                {(reason ?? '').length} / {REASON_MAX}
              </p>
            </div>

            {error && (
              <p
                role="alert"
                className="rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
                data-testid="running-late-error"
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
                onClick={() => void handleSend()}
                disabled={submitting}
                className="min-h-[44px] rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:cursor-not-allowed disabled:opacity-50"
                data-testid="running-late-send-button"
              >
                {submitting ? 'Sending…' : 'Send'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
