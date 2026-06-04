/**
 * TerminationModal — Task 34 port of
 * frontend/src/pages/staff/components/TerminationModal.tsx.
 *
 * Staff termination workflow (Phase 4 D4). ALL logic copied VERBATIM: end_date +
 * reason + final-pay option toggles, terminateStaff() POST, G16/G25 info banners,
 * submit guards, error extraction. Built on the shared Modal + Button +
 * AlertBanner primitives; inline `dark:` classes remapped onto tokens,
 * `secondary`→`ghost`. Every data-testid preserved.
 *
 * **Validates: Staff Management Phase 4 task D4, Requirements R10 + R14**
 */

import { useCallback, useEffect, useState } from 'react'
import { Button, Modal, AlertBanner } from '@/components/ui'
import { terminateStaff } from '@/api/payslips'
import type { TerminationResult } from '@/api/payslips'

function todayIso(): string {
  const d = new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

function readErrorMessage(err: unknown): string {
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
  if (
    detail &&
    typeof detail === 'object' &&
    'reason' in detail &&
    typeof (detail as { reason?: unknown }).reason === 'string'
  ) {
    return (detail as { reason: string }).reason
  }
  if (err instanceof Error) return err.message
  return 'Termination failed'
}

interface TerminationModalProps {
  staffId: string
  staffName?: string | null
  open: boolean
  onClose: () => void
  /**
   * Called after a successful termination request. The parent should
   * refresh the staff detail and surface the server result via toast.
   */
  onTerminated?: (result: TerminationResult) => void
}

interface FormState {
  end_date: string
  reason: string
  pay_annual_leave: boolean
  pay_alt_days: boolean
  pay_casual_8pct_remainder: boolean
}

const EMPTY_FORM: FormState = {
  end_date: '',
  reason: '',
  pay_annual_leave: true,
  pay_alt_days: true,
  pay_casual_8pct_remainder: true,
}

export default function TerminationModal({
  staffId,
  staffName,
  open,
  onClose,
  onTerminated,
}: TerminationModalProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Reset the form whenever the modal opens. Default end_date to today.
  useEffect(() => {
    if (open) {
      setForm({ ...EMPTY_FORM, end_date: todayIso() })
      setSubmitting(false)
      setError(null)
    }
  }, [open])

  const canSubmit =
    !submitting &&
    form.end_date.trim().length > 0 &&
    form.reason.trim().length > 0

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await terminateStaff(staffId, {
        end_date: form.end_date,
        reason: form.reason.trim(),
        final_pay_options: {
          pay_annual_leave: form.pay_annual_leave,
          pay_alt_days: form.pay_alt_days,
          pay_casual_8pct_remainder: form.pay_casual_8pct_remainder,
        },
      })
      onTerminated?.(result)
      onClose()
    } catch (err) {
      setError(readErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }, [canSubmit, staffId, form, onTerminated, onClose])

  const handleClose = useCallback(() => {
    if (submitting) return
    onClose()
  }, [submitting, onClose])

  const inputCls =
    'mt-1 block w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]'

  return (
    <Modal open={open} onClose={handleClose} title="End employment">
      <div className="space-y-4" data-testid="termination-modal">
        <p className="text-sm text-text">
          {staffName
            ? `End employment for ${staffName}.`
            : 'End employment for this staff member.'}{' '}
          The server will compute the final-pay breakdown and generate a draft termination payslip — you can review it before finalising.
        </p>

        {/* G16 — informational banner about future-leave cancellation. */}
        <AlertBanner variant="info" title="Future-dated approved leave">
          <p>
            Any approved leave requests starting after the end date will be cancelled and the corresponding hours refunded to the leave balance before the s27 payout is calculated. The exact count and hour total will be shown in the confirmation toast.
          </p>
        </AlertBanner>

        {/* G25 — informational banner about pay_period selection. */}
        <AlertBanner variant="info" title="Final payslip pay period">
          <p>
            The final payslip lands in the pay period that contains the end date. If that period is already finalised, it will be reopened for the corrective payslip. If no period covers the end date, a new pay period is rolled. If the period is already paid, the request is refused — contact support.
          </p>
        </AlertBanner>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="block text-sm font-medium text-text">End date</span>
            <input
              type="date"
              value={form.end_date}
              onChange={(e) => setForm((s) => ({ ...s, end_date: e.target.value }))}
              data-testid="termination-end-date"
              className={`mono ${inputCls}`}
            />
          </label>
        </div>

        <label className="block">
          <span className="block text-sm font-medium text-text">Reason</span>
          <textarea
            value={form.reason}
            onChange={(e) => setForm((s) => ({ ...s, reason: e.target.value }))}
            rows={3}
            placeholder="e.g. resignation, restructure, end of fixed-term agreement"
            data-testid="termination-reason"
            className={inputCls}
          />
        </label>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-text">Final pay options</legend>
          <label className="flex items-start gap-2 text-sm text-text">
            <input
              type="checkbox"
              checked={form.pay_annual_leave}
              onChange={(e) => setForm((s) => ({ ...s, pay_annual_leave: e.target.checked }))}
              data-testid="termination-pay-annual-leave"
              className="mt-0.5"
            />
            <span>Pay out remaining annual leave (Holidays Act s27 — greater of ordinary weekly pay vs 52-week average).</span>
          </label>
          <label className="flex items-start gap-2 text-sm text-text">
            <input
              type="checkbox"
              checked={form.pay_alt_days}
              onChange={(e) => setForm((s) => ({ ...s, pay_alt_days: e.target.checked }))}
              data-testid="termination-pay-alt-days"
              className="mt-0.5"
            />
            <span>Pay out unused alternative-holiday (lieu) days at relevant daily pay.</span>
          </label>
          <label className="flex items-start gap-2 text-sm text-text">
            <input
              type="checkbox"
              checked={form.pay_casual_8pct_remainder}
              onChange={(e) => setForm((s) => ({ ...s, pay_casual_8pct_remainder: e.target.checked }))}
              data-testid="termination-pay-casual-8pct"
              className="mt-0.5"
            />
            <span>Pay casual 8% holiday-pay remainder (settles the gap between YTD 8% accrual and amounts already paid each pay run).</span>
          </label>
        </fieldset>

        {error && <AlertBanner variant="error">{error}</AlertBanner>}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={handleSubmit}
            disabled={!canSubmit}
            loading={submitting}
            data-testid="termination-submit"
          >
            End employment
          </Button>
        </div>
      </div>
    </Modal>
  )
}
