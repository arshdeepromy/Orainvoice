import { useNavigate, useParams } from 'react-router-dom'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileBadge, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

interface ConstructionItem {
  id: string
  type: 'claim' | 'variation'
  number: string
  project_name: string | null
  description: string | null
  amount: number
  status: string
  approval_status: string | null
  created_at: string
  line_items: ConstructionLineItem[]
}

interface ConstructionLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  amount: number
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
 * Construction detail screen — detail view for progress claims and variations
 * with full breakdown and approval status.
 *
 * Requirements: 32.4
 */
export default function ConstructionDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: item, isLoading, error } = useApiDetail<ConstructionItem>({
    endpoint: `/api/v2/progress-claims/${id}`,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !item) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Item not found'}
      </div>
    )
  }

  const status = item.status ?? 'draft'
  const lineItems: ConstructionLineItem[] = item.line_items ?? []

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {item.number ?? (item.type === 'claim' ? 'Progress Claim' : 'Variation')}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {item.project_name ?? 'No project'}
          </p>
        </div>
        <MobileBadge
          label={status.charAt(0).toUpperCase() + status.slice(1)}
          variant={statusVariant[status] ?? 'info'}
        />
      </div>

      {/* Details */}
      <MobileCard>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Type</span>
            <span className="font-medium capitalize text-gray-900 dark:text-gray-100">
              {item.type === 'claim' ? 'Progress Claim' : 'Variation'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Created</span>
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(item.created_at)}
            </span>
          </div>
          {item.approval_status && (
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Approval</span>
              <span className="font-medium capitalize text-gray-900 dark:text-gray-100">
                {item.approval_status}
              </span>
            </div>
          )}
        </div>
      </MobileCard>

      {/* Description */}
      {item.description && (
        <MobileCard>
          <h2 className="mb-1 text-base font-semibold text-gray-900 dark:text-gray-100">
            Description
          </h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">{item.description}</p>
        </MobileCard>
      )}

      {/* Line items breakdown */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Breakdown
        </h2>
        {lineItems.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No line items</p>
        ) : (
          lineItems.map((li) => (
            <div
              key={li.id}
              className="flex items-start justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm text-gray-900 dark:text-gray-100">
                  {li.description || 'Item'}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {li.quantity ?? 0} × {formatCurrency(li.unit_price)}
                </p>
              </div>
              <span className="ml-3 text-sm font-medium text-gray-900 dark:text-gray-100">
                {formatCurrency(li.amount)}
              </span>
            </div>
          ))
        )}
        <div className="mt-2 flex justify-between border-t border-gray-200 pt-2 dark:border-gray-600">
          <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
          <span className="font-semibold text-gray-900 dark:text-gray-100">
            {formatCurrency(item.amount)}
          </span>
        </div>
      </MobileCard>
    </div>
  )
}
