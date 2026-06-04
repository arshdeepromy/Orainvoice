/**
 * ApproveWeekModal — Task 34 port of
 * frontend/src/pages/staff/components/ApproveWeekModal.tsx.
 *
 * Polished week-approval modal for the Hours tab. ALL logic copied VERBATIM:
 * totals breakdown (ordinary/overtime/public-holiday split), unapproved-overtime
 * chip when require_pre_approval, flagged-entries acknowledgement gate, TOIL
 * choice (employee_chooses), POST `/api/v2/staff/{id}/timesheets/{week}/approve`,
 * 403 / flagged_entries_require_acknowledgement mapping, AbortController.
 * Presentation remapped onto the design-system tokens. Every data-testid preserved.
 *
 * Refs: Phase 3 R8.4 / R9 / R10 / R6a / R11 / G1 / G10.
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 p-4"
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-card bg-card shadow-pop">
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 id="approve-week-modal-title" className="text-lg font-semibold text-text">
              Approve hours
            </h2>
            <p className="mono text-xs text-muted">Week starting {weekStart}</p>
          </div>
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
          {/* Totals */}
          <section
            aria-label="Week totals"
            data-testid="approve-week-totals"
            className="rounded-card border border-border bg-canvas p-4"
          >
            <p className="text-sm font-semibold text-text">Totals breakdown</p>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted">Scheduled</dt>
              <dd className="mono text-right font-medium text-text">{fmtMinutes(safeTotals?.total_scheduled_minutes)}</dd>
              <dt className="text-muted">Worked (total)</dt>
              <dd className="mono text-right font-medium text-text">{fmtMinutes(safeTotals?.total_worked_minutes)}</dd>
              <dt className="text-muted">Ordinary</dt>
              <dd className="mono text-right font-medium text-text" data-testid="totals-ordinary">{fmtMinutes(safeTotals?.ordinary_minutes)}</dd>
              <dt className="text-muted">Overtime</dt>
              <dd
                className={`mono text-right font-medium ${(safeTotals?.total_overtime_minutes ?? 0) > 0 ? 'text-warn' : 'text-text'}`}
                data-testid="totals-overtime"
              >
                {fmtMinutes(safeTotals?.total_overtime_minutes)}
              </dd>
              <dt className="text-muted">Public holiday</dt>
              <dd className="mono text-right font-medium text-text" data-testid="totals-public-holiday">{fmtMinutes(safeTotals?.public_holiday_minutes)}</dd>
              <dt className="text-muted">Breaks</dt>
              <dd className="mono text-right font-medium text-text">{fmtMinutes(safeTotals?.total_break_minutes)}</dd>
            </dl>
          </section>

          {/* Unapproved overtime warning chip (G1) */}
          {requirePreApproval && unapprovedOvertime > 0 && (
            <div
              role="status"
              data-testid="unapproved-overtime-chip"
              className="flex items-start gap-3 rounded-ctl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn"
            >
              <span aria-hidden="true" className="text-lg leading-none">⚠</span>
              <p>
                <span className="font-semibold">{fmtMinutes(unapprovedOvertime)} of unapproved overtime</span>{' '}
                — no overtime request was approved for this work. Phase 4 payroll will decide whether to pay or hold it.
              </p>
            </div>
          )}

          {/* Flagged-entries acknowledgement (G10) */}
          {flagged > 0 && (
            <div
              role="alert"
              data-testid="flagged-acknowledgement"
              className="rounded-ctl border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-warn"
            >
              <p className="font-semibold">
                {flagged} {flagged === 1 ? 'entry is' : 'entries are'} flagged for review.
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
                  I have reviewed the flagged entries and want to approve anyway. The week can still be re-opened later.
                </span>
              </label>
            </div>
          )}

          {/* TOIL choice — only when org policy is employee_chooses */}
          {showToilChoice && (
            <fieldset className="space-y-2 rounded-card border border-border p-4">
              <legend className="text-sm font-medium text-text">Overtime handling</legend>
              <label className="flex items-start gap-2 text-sm text-text">
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
              <label className="flex items-start gap-2 text-sm text-text">
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
            <label htmlFor="approve-week-notes" className="block text-sm font-medium text-text">
              Notes (optional)
            </label>
            <textarea
              id="approve-week-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 500))}
              disabled={submitting}
              rows={3}
              className="mt-1 w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              data-testid="approve-week-notes-input"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-ctl bg-danger-soft px-3 py-2 text-sm font-medium text-danger"
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
              className="min-h-[44px] rounded-ctl border border-border bg-card px-4 py-2 text-sm font-medium text-text hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit}
              className="min-h-[44px] rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:cursor-not-allowed disabled:opacity-50"
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
