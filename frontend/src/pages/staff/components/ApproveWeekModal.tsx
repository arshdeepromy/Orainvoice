/**
 * ApproveWeekModal — polished week-approval modal for the Hours tab.
 *
 * Shows the totals breakdown with explicit ordinary / overtime /
 * public-holiday split, surfaces the count of `unapproved_overtime`
 * minutes when the org's `overtime_policy.require_pre_approval=true`,
 * and requires explicit acknowledgement when there are flagged entries.
 *
 * POSTs `/api/v2/staff/{staff_id}/timesheets/{week_start}/approve` with
 *   { toil_choice?, acknowledge_flagged?, notes? }.
 *
 * The inline `ApproveWeekBar` in HoursTab.tsx remains for in-page
 * approval; this modal exists for callers that prefer a modal flow with
 * a richer breakdown (e.g. a future "Approval queue" page or a deep-link
 * from the manager dashboard).
 *
 * Refs: Phase 3 R8.4 (acknowledgement requirement), R9 (totals + split),
 * R10/R6a (overtime), R11 (TOIL choice), G1 + G10. Touch targets ≥ 44×44.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'

export type OvertimeHandling = 'pay_cash' | 'toil' | 'employee_chooses'
export type ToilChoice = 'pay_cash' | 'toil'

export interface ApproveWeekModalTotals {
  total_worked_minutes?: number | null
  total_scheduled_minutes?: number | null
  ordinary_minutes?: number | null
  total_overtime_minutes?: number | null
  public_holiday_minutes?: number | null
  total_break_minutes?: number | null
  unapproved_overtime_minutes?: number | null
}

export interface ApproveWeekModalProps {
  open: boolean
  onClose: () => void
  staffId: string
  /** Monday-aligned ISO date (YYYY-MM-DD). */
  weekStart: string
  totals: ApproveWeekModalTotals | null
  flaggedCount?: number | null
  /** Org-level `overtime_handling` enum from Phase 2. */
  overtimeHandling?: OvertimeHandling | null
  /** Org-level `overtime_policy.require_pre_approval` flag. */
  requirePreApproval?: boolean
  onApproved?: () => void
}

