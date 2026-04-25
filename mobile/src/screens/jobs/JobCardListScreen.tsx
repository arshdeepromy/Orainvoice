import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { JobCard } from '@shared/types/job'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileButton, MobileBadge } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'
import type { JobStatus } from '@shared/types/job'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

const statusVariantMap: Record<JobStatus, BadgeVariant> = {
  pending: 'draft',
  in_progress: 'sent',
  completed: 'paid',
  cancelled: 'cancelled',
}

const statusLabels: Record<JobStatus, string> = {
  pending: 'Pending',
  in_progress: 'In Progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

/**
 * Job card list screen — searchable list with job card number, customer,
 * vehicle registration, status. Pull-to-refresh. Wrapped in ModuleGate
 * for jobs module + automotive-transport trade family.
 *
 * Requirements: 11.1, 11.4
 */
export default function JobCardListScreen() {
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
  } = useApiList<JobCard>({
    endpoint: '/api/v1/job-cards',
    dataKey: 'job_cards',
  })

  const handleTap = useCallback(
    (card: JobCard) => {
      navigate(`/job-cards/${card.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (card: JobCard) => {
      const status = card.status ?? 'pending'

      return (
        <MobileListItem
          title={card.job_card_number ?? 'No Number'}
          subtitle={`${card.customer_name ?? 'Unknown'} · ${card.vehicle_registration ?? 'No Reg'}`}
          trailing={
            <MobileBadge
              label={statusLabels[status] ?? status}
              variant={statusVariantMap[status] ?? 'info'}
            />
          }
          onTap={() => handleTap(card)}
        />
      )
    },
    [handleTap],
  )

  return (
    <ModuleGate moduleSlug="jobs" tradeFamily="automotive-transport">
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-4 pb-1 pt-4">
            <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              Job Cards
            </h1>
            <MobileButton
              variant="primary"
              size="sm"
              onClick={() => navigate('/job-cards/new')}
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

          {/* Paginated list with search */}
          <MobileList<JobCard>
            items={items}
            renderItem={renderItem}
            onRefresh={refresh}
            onLoadMore={loadMore}
            isLoading={isLoading}
            isRefreshing={isRefreshing}
            hasMore={hasMore}
            emptyMessage="No job cards found"
            searchValue={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search job cards…"
            keyExtractor={(c) => c.id}
          />
        </div>
      </PullRefresh>
    </ModuleGate>
  )
}
