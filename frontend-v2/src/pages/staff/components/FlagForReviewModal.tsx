/**
 * FlagForReviewModal — Task 34 port of
 * frontend/src/pages/staff/components/FlagForReviewModal.tsx.
 *
 * Confirms flagging a clock entry for follow-up review (G10). ALL logic copied
 * VERBATIM: POST `/api/v2/staff/{id}/clock-entries/{entryId}/flag` with optional
 * reason, AbortController, 403/404 error mapping. Presentation remapped from the
 * raw `dark:`-variant overlay onto the design-system tokens (ink/50 scrim, card
 * panel, warn submit). Every data-testid preserved.
 *
 * Refs: Phase 3 G10 / R8.3 / R16.
 */

import { useCallback, useEffect, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'

export interface FlagForReviewModalProps {
  open: boolean
  onClose: () => void
  staffId: string
  entryId: string
  /** Optional context shown in the modal header (e.g. "Mon 9 Jun · 08:42 → 17:08"). */
  entryLabel?: string | null
  onFlagged?: () => void
}

const REASON_MAX = 500

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

export default function FlagForReviewModal({
  open,
  onClose,
  staffId,
  entryId,
  entryLabel,
  onFlagged,
}: FlagForReviewModalProps) {
  const [reason, setReason] = useState<string>('')
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setReason('')
      setError(null)
      setSubmitting(false)
    }
  }, [open])

  const handleSubmit = useCallback(async () => {
    setError(null)
    setSubmitting(true)
    const controller = new AbortController()
    try {
      const trimmed = reason.trim()
      const payload: Record<string, unknown> = {}
      if (trimmed) payload.reason = trimmed
      await apiClient.post(
        `/api/v2/staff/${staffId}/clock-entries/${entryId}/flag`,
        payload,
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      onFlagged?.()
      onClose()
    } catch (err) {
      if (controller.signal.aborted) return
      const detail = readErrorDetail(err)
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        setError('You do not have permission to flag clock entries.')
      } else if (status === 404) {
        setError('That clock entry could not be found. It may have been removed.')
      } else if (detail) {
        setError(detail)
      } else {
        setError("Couldn't flag the entry. Please try again.")
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [staffId, entryId, reason, onClose, onFlagged])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="flag-for-review-title"
      data-testid="flag-for-review-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4"
    >
      <div className="w-full max-w-md overflow-hidden rounded-card bg-card shadow-pop">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 id="flag-for-review-title" className="text-lg font-semibold text-text">
            Flag for review
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
          {entryLabel && (
            <p className="text-sm text-muted">
              Entry: <span className="mono font-medium text-text">{entryLabel}</span>
            </p>
          )}
          <p className="text-sm text-text">
            This entry will be marked with a 🚩 flag. The week's approval modal
            will require explicit acknowledgement before approving.
          </p>

          <div>
            <label htmlFor="flag-reason" className="block text-sm font-medium text-text">
              Reason (optional)
            </label>
            <textarea
              id="flag-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value.slice(0, REASON_MAX))}
              placeholder="What looks off? (Buddy-punch, photo mismatch, …)"
              disabled={submitting}
              rows={3}
              className="mt-1 w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              data-testid="flag-reason-input"
            />
            <p className="mono mt-1 text-right text-xs text-muted-2">
              {(reason ?? '').length} / {REASON_MAX}
            </p>
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
              data-testid="flag-error"
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
              disabled={submitting}
              className="min-h-[44px] rounded-ctl bg-warn px-4 py-2 text-sm font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="flag-submit-button"
            >
              {submitting ? 'Flagging…' : 'Flag entry'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
