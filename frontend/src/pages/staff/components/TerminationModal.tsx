/**
 * TerminationModal — Staff termination workflow (Phase 4 task D4).
 *
 * Per design.md §6.4 and R10:
 *   - Form: end_date (date picker), reason (textarea), final_pay_options
 *     toggles (pay_annual_leave, pay_alt_days, pay_casual_8pct_remainder
 *     — all default true).
 *   - Confirm button POSTs to terminateStaff(staffId, ...).
 *   - Static informational banner (G16) about cancellation of future-
 *     dated approved leave — actuals computed server-side and surfaced
 *     via the response toast in the parent page.
 *   - Static informational banner (G25) about the chosen pay_period
 *     selection rule (open / reopen-finalised / new-period).
 *
 * Defensive:
 *   - end_date and reason both required before Submit enables.
 *   - Server response uses `?? null` defaults; tolerated as free-form.
 *   - Parent (caller) is responsible for refreshing staff detail after
 *     a successful termination via `onTerminated`.
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
   * refresh the staff detail (employment_end_date / is_active flipped)
   * and surface the server result via toast.
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

  // Reset the form whenever the modal opens. Default end_date to today
  // so the date picker has a sensible starting value.
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

  return (
    <Modal open={open} onClose={handleClose} title="End employment">
      <div className="space-y-4" data-testid="termination-modal">
        <p className="text-sm text-gray-700 dark:text-gray-300">
          {staffName
            ? `End employment for ${staffName}.`
            : 'End employment for this staff member.'}{' '}
          The server will compute the final-pay breakdown and generate a
          draft termination payslip — you can review it before finalising.
        </p>

        {/* G16 — informational banner about future-leave cancellation. */}
        <AlertBanner variant="info" title="Future-dated approved leave">
          <p>
            Any approved leave requests starting after the end date will be
            cancelled and the corresponding hours refunded to the leave
            balance before the s27 payout is calculated. The exact count and
            hour total will be shown in the confirmation toast.
          </p>
        </AlertBanner>

        {/* G25 — informational banner about pay_period selection. */}
        <AlertBanner variant="info" title="Final payslip pay period">
          <p>
            The final payslip lands in the pay period that contains the end
            date. If that period is already finalised, it will be reopened
            for the corrective payslip. If no period covers the end date, a
            new pay period is rolled. If the period is already paid, the
            request is refused — contact support.
          </p>
        </AlertBanner>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="block text-sm font-medium text-gray-800 dark:text-gray-200">
              End date
            </span>
            <input
              type="date"
              value={form.end_date}
              onChange={(e) =>
                setForm((s) => ({ ...s, end_date: e.target.value }))
              }
              data-testid="termination-end-date"
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
            />
          </label>
        </div>

        <label className="block">
          <span className="block text-sm font-medium text-gray-800 dark:text-gray-200">
            Reason
          </span>
          <textarea
            value={form.reason}
            onChange={(e) =>
              setForm((s) => ({ ...s, reason: e.target.value }))
            }
            rows={3}
            placeholder="e.g. resignation, restructure, end of fixed-term agreement"
            data-testid="termination-reason"
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
          />
        </label>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-800 dark:text-gray-200">
            Final pay options
          </legend>
          <label className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={form.pay_annual_leave}
              onChange={(e) =>
                setForm((s) => ({
                  ...s,
                  pay_annual_leave: e.target.checked,
                }))
              }
              data-testid="termination-pay-annual-leave"
              className="mt-0.5"
            />
            <span>
              Pay out remaining annual leave (Holidays Act s27 — greater of
              ordinary weekly pay vs 52-week average).
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={form.pay_alt_days}
              onChange={(e) =>
                setForm((s) => ({ ...s, pay_alt_days: e.target.checked }))
              }
              data-testid="termination-pay-alt-days"
              className="mt-0.5"
            />
            <span>
              Pay out unused alternative-holiday (lieu) days at relevant
              daily pay.
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={form.pay_casual_8pct_remainder}
              onChange={(e) =>
                setForm((s) => ({
                  ...s,
                  pay_casual_8pct_remainder: e.target.checked,
                }))
              }
              data-testid="termination-pay-casual-8pct"
              className="mt-0.5"
            />
            <span>
              Pay casual 8% holiday-pay remainder (settles the gap between
              YTD 8% accrual and amounts already paid each pay run).
            </span>
          </label>
        </fieldset>

        {error && <AlertBanner variant="error">{error}</AlertBanner>}

        <div className="flex justify-end gap-2">
          <Button
            variant="secondary"
            onClick={handleClose}
            disabled={submitting}
          >
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
