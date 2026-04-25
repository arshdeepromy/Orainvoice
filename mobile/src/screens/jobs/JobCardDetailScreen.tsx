import { useNavigate, useParams } from 'react-router-dom'
import type { JobCard, JobStatus } from '@shared/types/job'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileBadge, MobileSpinner, MobileCard } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

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
 * Job card detail screen — vehicle info, service items, parts, labour, status.
 *
 * Requirements: 11.2
 */
export default function JobCardDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: card, isLoading, error } = useApiDetail<JobCard>({
    endpoint: `/api/v1/job-cards/${id}`,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !card) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Job card not found'}
      </div>
    )
  }

  const status = card.status ?? 'pending'

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
            {card.job_card_number ?? 'Job Card'}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {card.customer_name ?? 'Unknown Customer'}
          </p>
        </div>
        <MobileBadge
          label={statusLabels[status] ?? status}
          variant={statusVariantMap[status] ?? 'info'}
        />
      </div>

      {/* Vehicle info */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Vehicle
        </h2>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Registration</span>
            <span className="text-gray-900 dark:text-gray-100">
              {card.vehicle_registration ?? '—'}
            </span>
          </div>
        </div>
      </MobileCard>

      {/* Description / Service items */}
      {card.description && (
        <MobileCard>
          <h2 className="mb-1 text-base font-semibold text-gray-900 dark:text-gray-100">
            Service Description
          </h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            {card.description}
          </p>
        </MobileCard>
      )}

      {/* Dates */}
      <MobileCard>
        <div className="flex justify-between text-sm">
          <div>
            <span className="text-gray-500 dark:text-gray-400">Created</span>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(card.created_at)}
            </p>
          </div>
        </div>
      </MobileCard>
    </div>
  )
}
