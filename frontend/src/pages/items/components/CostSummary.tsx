import type { PackageComponent } from '../types'

interface CostSummaryProps {
  components: PackageComponent[]
  sellPrice: number
  userRole: string
}

/**
 * Displays "Total Package Cost" and "Profit" (sell price − cost).
 * Red styling + warning indicator when profit is negative.
 * Only visible to `org_admin` or `global_admin` roles.
 * Recalculates on every component change (derived state, no API call).
 *
 * Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.7
 */
export default function CostSummary({ components, sellPrice, userRole }: CostSummaryProps) {
  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'

  if (!isAdmin) {
    return null
  }

  // Calculate total package cost from component snapshots
  const totalCost = (components ?? []).reduce((sum, comp) => {
    const cost = comp.cost_per_unit_snapshot ?? 0
    if (comp.catalogue_type === 'fluid') {
      return sum + cost * (comp.volume ?? 0)
    }
    return sum + cost * (comp.quantity ?? 0)
  }, 0)

  const profit = sellPrice - totalCost
  const isNegativeProfit = profit < 0

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/50">
      <h4 className="mb-3 text-sm font-semibold text-gray-700 dark:text-gray-300">
        Cost Summary
      </h4>

      <div className="space-y-2">
        {/* Total Package Cost */}
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600 dark:text-gray-400">Total Package Cost</span>
          <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
            ${totalCost.toFixed(2)}
          </span>
        </div>

        {/* Sell Price */}
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600 dark:text-gray-400">Sell Price</span>
          <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
            ${sellPrice.toFixed(2)}
          </span>
        </div>

        {/* Divider */}
        <div className="border-t border-gray-200 dark:border-gray-700" />

        {/* Profit */}
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600 dark:text-gray-400">Profit</span>
          <div className="flex items-center gap-2">
            {isNegativeProfit && (
              <svg
                className="h-4 w-4 text-red-500"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-label="Negative profit warning"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
                />
              </svg>
            )}
            <span
              className={`text-sm font-semibold ${
                isNegativeProfit
                  ? 'text-red-600 dark:text-red-400'
                  : 'text-green-600 dark:text-green-400'
              }`}
            >
              ${profit.toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
