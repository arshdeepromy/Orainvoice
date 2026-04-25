import { useNavigate, useParams } from 'react-router-dom'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileBadge, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

interface RecurringDetail {
  id: string
  customer_name: string | null
  amount: number
  frequency: string
  next_run_date: string | null
  status: string
  start_date: string | null
  end_date: string | null
  line_items: RecurringLineItem[]
  history: GenerationRecord[]
}

interface RecurringLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  amount: number
}

interface GenerationRecord {
  id: string
  invoice_number: string | null
  generated_at: string
  status: string
}

const statusVariant: Record<string, BadgeVariant> = {
  active: 'paid',
  paused: 'draft',
  cancelled: 'cancelled',
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'N/A'
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr ?? ''
  }
}

/**
 * Recurring invoice detail — template configuration and generation history.
 *
 * Requirements: 34.2
 */
export default function RecurringDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading, error } = useApiDetail<RecurringDetail>({
    endpoint: `/api/v2/recurring/${id}`,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Not found'}
      </div>
    )
  }

  const lineItems: RecurringLineItem[] = data.line_items ?? []
  const history: GenerationRecord[] = data.history ?? []
  const status = data.status ?? 'active'

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back */}
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
            Recurring Invoice
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {data.customer_name ?? 'Unknown Customer'}
          </p>
        </div>
        <MobileBadge
          label={status.charAt(0).toUpperCase() + status.slice(1)}
          variant={statusVariant[status] ?? 'info'}
        />
      </div>

      {/* Configuration */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Configuration
        </h2>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Frequency</span>
            <span className="font-medium capitalize text-gray-900 dark:text-gray-100">
              {data.frequency ?? 'monthly'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Amount</span>
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {formatCurrency(data.amount)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Next Run</span>
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(data.next_run_date)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Start</span>
            <span className="text-gray-900 dark:text-gray-100">{formatDate(data.start_date)}</span>
          </div>
          {data.end_date && (
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">End</span>
              <span className="text-gray-900 dark:text-gray-100">{formatDate(data.end_date)}</span>
            </div>
          )}
        </div>
      </MobileCard>

      {/* Line items */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Template Items
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
                <p className="text-sm text-gray-900 dark:text-gray-100">{li.description || 'Item'}</p>
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
      </MobileCard>

      {/* Generation history */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Generation History
        </h2>
        {history.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No invoices generated yet</p>
        ) : (
          history.map((h) => (
            <div
              key={h.id}
              className="flex items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700"
            >
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {h.invoice_number ?? 'Invoice'}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {formatDate(h.generated_at)}
                </p>
              </div>
              <span className="text-xs capitalize text-gray-500 dark:text-gray-400">
                {h.status ?? 'generated'}
              </span>
            </div>
          ))
        )}
      </MobileCard>
    </div>
  )
}
