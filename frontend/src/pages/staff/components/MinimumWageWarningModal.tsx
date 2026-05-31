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

import React from 'react'

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 dark:bg-black/70"
    >
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
        <h2
          id="min-wage-title"
          className="text-lg font-semibold text-gray-900 dark:text-white"
        >
          Below NZ minimum wage
        </h2>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          The proposed hourly rate of ${proposed.toFixed(2)} is below the NZ
          minimum wage of ${threshold.toFixed(2)}.
        </p>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          Continuing will save the rate as-is. An audit log entry will be
          written.
        </p>
        <div className="mt-6 flex gap-3 justify-end">
          <button
            type="button"
            className="px-4 py-2 min-h-[44px] min-w-[44px] rounded border border-gray-300 dark:border-gray-600 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="px-4 py-2 min-h-[44px] min-w-[44px] rounded bg-amber-600 text-white text-sm font-medium hover:bg-amber-700"
            onClick={onConfirm}
          >
            Continue anyway
          </button>
        </div>
      </div>
    </div>
  )
}
