import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileCard, MobileBadge, MobileSearchBar, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface RecurringInvoice {
  id: string
  customer_name: string | null
  amount: number
  frequency: string
  next_run_date: string | null
  status: string
}

const statusVariant: Record<string, BadgeVariant> = {
  active: 'paid',
  paused: 'draft',
  cancelled: 'cancelled',
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'N/A'
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

function RecurringListContent() {
  const navigate = useNavigate()
  const { items, isLoading, isRefreshing, search, setSearch, refresh, hasMore, loadMore } =
    useApiList<RecurringInvoice>({ endpoint: '/api/v2/recurring', dataKey: 'items' })

  if (isLoading && items.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Recurring Invoices</h1>
      <MobileSearchBar value={search} onChange={setSearch} placeholder="Search recurring..." />
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <MobileList
          items={items}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          onRefresh={refresh}
          onLoadMore={loadMore}
          emptyMessage="No recurring invoices found"
          renderItem={(r) => (
            <MobileCard
              key={r.id}
              onClick={() => navigate(`/recurring/${r.id}`)}
              className="cursor-pointer"
            >
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {r.customer_name ?? 'Unknown Customer'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {(r.frequency ?? 'monthly').charAt(0).toUpperCase() + (r.frequency ?? 'monthly').slice(1)} · Next: {formatDate(r.next_run_date)}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {formatCurrency(r.amount)}
                  </span>
                  <MobileBadge
                    label={(r.status ?? 'active').charAt(0).toUpperCase() + (r.status ?? 'active').slice(1)}
                    variant={statusVariant[r.status] ?? 'info'}
                  />
                </div>
              </div>
            </MobileCard>
          )}
        />
      </PullRefresh>
    </div>
  )
}

/**
 * Recurring invoice list — customer name, amount, frequency, next run date.
 *
 * Requirements: 34.1, 34.3
 */
export default function RecurringListScreen() {
  return (
    <ModuleGate moduleSlug="recurring_invoices">
      <RecurringListContent />
    </ModuleGate>
  )
}
