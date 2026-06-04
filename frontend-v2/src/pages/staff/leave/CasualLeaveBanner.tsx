/**
 * CasualLeaveBanner — info banner for casual employees explaining the
 * 8% holiday-pay-as-you-go arrangement, with a note that sick + family
 * violence leave still accrue pro-rata.
 *
 * Per Phase 2 design §6.1 / §7.2 — rendered between the balance row and
 * the ledger when `staff.employment_type === 'casual'`.
 *
 * Presentation remapped onto the design-system tokens (blue info →
 * accent). Logic + copy + data-testid preserved verbatim.
 *
 * **Validates: Staff Management Phase 2 task D5**
 */

export default function CasualLeaveBanner() {
  return (
    <div
      role="note"
      data-testid="casual-leave-banner"
      className="rounded-card border border-border bg-accent-soft p-4"
    >
      <div className="flex items-start gap-3">
        <span className="text-accent" aria-hidden="true">
          ℹ️
        </span>
        <div className="text-sm text-text">
          <p className="font-medium">Casual employee — pay-as-you-go holiday pay</p>
          <p className="mt-1 text-muted">
            As a casual employee, you receive holiday pay (8% of gross) on each
            pay run instead of accruing annual leave. You still accrue sick
            leave and family violence leave pro-rata.
          </p>
        </div>
      </div>
    </div>
  )
}
