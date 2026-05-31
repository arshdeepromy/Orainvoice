/**
 * RunningLateSheet (mobile) — staff-initiated "I'm running late" bottom sheet.
 *
 * Adapted from `frontend/src/pages/staff/components/RunningLateSheet.tsx`
 * (Phase 3 D5 / G3 / R14b) for the mobile app's component library
 * (`MobileModal` bottom sheet, `MobileButton`, etc.).
 *
 * POSTs to `/api/v2/staff/me/running-late` with a minutes value and an
 * optional reason. Backend responses:
 *   - 422 `no_upcoming_shift`     — surfaced as a friendly banner.
 *   - 429 `too_many_late_reports` — already reported 3 times for this shift.
 *   - 200 `{ ok, snoozed_until }` — render success state, fire `onSent`.
 *
 * Refs: Phase 3 G3 / R14b.6 (mobile UI). Touch targets ≥ 44×44 per
 * #[[file:.kiro/steering/mobile-app.md]]. Safe API consumption per
 * #[[file:.kiro/steering/safe-api-consumption.md]] — every API read uses
 * `?.` chaining and `?? null` defaults; every `useEffect` with an API
 * call uses `AbortController`.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'
import { MobileModal } from '@/components/ui'
import { MobileButton } from '@/components/ui'

export interface RunningLateSheetProps {
  /** Whether the sheet is open. */
  open: boolean
  /** Called when the sheet is dismissed (cancel button, backdrop, swipe, escape). */
  onClose: () => void
  /** Called after a successful POST. */
  onSent?: (snoozedUntil: string | null) => void
}

interface RunningLateResponse {
  ok?: boolean | null
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

function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
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

/**
 * RunningLateSheet — mobile bottom-sheet variant.
 *
 * Renders nothing when `open=false`. When open, renders inside a
 * `MobileModal` (bottom sheet w/ swipe-to-dismiss + safe-area inset).
 */
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

  const abortRef = useRef<AbortController | null>(null)

  // Reset all local state whenever the sheet opens.
  useEffect(() => {
    if (open) {
      setMinutes(DEFAULT_MINUTES)
      setReason('')
      setError(null)
      setSubmitting(false)
      setSuccess(false)
    }
  }, [open])

  // Abort any in-flight POST when the sheet closes or unmounts.
  useEffect(() => {
    if (!open) {
      abortRef.current?.abort()
      abortRef.current = null
    }
    return () => {
      abortRef.current?.abort()
      abortRef.current = null
    }
  }, [open])

  const handleSend = useCallback(async () => {
    setError(null)
    setSubmitting(true)
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
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
      if (controller.signal.aborted) return
      const snoozedUntil = res.data?.snoozed_until ?? null
      setSuccess(true)
      onSent?.(snoozedUntil)
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return
      setError(mapError(err))
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [minutes, reason, onSent])

  return (
    <MobileModal
      isOpen={open}
      onClose={onClose}
      title="I'm running late"
      swipeToDismiss
    >
      {success ? (
        <div className="space-y-3 py-4 text-center">
          <p className="text-base font-semibold text-emerald-700 dark:text-emerald-300">
            Thanks — your manager has been notified.
          </p>
          <p className="text-sm text-gray-600 dark:text-gray-300">
            The automated late-arrival alert has been suppressed for this
            shift.
          </p>
          <div className="pt-2">
            <MobileButton
              variant="primary"
              fullWidth
              onClick={onClose}
              data-testid="running-late-close-button"
            >
              Done
            </MobileButton>
          </div>
        </div>
      ) : (
        <div className="space-y-4 py-2">
          <div>
            <label
              htmlFor="running-late-minutes"
              className="flex items-baseline justify-between text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              <span>How late will you be?</span>
              <span
                className="text-base font-semibold text-blue-700 dark:text-blue-300"
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
                setMinutes(
                  Math.max(
                    MIN_MINUTES,
                    Math.min(
                      MAX_MINUTES,
                      Number(e.target.value) || MIN_MINUTES,
                    ),
                  ),
                )
              }
              disabled={submitting}
              aria-valuemin={MIN_MINUTES}
              aria-valuemax={MAX_MINUTES}
              aria-valuenow={minutes}
              className="mt-2 w-full"
              data-testid="running-late-minutes-slider"
            />
            <div className="mt-1 flex justify-between text-xs text-gray-500 dark:text-gray-400">
              <span>{MIN_MINUTES} min</span>
              <span>{MAX_MINUTES} min</span>
            </div>
          </div>

          <div>
            <label
              htmlFor="running-late-reason"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
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
              className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              data-testid="running-late-reason-input"
            />
            <p className="mt-1 text-right text-xs text-gray-400 dark:text-gray-500">
              {(reason ?? '').length} / {REASON_MAX}
            </p>
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300"
              data-testid="running-late-error"
            >
              {error}
            </p>
          )}

          <div className="flex flex-col gap-2 pt-2 sm:flex-row sm:justify-end">
            <MobileButton
              variant="secondary"
              onClick={onClose}
              disabled={submitting}
              fullWidth
            >
              Cancel
            </MobileButton>
            <MobileButton
              variant="primary"
              onClick={() => void handleSend()}
              isLoading={submitting}
              fullWidth
              data-testid="running-late-send-button"
            >
              Send
            </MobileButton>
          </div>
        </div>
      )}
    </MobileModal>
  )
}
