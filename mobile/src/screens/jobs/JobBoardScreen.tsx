import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Job, JobStatus } from '@shared/types/job'
import { useApiList } from '@/hooks/useApiList'
import { MobileBadge, MobileCard, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { DragDrop } from '@/components/gestures/DragDrop'
import type { DragDropItem, DragDropColumnConfig } from '@/components/gestures/DragDrop'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

export interface BoardJob extends DragDropItem {
  title: string
  customerName: string
  assignedStaffName: string | null
}

/* ------------------------------------------------------------------ */
/* Helpers — exported for testing                                     */
/* ------------------------------------------------------------------ */

const BOARD_COLUMNS: DragDropColumnConfig[] = [
  { id: 'pending', label: 'Pending', color: 'bg-yellow-400' },
  { id: 'in_progress', label: 'In Progress', color: 'bg-blue-400' },
  { id: 'completed', label: 'Completed', color: 'bg-green-400' },
  { id: 'cancelled', label: 'Cancelled', color: 'bg-gray-400' },
]

const statusVariantMap: Record<JobStatus, BadgeVariant> = {
  pending: 'draft',
  in_progress: 'sent',
  completed: 'paid',
  cancelled: 'cancelled',
}

/**
 * Convert raw Job API data to BoardJob items for the DragDrop component.
 */
export function jobsToBoardItems(jobs: Job[]): BoardJob[] {
  return jobs.map((job) => ({
    id: job.id,
    columnId: job.status ?? 'pending',
    title: job.title ?? 'Untitled Job',
    customerName: job.customer_name ?? 'Unknown',
    assignedStaffName: job.assigned_staff_name ?? null,
  }))
}

/**
 * Update a job's status via the API.
 */
export async function updateJobStatus(
  jobId: string,
  newStatus: string,
): Promise<boolean> {
  try {
    await apiClient.patch(`/api/v2/jobs/${jobId}`, { status: newStatus })
    return true
  } catch {
    return false
  }
}

/**
 * Job board screen — kanban board with drag-drop columns.
 * Status update on column change.
 *
 * Requirements: 10.1, 10.6
 */
export default function JobBoardScreen() {
  const navigate = useNavigate()

  const {
    items: jobs,
    isLoading,
    isRefreshing,
    refresh,
  } = useApiList<Job>({
    endpoint: '/api/v2/jobs',
    dataKey: 'jobs',
    pageSize: 100,
  })

  const boardItems = jobsToBoardItems(jobs)

  const handleDrop = useCallback(
    async (itemId: string, _fromColumnId: string, toColumnId: string) => {
      await updateJobStatus(itemId, toColumnId)
      await refresh()
    },
    [refresh],
  )

  const renderItem = useCallback(
    (item: BoardJob, isDragging: boolean) => {
      const status = item.columnId as JobStatus

      return (
        <MobileCard
          className={`cursor-grab ${isDragging ? 'ring-2 ring-blue-400' : ''}`}
          onTap={() => navigate(`/jobs/${item.id}`)}
        >
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {item.title}
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {item.customerName}
            </p>
            {item.assignedStaffName && (
              <p className="text-xs text-gray-400 dark:text-gray-500">
                {item.assignedStaffName}
              </p>
            )}
            <MobileBadge
              label={status.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
              variant={statusVariantMap[status] ?? 'info'}
            />
          </div>
        </MobileCard>
      )
    },
    [navigate],
  )

  if (isLoading && jobs.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Job Board
          </h1>
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="flex min-h-[44px] items-center text-blue-600 dark:text-blue-400"
            aria-label="Back to list"
          >
            List View
          </button>
        </div>

        {/* Kanban board */}
        <DragDrop<BoardJob>
          columns={BOARD_COLUMNS}
          items={boardItems}
          renderItem={renderItem}
          onDrop={handleDrop}
        />
      </div>
    </PullRefresh>
  )
}
