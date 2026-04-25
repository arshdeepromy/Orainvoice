import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileCard, MobileBadge, MobileSearchBar, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface StockTransfer {
  id: string
  transfer_number: string
  source_name: string | null
  destination_name: string | null
  status: string
  item_count: number
  created_at: string
}

const statusVariant: Record<string, BadgeVariant> = {
  pending: 'draft',
  in_transit: 'sent',
  completed: 'paid',
  cancelled: 'cancelled',
}

function StockTransferListContent() {
  const { items, isLoading, isRefreshing, search, setSearch, refresh, hasMore, loadMore } =
    useApiList<StockTransfer>({ endpoint: '/api/v2/stock-transfers', dataKey: 'items' })

  if (isLoading && items.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Stock Transfers</h1>
      <MobileSearchBar value={search} onChange={setSearch} placeholder="Search transfers..." />
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <MobileList
          items={items}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          onRefresh={refresh}
          onLoadMore={loadMore}
          emptyMessage="No stock transfers found"
          renderItem={(t) => (
            <MobileCard key={t.id}>
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {t.transfer_number ?? 'Transfer'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {t.source_name ?? 'Source'} → {t.destination_name ?? 'Destination'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {t.item_count ?? 0} items
                  </p>
                </div>
                <MobileBadge
                  label={(t.status ?? 'pending').replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  variant={statusVariant[t.status] ?? 'info'}
                />
              </div>
            </MobileCard>
          )}
        />
      </PullRefresh>
    </div>
  )
}

/**
 * Stock transfer list — transfers with number, source, destination, status, item count.
 *
 * Requirements: 33.3
 */
export default function StockTransferListScreen() {
  return (
    <ModuleGate moduleSlug="franchise">
      <StockTransferListContent />
    </ModuleGate>
  )
}
