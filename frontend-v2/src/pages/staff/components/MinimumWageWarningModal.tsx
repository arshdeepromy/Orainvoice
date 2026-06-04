/**
 * MinimumWageWarningModal
 *
 * Confirmation modal shown when an org admin saves a staff record with
 * an hourly rate below the NZ minimum wage threshold. Confirming triggers
 * the caller to re-submit with `minimum_wage_override: true`, which the
 * backend records via `audit_log` action='staff.minimum_wage_override'.
 *
 * Refs: Staff Management Phase 1 — R4
 */

import { Button } from '@/components/ui'

interface Props {
  threshold: number
  proposed: number
  onCancel: () => void
  onConfirm: () => void
}

export default function MinimumWageWarningModal({
  threshold,
  proposed,
  onCancel,
  onConfirm,
}: Props) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="min-wage-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50 px-4"
    >
      <div className="w-full max-w-md rounded-card bg-card p-6 shadow-pop">
        <h2
          id="min-wage-title"
          className="text-[15px] font-semibold text-text"
        >
          Below NZ minimum wage
        </h2>
        <p className="mt-2 text-[13.5px] text-muted">
          The proposed hourly rate of <span className="mono">${proposed.toFixed(2)}</span> is below the NZ
          minimum wage of <span className="mono">${threshold.toFixed(2)}</span>.
        </p>
        <p className="mt-2 text-[13.5px] text-muted">
          Continuing will save the rate as-is. An audit log entry will be
          written.
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <button
            type="button"
            className="inline-flex h-10 items-center justify-center rounded-ctl bg-warn px-4 text-[13.5px] font-semibold text-white hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-card"
            onClick={onConfirm}
          >
            Continue anyway
          </button>
        </div>
      </div>
    </div>
  )
}
