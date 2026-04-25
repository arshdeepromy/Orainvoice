import { useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { Job, TimeEntry } from '@shared/types/job'
import { useApiDetail } from '@/hooks/useApiDetail'
import { useApiList } from '@/hooks/useApiList'
import { useTimer, formatElapsedTime } from '@/hooks/useTimer'
import {
  MobileButton,
  MobileBadge,
  MobileSpinner,
  MobileCard,
  MobileSelect,
} from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

import type { JobStatus } from '@shared/types/job'

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
  { value: 'pending', label: 'Pending' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'cancelled', label: 'Cancelled' },
]

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

function formatDuration(minutes: number | null): string {
  if (minutes === null || minutes === undefined) return '—'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

/* ------------------------------------------------------------------ */
/* Exported helpers for testing                                       */
/* ------------------------------------------------------------------ */

export async function updateJobStatus(
  jobId: string,
  status: string,
): Promise<boolean> {
  try {
    await apiClient.patch(`/api/v2/jobs/${jobId}`, { status })
    return true
  } catch {
    return false
  }
}

/**
 * Job detail screen — description, status, assigned staff, time entries,
 * linked invoices. Status change dropdown. Timer button for time tracking.
 *
 * Requirements: 10.2, 10.3, 10.4
 */
export default function JobDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: job, isLoading, error, refetch } = useApiDetail<Job>({
    endpoint: `/api/v2/jobs/${id}`,
  })

  const { items: timeEntries } = useApiList<TimeEntry>({
    endpoint: `/api/v2/time-entries`,
    dataKey: 'items',
    pageSize: 50,
    initialFilters: { job_id: id ?? '' },
  })

  const timer = useTimer({ jobId: id ?? '' })

  const handleStatusChange = useCallback(
    async (newStatus: string) => {
      if (!id || !newStatus) return
      await updateJobStatus(id, newStatus)
      await refetch()
    },
    [id, refetch],
  )

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !job) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Job not found'}
      </div>
    )
  }

  const status = job.status ?? 'pending'

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {job.title ?? 'Untitled Job'}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {job.customer_name ?? 'Unknown Customer'}
          </p>
        </div>
        <MobileBadge
          label={statusLabels[status] ?? status}
          variant={statusVariantMap[status] ?? 'info'}
        />
      </div>

      {/* Description */}
      {job.description && (
        <MobileCard>
          <h2 className="mb-1 text-base font-semibold text-gray-900 dark:text-gray-100">
            Description
          </h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            {job.description}
          </p>
        </MobileCard>
      )}

      {/* Details */}
      <MobileCard>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Assigned To</span>
            <span className="text-gray-900 dark:text-gray-100">
              {job.assigned_staff_name ?? 'Unassigned'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Created</span>
            <span className="text-gray-900 dark:text-gray-100">
              {formatDate(job.created_at)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Updated</span>
            <span className="text-gray-900 dark:text-gray-100">
              {formatDate(job.updated_at)}
            </span>
          </div>
        </div>
      </MobileCard>

      {/* Status change */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Change Status
        </h2>
        <MobileSelect
          label=""
          options={STATUS_OPTIONS}
          value={status}
          onChange={(e) => handleStatusChange(e.target.value)}
        />
      </MobileCard>

      {/* Timer */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Time Tracking
        </h2>
        <div className="flex items-center justify-between">
          <div className="text-2xl font-mono text-gray-900 dark:text-gray-100" aria-label="Timer display">
            {formatElapsedTime(timer.elapsedSeconds)}
          </div>
          {timer.isRunning ? (
            <MobileButton
              variant="danger"
              size="sm"
              onClick={timer.stop}
              isLoading={timer.isLoading}
            >
              Stop
            </MobileButton>
          ) : (
            <MobileButton
              variant="primary"
              size="sm"
              onClick={timer.start}
              isLoading={timer.isLoading}
            >
              Start Timer
            </MobileButton>
          )}
        </div>
        {timer.error && (
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">{timer.error}</p>
        )}
      </MobileCard>

      {/* Time entries */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Time Entries
        </h2>
        {timeEntries.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No time entries</p>
        ) : (
          <div className="flex flex-col gap-2">
            {timeEntries.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {entry.staff_name ?? 'Unknown'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {formatDate(entry.clock_in)}
                    {entry.clock_out && ` — ${formatDate(entry.clock_out)}`}
                  </p>
                </div>
                <span className="text-sm text-gray-700 dark:text-gray-300">
                  {formatDuration(entry.duration_minutes)}
                </span>
              </div>
            ))}
          </div>
        )}
      </MobileCard>
    </div>
  )
}
