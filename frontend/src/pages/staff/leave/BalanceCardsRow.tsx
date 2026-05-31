/**
 * BalanceCardsRow — horizontal row of leave-balance cards.
 *
 * One card per active leave type. Each card surfaces:
 *   - leave type name
 *   - large "available" hours number (accrued − used − pending)
 *   - small accrued / used / pending breakdown
 *   - anniversary date when accrual_method='anniversary'
 *
 * For casual employees the annual-leave card is hidden (per Phase 2 spec
 * §6.4: "annual-leave card hidden for casual; sick + family_violence
 * still accrue pro-rata"). The CasualLeaveBanner is rendered separately
 * by the parent LeaveTab.
 *
 * **Validates: Staff Management Phase 2 task D5**
 */

import type { LeaveBalance, LeaveType } from '../../../api/leave'

interface Props {
  balances: LeaveBalance[]
  leaveTypes: LeaveType[]
  employmentType: string
}

/**
 * Format a numeric-string Decimal as `Nh` with up to 1 decimal place.
 * Renders `0h` when missing / unparseable so the UI never shows NaN.
 */
function fmtHours(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '0h'
  const num = typeof value === 'number' ? value : parseFloat(value)
  if (Number.isNaN(num)) return '0h'
  // 0 → "0h"; 1.5 → "1.5h"; 40 → "40h"
  const rounded = Math.round(num * 10) / 10
  return Number.isInteger(rounded) ? `${rounded}h` : `${rounded.toFixed(1)}h`
}

function formatAnniversary(iso: string | null): string {
  if (!iso) return ''
  // Display as e.g. "12 Mar" — NZ-friendly, no year clutter.
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}

export default function BalanceCardsRow({
  balances,
  leaveTypes,
  employmentType,
}: Props) {
  // Build a quick lookup of leave_type metadata by id.
  const typeById = new Map<string, LeaveType>()
  for (const lt of leaveTypes ?? []) {
    typeById.set(lt.id, lt)
  }

  const isCasual = employmentType === 'casual'

  // Hide annual leave card for casual employees, hide unpaid leave (no accrual)
  // and TOIL Phase 2 placeholder when there's no balance to surface.
  const visible = (balances ?? []).filter((b) => {
    const lt = typeById.get(b.leave_type_id)
    const code = lt?.code ?? b.leave_type_code ?? ''
    if (isCasual && code === 'annual') return false
    return true
  })

  if (visible.length === 0) {
    return (
      <div
        data-testid="balance-cards-empty"
        className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 p-6 text-center text-sm text-gray-500 dark:text-gray-400"
      >
        No leave balances on file yet.
      </div>
    )
  }

  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3"
      data-testid="balance-cards-row"
    >
      {visible.map((bal) => {
        const lt = typeById.get(bal.leave_type_id)
        const name = lt?.name ?? bal.leave_type_name ?? bal.leave_type_code ?? 'Leave'
        const showAnniversary =
          (lt?.accrual_method ?? '') === 'anniversary' && !!bal.anniversary_date
        return (
          <div
            key={bal.id}
            data-testid={`balance-card-${bal.leave_type_code ?? lt?.code ?? bal.id}`}
            className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 shadow-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {name}
              </h3>
              {lt?.confidential_visibility && (
                <span
                  className="text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5 bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200"
                  title="Confidential leave type"
                >
                  Confidential
                </span>
              )}
            </div>
            <div className="mt-2">
              <div
                className="text-3xl font-semibold text-gray-900 dark:text-gray-100"
                data-testid={`balance-available-${bal.leave_type_code ?? bal.id}`}
              >
                {fmtHours(bal.available_hours)}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">
                available
              </div>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-[11px] text-gray-600 dark:text-gray-400">
              <div>
                <div className="font-medium text-gray-700 dark:text-gray-300">
                  {fmtHours(bal.accrued_hours)}
                </div>
                <div>accrued</div>
              </div>
              <div>
                <div className="font-medium text-gray-700 dark:text-gray-300">
                  {fmtHours(bal.used_hours)}
                </div>
                <div>used</div>
              </div>
              <div>
                <div className="font-medium text-gray-700 dark:text-gray-300">
                  {fmtHours(bal.pending_hours)}
                </div>
                <div>pending</div>
              </div>
            </div>
            {showAnniversary && (
              <div className="mt-3 text-[11px] text-gray-500 dark:text-gray-400">
                Anniversary: {formatAnniversary(bal.anniversary_date)}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
