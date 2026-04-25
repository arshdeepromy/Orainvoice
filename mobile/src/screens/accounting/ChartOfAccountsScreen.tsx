import { useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Account, AccountType } from '@shared/types/accounting'
import { useApiList } from '@/hooks/useApiList'
import { MobileListItem, MobileBadge, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

const typeVariant: Record<AccountType, 'active' | 'info' | 'paid' | 'overdue' | 'draft'> = {
  asset: 'active',
  liability: 'overdue',
  equity: 'info',
  revenue: 'paid',
  expense: 'draft',
}

function typeLabel(type: AccountType): string {
  return (type ?? 'asset').charAt(0).toUpperCase() + (type ?? 'asset').slice(1)
}

/**
 * Chart of Accounts screen — hierarchical list with account code, name,
 * type, balance. Tap to view account detail with recent journal entries.
 * Pull-to-refresh. Wrapped in ModuleGate at the route level.
 *
 * Requirements: 23.1, 23.2, 23.3
 */
export default function ChartOfAccountsScreen() {
  const navigate = useNavigate()
  const [expandedTypes, setExpandedTypes] = useState<Set<AccountType>>(
    new Set(['asset', 'liability', 'equity', 'revenue', 'expense']),
  )

  const {
    items: accounts,
    isLoading,
    isRefreshing,
    refresh,
  } = useApiList<Account>({
    endpoint: '/api/v1/ledger/accounts',
    dataKey: 'items',
    pageSize: 200,
  })

  // Group accounts by type
  const groupedAccounts = useMemo(() => {
    const groups: Record<AccountType, Account[]> = {
      asset: [],
      liability: [],
      equity: [],
      revenue: [],
      expense: [],
    }
    for (const account of accounts) {
      const type = account.type ?? 'asset'
      if (groups[type]) {
        groups[type].push(account)
      }
    }
    return groups
  }, [accounts])

  const toggleType = useCallback((type: AccountType) => {
    setExpandedTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) {
        next.delete(type)
      } else {
        next.add(type)
      }
      return next
    })
  }, [])

  const handleTap = useCallback(
    (account: Account) => {
      navigate(`/accounting/journal-entries?account_id=${account.id}`)
    },
    [navigate],
  )

  const accountTypes: AccountType[] = ['asset', 'liability', 'equity', 'revenue', 'expense']

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-2 p-4">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Chart of Accounts
        </h1>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <MobileSpinner size="md" />
          </div>
        ) : (
          accountTypes.map((type) => {
            const typeAccounts = groupedAccounts[type]
            const isExpanded = expandedTypes.has(type)
            const totalBalance = typeAccounts.reduce(
              (sum, a) => sum + (a.balance ?? 0),
              0,
            )

            return (
              <div key={type}>
                {/* Type header */}
                <button
                  type="button"
                  onClick={() => toggleType(type)}
                  className="flex min-h-[44px] w-full items-center justify-between rounded-lg bg-gray-50 px-4 py-3 dark:bg-gray-800"
                  aria-expanded={isExpanded}
                >
                  <div className="flex items-center gap-2">
                    <svg
                      className={`h-4 w-4 text-gray-500 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      aria-hidden="true"
                    >
                      <path d="m9 18 6-6-6-6" />
                    </svg>
                    <MobileBadge
                      label={typeLabel(type)}
                      variant={typeVariant[type]}
                    />
                    <span className="text-xs text-gray-400 dark:text-gray-500">
                      ({typeAccounts.length})
                    </span>
                  </div>
                  <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {formatCurrency(totalBalance)}
                  </span>
                </button>

                {/* Account list */}
                {isExpanded && (
                  <div className="ml-2 border-l-2 border-gray-100 dark:border-gray-700">
                    {typeAccounts.length === 0 ? (
                      <p className="py-3 pl-4 text-sm text-gray-400 dark:text-gray-500">
                        No accounts
                      </p>
                    ) : (
                      typeAccounts.map((account) => (
                        <MobileListItem
                          key={account.id}
                          title={`${account.code ?? ''} ${account.name ?? 'Unnamed'}`}
                          trailing={
                            <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                              {formatCurrency(account.balance)}
                            </span>
                          }
                          onTap={() => handleTap(account)}
                        />
                      ))
                    )}
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </PullRefresh>
  )
}
