import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Expense } from '@shared/types/expense'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileButton } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
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
 * Expense list screen — list with date, description, amount, category.
 * Pull-to-refresh. Wrapped in ModuleGate at the route level.
 *
 * Requirements: 20.1, 20.6
 */
export default function ExpenseListScreen() {
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
  } = useApiList<Expense>({
    endpoint: '/api/v2/expenses',
    dataKey: 'items',
  })

  const renderItem = useCallback(
    (expense: Expense) => (
      <MobileListItem
        title={expense.description ?? 'Expense'}
        subtitle={`${formatDate(expense.date)}${expense.category ? ` · ${expense.category}` : ''}`}
        trailing={
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            {formatCurrency(expense.amount)}
          </span>
        }
      />
    ),
    [],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        <div className="flex items-center justify-between px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Expenses
          </h1>
          <MobileButton
            variant="primary"
            size="sm"
            onClick={() => navigate('/expenses/new')}
            icon={
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            }
          >
            New
          </MobileButton>
        </div>

        <MobileList<Expense>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No expenses found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search expenses…"
          keyExtractor={(e) => e.id}
        />
      </div>
    </PullRefresh>
  )
}
