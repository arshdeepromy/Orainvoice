import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface TaxSummary {
  id: string
  label: string
  amount: number
  type: 'liability' | 'refund' | 'neutral'
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

/**
 * Tax position screen — current tax liability or refund position summary.
 *
 * Requirements: 26.3
 */
export default function TaxPositionScreen() {
  const {
    items,
    isLoading,
    isRefreshing,
    refresh,
  } = useApiList<TaxSummary>({
    endpoint: '/api/v1/gst/position',
    dataKey: 'items',
    pageSize: 50,
  })

  // Calculate net position
  const netPosition = items.reduce((sum, item) => {
    if (item.type === 'liability') return sum + (item.amount ?? 0)
    if (item.type === 'refund') return sum - (item.amount ?? 0)
    return sum
  }, 0)

  const isRefund = netPosition < 0

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Tax Position
        </h1>

        {/* Net position card */}
        <MobileCard>
          <div className="flex flex-col items-center gap-2">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {isRefund ? 'Net Refund Due' : 'Net Tax Liability'}
            </p>
            <p
              className={`text-3xl font-bold ${
                isRefund
                  ? 'text-green-600 dark:text-green-400'
                  : netPosition > 0
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-gray-900 dark:text-gray-100'
              }`}
            >
              {formatCurrency(Math.abs(netPosition))}
            </p>
          </div>
        </MobileCard>

        {/* Breakdown */}
        {isLoading ? (
          <div className="flex justify-center py-8">
            <MobileSpinner size="md" />
          </div>
        ) : items.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
            No tax data available
          </p>
        ) : (
          <MobileCard>
            <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
              Breakdown
            </h2>
            <div className="flex flex-col gap-3 text-sm">
              {items.map((item) => (
                <div key={item.id} className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">
                    {item.label ?? 'Tax Item'}
                  </span>
                  <span
                    className={`font-medium ${
                      item.type === 'refund'
                        ? 'text-green-600 dark:text-green-400'
                        : item.type === 'liability'
                          ? 'text-red-600 dark:text-red-400'
                          : 'text-gray-900 dark:text-gray-100'
                    }`}
                  >
                    {item.type === 'refund' ? '-' : ''}{formatCurrency(item.amount)}
                  </span>
                </div>
              ))}
            </div>
          </MobileCard>
        )}
      </div>
    </PullRefresh>
  )
}