function fmtMinutes(mins: number | null | undefined): string {
  const safe = mins ?? 0
  const sign = safe < 0 ? '-' : ''
  const v = Math.abs(safe)
  const h = Math.floor(v / 60)
  const m = v % 60
  if (h > 0 && m > 0) return `${sign}${h}h ${m}m`
  if (h > 0) return `${sign}${h}h`
  return `${sign}${m}m`
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

export default function ApproveWeekModal({
  open,
  onClose,
  staffId,
  weekStart,
  totals,
  flaggedCount,
  overtimeHandling,
  requirePreApproval,
  onApproved,
}: ApproveWeekModalProps) {
  const [acknowledgeFlagged, setAcknowledgeFlagged] = useState<boolean>(false)
  const [toilChoice, setToilChoice] = useState<ToilChoice>('pay_cash')
  const [notes, setNotes] = useState<string>('')
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Reset the form whenever the modal opens.
  useEffect(() => {
    if (open) {
      setAcknowledgeFlagged(false)
      setToilChoice('pay_cash')
      setNotes('')
      setSubmitting(false)
      setError(null)
    }
  }, [open])

  const flagged = flaggedCount ?? 0
  const safeTotals = useMemo<ApproveWeekModalTotals>(
    () => totals ?? {},
    [totals],
  )
  const unapprovedOvertime = safeTotals?.unapproved_overtime_minutes ?? 0
  const showToilChoice = overtimeHandling === 'employee_chooses'

  const canSubmit = !submitting && (flagged === 0 || acknowledgeFlagged)

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setError(null)
    setSubmitting(true)
    const controller = new AbortController()
    try {
      const payload: Record<string, unknown> = {}
      if (flagged > 0) payload.acknowledge_flagged = acknowledgeFlagged
      if (showToilChoice) payload.toil_choice = toilChoice
      const trimmed = notes.trim()
      if (trimmed) payload.notes = trimmed

      await apiClient.post(
        `/api/v2/staff/${staffId}/timesheets/${weekStart}/approve`,
        payload,
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      onApproved?.()
      onClose()
    } catch (err) {
      if (controller.signal.aborted) return
      const detail = readErrorDetail(err)
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        setError('You do not have permission to approve this week.')
      } else if (detail === 'flagged_entries_require_acknowledgement') {
        setError('Please tick the acknowledgement before approving.')
      } else if (detail) {
        setError(detail)
      } else {
        setError("Couldn't approve the week. Please try again.")
      }
    } finally {
      if (!controller.signal.aborted) setSubmitting(false)
    }
  }, [
    canSubmit,
    acknowledgeFlagged,
    flagged,
    showToilChoice,
    toilChoice,
    notes,
    staffId,
    weekStart,
    onApproved,
    onClose,
  ])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="approve-week-modal-title"
      data-testid="approve-week-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-xl dark:bg-gray-900">
        <header className="flex items-center justify-between border-b border-gray-200 px-6 py-4 dark:border-gray-700">
          <div>
            <h2
              id="approve-week-modal-title"
              className="text-lg font-semibold text-gray-900 dark:text-gray-100"
            >
              Approve hours
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Week starting {weekStart}
            </p>
          </div>
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
          {/* Totals */}
          <section
            aria-label="Week totals"
            data-testid="approve-week-totals"
            className="rounded-md border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800"
          >
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Totals breakdown
            </p>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-gray-600 dark:text-gray-400">Scheduled</dt>
              <dd className="text-right font-medium text-gray-900 dark:text-gray-100">
                {fmtMinutes(safeTotals?.total_scheduled_minutes)}
              </dd>
              <dt className="text-gray-600 dark:text-gray-400">Worked (total)</dt>
              <dd className="text-right font-medium text-gray-900 dark:text-gray-100">
                {fmtMinutes(safeTotals?.total_worked_minutes)}
              </dd>
              <dt className="text-gray-600 dark:text-gray-400">Ordinary</dt>
              <dd
                className="text-right font-medium text-gray-900 dark:text-gray-100"
                data-testid="totals-ordinary"
              >
                {fmtMinutes(safeTotals?.ordinary_minutes)}
              </dd>
              <dt className="text-gray-600 dark:text-gray-400">Overtime</dt>
              <dd
                className={`text-right font-medium ${
                  (safeTotals?.total_overtime_minutes ?? 0) > 0
                    ? 'text-amber-700 dark:text-amber-300'
                    : 'text-gray-900 dark:text-gray-100'
                }`}
                data-testid="totals-overtime"
              >
                {fmtMinutes(safeTotals?.total_overtime_minutes)}
              </dd>
              <dt className="text-gray-600 dark:text-gray-400">Public holiday</dt>
              <dd
                className="text-right font-medium text-gray-900 dark:text-gray-100"
                data-testid="totals-public-holiday"
              >
                {fmtMinutes(safeTotals?.public_holiday_minutes)}
              </dd>
              <dt className="text-gray-600 dark:text-gray-400">Breaks</dt>
              <dd className="text-right font-medium text-gray-900 dark:text-gray-100">
                {fmtMinutes(safeTotals?.total_break_minutes)}
              </dd>
            </dl>
          </section>

          {/* Unapproved overtime warning chip (G1) */}
          {requirePreApproval && unapprovedOvertime > 0 && (
            <div
              role="status"
              data-testid="unapproved-overtime-chip"
              className="flex items-start gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-100"
            >
              <span aria-hidden="true" className="text-lg leading-none">
                ⚠
              </span>
              <p>
                <span className="font-semibold">
                  {fmtMinutes(unapprovedOvertime)} of unapproved overtime
                </span>{' '}
                — no overtime request was approved for this work. Phase 4
                payroll will decide whether to pay or hold it.
              </p>
            </div>
          )}

          {/* Flagged-entries acknowledgement (G10) */}
          {flagged > 0 && (
            <div
              role="alert"
              data-testid="flagged-acknowledgement"
              className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-100"
            >
              <p className="font-semibold">
                {flagged} {flagged === 1 ? 'entry is' : 'entries are'} flagged
                for review.
              </p>
              <label className="mt-2 flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={acknowledgeFlagged}
                  onChange={(e) => setAcknowledgeFlagged(e.target.checked)}
                  className="mt-0.5"
                  data-testid="flagged-acknowledge-checkbox"
                />
                <span>
                  I have reviewed the flagged entries and want to approve
                  anyway. The week can still be re-opened later.
                </span>
              </label>
            </div>
          )}

          {/* TOIL choice — only when org policy is employee_chooses */}
          {showToilChoice && (
            <fieldset className="space-y-2 rounded-md border border-gray-200 p-4 dark:border-gray-700">
              <legend className="text-sm font-medium text-gray-700 dark:text-gray-200">
                Overtime handling
              </legend>
              <label className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="radio"
                  name="toil-choice"
                  value="pay_cash"
                  checked={toilChoice === 'pay_cash'}
                  onChange={() => setToilChoice('pay_cash')}
                  data-testid="toil-choice-cash"
                />
                <span>Pay overtime in cash this period.</span>
              </label>
              <label className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="radio"
                  name="toil-choice"
                  value="toil"
                  checked={toilChoice === 'toil'}
                  onChange={() => setToilChoice('toil')}
                  data-testid="toil-choice-toil"
                />
                <span>Bank as TOIL leave.</span>
              </label>
            </fieldset>
          )}

          {/* Notes */}
          <div>
            <label
              htmlFor="approve-week-notes"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              Notes (optional)
            </label>
            <textarea
              id="approve-week-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 500))}
              disabled={submitting}
              rows={3}
              className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              data-testid="approve-week-notes-input"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300"
              data-testid="approve-week-error"
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
              data-testid="approve-week-submit-button"
            >
              {submitting ? 'Approving…' : 'Approve hours'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
