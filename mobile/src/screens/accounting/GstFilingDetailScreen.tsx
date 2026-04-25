import { useParams, useNavigate } from 'react-router-dom'
import type { GstPeriod } from '@shared/types/accounting'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileButton, MobileSpinner, MobileBadge } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

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

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

const statusVariant: Record<GstPeriod['status'], 'draft' | 'info' | 'paid'> = {
  open: 'draft',
  filed: 'info',
  paid: 'paid',
}

/**
 * GST filing detail screen — GST collected vs GST paid breakdown.
 *
 * Requirements: 26.2
 */
export default function GstFilingDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: period, isLoading, error } = useApiDetail<GstPeriod>({
    endpoint: `/api/v1/gst/periods/${id}`,
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !period) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">
          {error ?? 'GST period not found'}
        </p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  const netGst = period.net_gst ?? 0
  const isRefund = netGst < 0

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
            GST Filing
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {formatDate(period.start_date)} – {formatDate(period.end_date)}
          </p>
        </div>
        <MobileBadge
          label={(period.status ?? 'open').charAt(0).toUpperCase() + (period.status ?? 'open').slice(1)}
          variant={statusVariant[period.status] ?? 'draft'}
        />
      </div>

      {/* GST breakdown */}
      <MobileCard>
        <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
          GST Breakdown
        </h2>
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">GST Collected (Sales)</span>
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {formatCurrency(period.gst_collected)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">GST Paid (Purchases)</span>
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {formatCurrency(period.gst_paid)}
            </span>
          </div>
          <div className="flex justify-between border-t border-gray-200 pt-3 dark:border-gray-600">
            <span className="font-semibold text-gray-900 dark:text-gray-100">
              {isRefund ? 'GST Refund Due' : 'GST Payable'}
            </span>
            <span
              className={`font-semibold ${
                isRefund
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400'
              }`}
            >
              {formatCurrency(Math.abs(netGst))}
            </span>
          </div>
        </div>
      </MobileCard>
    </div>
  )
}
