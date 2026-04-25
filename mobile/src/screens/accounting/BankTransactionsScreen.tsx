import { useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import type { BankTransaction } from '@shared/types/accounting'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileBadge } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
    })
  } catch {
    return dateStr
  }
}

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

/**
 * Bank transactions screen — paginated transaction list for a bank account.
 * Pull-to-refresh.
 *
 * Requirements: 25.2, 25.4
 */
export default function BankTransactionsScreen() {
  const { accountId } = useParams<{ accountId: string }>()
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<BankTransaction>({
    endpoint: `/api/v1/banking/accounts/${accountId}/transactions`,
    dataKey: 'items',
  })

  const renderItem = useCallback(
    (txn: BankTransaction) => {
      const amount = txn.amount ?? 0
      const isCredit = amount >= 0

      return (
        <MobileListItem
          title={txn.description ?? 'Transaction'}
          subtitle={formatDate(txn.date)}
          trailing={
            <div className="flex flex-col items-end gap-1">
              <span
                className={`text-sm font-semibold ${
                  isCredit
                    ? 'text-green-600 dark:text-green-400'
                    : 'text-red-600 dark:text-red-400'
                }`}
              >
                {isCredit ? '+' : ''}{formatCurrency(amount)}
              </span>
              <MobileBadge
                label={txn.is_reconciled ? 'Reconciled' : 'Unreconciled'}
                variant={txn.is_reconciled ? 'paid' : 'draft'}
              />
            </div>
          }
        />
      )
    },
    [],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        <div className="flex items-center gap-2 px-4 pb-1 pt-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="flex min-h-[44px] items-center gap-1 text-blue-600 dark:text-blue-400"
            aria-label="Back"
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="m15 18-6-6 6-6" />
            </svg>
          </button>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Transactions
          </h1>
        </div>

        <MobileList<BankTransaction>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No transactions found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search transactions…"
          keyExtractor={(t) => t.id}
        />
      </div>
    </PullRefresh>
  )
}
