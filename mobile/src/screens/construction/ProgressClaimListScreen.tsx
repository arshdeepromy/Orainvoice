import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileCard, MobileBadge, MobileSearchBar, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface ProgressClaim {
  id: string
  claim_number: string
  project_name: string | null
  amount: number
  status: string
  created_at: string
}

const statusVariant: Record<string, BadgeVariant> = {
  draft: 'draft',
  submitted: 'sent',
  approved: 'paid',
  rejected: 'overdue',
  certified: 'info',
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

function ProgressClaimListContent() {
  const navigate = useNavigate()
  const { items, isLoading, isRefreshing, search, setSearch, refresh, hasMore, loadMore } =
    useApiList<ProgressClaim>({ endpoint: '/api/v2/progress-claims', dataKey: 'items' })

  if (isLoading && items.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Progress Claims</h1>
      <MobileSearchBar value={search} onChange={setSearch} placeholder="Search claims..." />
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <MobileList
          items={items}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          onRefresh={refresh}
          onLoadMore={loadMore}
          emptyMessage="No progress claims found"
          renderItem={(claim) => (
            <MobileCard
              key={claim.id}
              onClick={() => navigate(`/construction/${claim.id}`)}
              className="cursor-pointer"
            >
              <div className="flex items-start justify-between">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {claim.claim_number ?? 'Claim'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {claim.project_name ?? 'No project'}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {formatCurrency(claim.amount)}
                  </span>
                  <MobileBadge
                    label={(claim.status ?? 'draft').charAt(0).toUpperCase() + (claim.status ?? 'draft').slice(1)}
                    variant={statusVariant[claim.status] ?? 'info'}
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
 * Progress Claim list screen — claims with number, project, amount, status.
 *
 * Requirements: 32.1, 32.5
 */
export default function ProgressClaimListScreen() {
  return (
    <ModuleGate moduleSlug="progress_claims">
      <ProgressClaimListContent />
    </ModuleGate>
  )
}
