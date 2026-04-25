import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileCard, MobileBadge, MobileSearchBar, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface PurchaseOrder {
  id: string
  po_number: string
  supplier_name: string | null
  amount: number
  status: string
  created_at: string
}

const statusVariant: Record<string, BadgeVariant> = {
  draft: 'draft',
  sent: 'sent',
  received: 'paid',
  partial: 'info',
  cancelled: 'cancelled',
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

function POListContent() {
  const navigate = useNavigate()
  const { items, isLoading, isRefreshing, search, setSearch, refresh, hasMore, loadMore } =
    useApiList<PurchaseOrder>({ endpoint: '/api/v2/purchase-orders', dataKey: 'items' })

  if (isLoading && items.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Purchase Orders</h1>
      <MobileSearchBar value={search} onChange={setSearch} placeholder="Search POs..." />
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <MobileList
          items={items}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          onRefresh={refresh}
          onLoadMore={loadMore}
          emptyMessage="No purchase orders found"
          renderItem={(po) => (
            <MobileCard
              key={po.id}
              onClick={() => navigate(`/purchase-orders/${po.id}`)}
              className="cursor-pointer"
            >
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {po.po_number ?? 'PO'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {po.supplier_name ?? 'Unknown Supplier'}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {formatCurrency(po.amount)}
                  </span>
                  <MobileBadge
                    label={(po.status ?? 'draft').charAt(0).toUpperCase() + (po.status ?? 'draft').slice(1)}
                    variant={statusVariant[po.status] ?? 'info'}
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
 * Purchase order list — PO number, supplier, amount, status.
 *
 * Requirements: 35.1, 35.3
 */
export default function POListScreen() {
  return (
    <ModuleGate moduleSlug="purchase_orders">
      <POListContent />
    </ModuleGate>
  )
}
