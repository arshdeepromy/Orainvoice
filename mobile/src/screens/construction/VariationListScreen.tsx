import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileCard, MobileBadge, MobileSearchBar, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface Variation {
  id: string
  variation_number: string
  description: string | null
  amount: number
  status: string
  created_at: string
}

const statusVariant: Record<string, BadgeVariant> = {
  draft: 'draft',
  submitted: 'sent',
  approved: 'paid',
  rejected: 'overdue',
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

function VariationListContent() {
  const navigate = useNavigate()
  const { items, isLoading, isRefreshing, search, setSearch, refresh, hasMore, loadMore } =
    useApiList<Variation>({ endpoint: '/api/v2/variations', dataKey: 'items' })

  if (isLoading && items.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Variations</h1>
      <MobileSearchBar value={search} onChange={setSearch} placeholder="Search variations..." />
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <MobileList
          items={items}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          onRefresh={refresh}
          onLoadMore={loadMore}
          emptyMessage="No variations found"
          renderItem={(v) => (
            <MobileCard
              key={v.id}
              onClick={() => navigate(`/construction/${v.id}`)}
              className="cursor-pointer"
            >
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {v.variation_number ?? 'Variation'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-1">
                    {v.description ?? 'No description'}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {formatCurrency(v.amount)}
                  </span>
                  <MobileBadge
                    label={(v.status ?? 'draft').charAt(0).toUpperCase() + (v.status ?? 'draft').slice(1)}
                    variant={statusVariant[v.status] ?? 'info'}
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
 * Variation list screen — variations with number, description, amount, status.
 *
 * Requirements: 32.2, 32.5
 */
export default function VariationListScreen() {
  return (
    <ModuleGate moduleSlug="variations">
      <VariationListContent />
    </ModuleGate>
  )
}
