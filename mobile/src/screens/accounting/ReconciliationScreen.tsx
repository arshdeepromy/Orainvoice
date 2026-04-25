import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileListItem, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface ReconciliationSummary {
  id: string
  bank_account_id: string
  bank_account_name: string
  unreconciled_count: number
  unreconciled_amount: number
  last_reconciled_date: string | null
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Never'
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

/**
 * Reconciliation screen — reconciliation dashboard with unreconciled
 * counts and amounts per bank account.
 *
 * Requirements: 25.3
 */
export default function ReconciliationScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    refresh,
  } = useApiList<ReconciliationSummary>({
    endpoint: '/api/v1/banking/reconciliation',
    dataKey: 'items',
    pageSize: 50,
  })

  const handleTap = useCallback(
    (summary: ReconciliationSummary) => {
      navigate(`/accounting/bank-accounts/${summary.bank_account_id}/transactions`)
    },
    [navigate],
  )

  // Totals
  const totalUnreconciled = items.reduce(
    (sum, s) => sum + (s.unreconciled_count ?? 0),
    0,
  )
  const totalAmount = items.reduce(
    (sum, s) => sum + (s.unreconciled_amount ?? 0),
    0,
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Reconciliation
        </h1>

        {/* Summary card */}
        <MobileCard>
          <div className="flex justify-between">
            <div>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Unreconciled Items
              </p>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                {totalUnreconciled}
              </p>
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Total Amount
              </p>
              <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                {formatCurrency(totalAmount)}
              </p>
            </div>
          </div>
        </MobileCard>

        {/* Per-account breakdown */}
        {isLoading ? (
          <div className="flex justify-center py-8">
            <MobileSpinner size="md" />
          </div>
        ) : items.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
            No bank accounts to reconcile
          </p>
        ) : (
          <div className="flex flex-col">
            {items.map((summary) => (
              <MobileListItem
                key={summary.id}
                title={summary.bank_account_name ?? 'Bank Account'}
                subtitle={`Last reconciled: ${formatDate(summary.last_reconciled_date)}`}
                trailing={
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {formatCurrency(summary.unreconciled_amount)}
                    </span>
                    <span className="text-xs text-amber-600 dark:text-amber-400">
                      {summary.unreconciled_count ?? 0} items
                    </span>
                  </div>
                }
                onTap={() => handleTap(summary)}
              />
            ))}
          </div>
        )}
      </div>
    </PullRefresh>
  )
}
