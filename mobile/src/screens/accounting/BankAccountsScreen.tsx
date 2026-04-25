import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { BankAccount } from '@shared/types/accounting'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number, currency?: string): string {
  const code = currency ?? 'NZD'
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: code,
    minimumFractionDigits: 2,
  }).format(amount ?? 0)
}

/**
 * Bank accounts screen — list with account name, institution, balance.
 * Pull-to-refresh. Wrapped in ModuleGate at the route level.
 *
 * Requirements: 25.1, 25.4
 */
export default function BankAccountsScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    refresh,
    loadMore,
  } = useApiList<BankAccount>({
    endpoint: '/api/v1/banking/accounts',
    dataKey: 'items',
  })

  const handleTap = useCallback(
    (account: BankAccount) => {
      navigate(`/accounting/bank-accounts/${account.id}/transactions`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (account: BankAccount) => (
      <MobileListItem
        title={account.name ?? 'Bank Account'}
        subtitle={account.institution ?? undefined}
        trailing={
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            {formatCurrency(account.balance, account.currency)}
          </span>
        }
        onTap={() => handleTap(account)}
      />
    ),
    [handleTap],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        <div className="px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Bank Accounts
          </h1>
        </div>

        <MobileList<BankAccount>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No bank accounts found"
          keyExtractor={(a) => a.id}
        />
      </div>
    </PullRefresh>
  )
}
