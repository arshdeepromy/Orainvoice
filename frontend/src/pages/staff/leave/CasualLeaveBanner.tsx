/**
 * CasualLeaveBanner — info banner for casual employees explaining the
 * 8% holiday-pay-as-you-go arrangement, with a note that sick + family
 * violence leave still accrue pro-rata.
 *
 * Per Phase 2 design §6.1 / §7.2 — rendered between the balance row and
 * the ledger when `staff.employment_type === 'casual'`.
 *
 * **Validates: Staff Management Phase 2 task D5**
 */

export default function CasualLeaveBanner() {
  return (
    <div
      role="note"
      data-testid="casual-leave-banner"
      className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 p-4"
    >
      <div className="flex items-start gap-3">
        <span className="text-blue-600 dark:text-blue-300" aria-hidden="true">
          ℹ️
        </span>
        <div className="text-sm text-blue-900 dark:text-blue-100">
          <p className="font-medium">Casual employee — pay-as-you-go holiday pay</p>
          <p className="mt-1 text-blue-800 dark:text-blue-200">
            As a casual employee, you receive holiday pay (8% of gross) on each
            pay run instead of accruing annual leave. You still accrue sick
            leave and family violence leave pro-rata.
          </p>
        </div>
      </div>
    </div>
  )
}
