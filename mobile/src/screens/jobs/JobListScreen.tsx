import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Job, JobStatus } from '@shared/types/job'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileButton, MobileBadge, MobileSelect } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

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

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
]

/**
 * Job list screen — list view with status filters, toggle to board view.
 * Pull-to-refresh. Wrapped in ModuleGate for jobs module.
 *
 * Requirements: 10.1, 10.5
 */
export default function JobListScreen() {
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState('')

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
    setFilters,
  } = useApiList<Job>({
    endpoint: '/api/v2/jobs',
    dataKey: 'jobs',
    initialFilters: statusFilter ? { status: statusFilter } : {},
  })

  const handleStatusChange = useCallback(
    (value: string) => {
      setStatusFilter(value)
      if (value) {
        setFilters({ status: value })
      } else {
        setFilters({})
      }
    },
    [setFilters],
  )

  const handleTap = useCallback(
    (job: Job) => {
      navigate(`/jobs/${job.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (job: Job) => {
      const status = job.status ?? 'pending'

      return (
        <MobileListItem
          title={job.title ?? 'Untitled Job'}
          subtitle={`${job.customer_name ?? 'Unknown'} · ${job.assigned_staff_name ?? 'Unassigned'}`}
          trailing={
            <MobileBadge
              label={statusLabels[status] ?? status}
              variant={statusVariantMap[status] ?? 'info'}
            />
          }
          onTap={() => handleTap(job)}
        />
      )
    },
    [handleTap],
  )

  return (
    <ModuleGate moduleSlug="jobs">
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-4 pb-1 pt-4">
            <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              Jobs
            </h1>
            <div className="flex gap-2">
              <MobileButton
                variant="secondary"
                size="sm"
                onClick={() => navigate('/jobs/board')}
              >
                Board
              </MobileButton>
              <MobileButton
                variant="primary"
                size="sm"
                onClick={() => navigate('/jobs/new')}
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
          </div>

          {/* Status filter */}
          <div className="px-4 pb-2">
            <MobileSelect
              label=""
              options={STATUS_OPTIONS}
              value={statusFilter}
              onChange={(e) => handleStatusChange(e.target.value)}
            />
          </div>

          {/* Paginated list with search */}
          <MobileList<Job>
            items={items}
            renderItem={renderItem}
            onRefresh={refresh}
            onLoadMore={loadMore}
            isLoading={isLoading}
            isRefreshing={isRefreshing}
            hasMore={hasMore}
            emptyMessage="No jobs found"
            searchValue={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search jobs…"
            keyExtractor={(j) => j.id}
          />
        </div>
      </PullRefresh>
    </ModuleGate>
  )
}
