import { useNavigate, useParams } from 'react-router-dom'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileBadge, MobileSpinner } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'

interface PODetail {
  id: string
  po_number: string
  supplier_name: string | null
  supplier_email: string | null
  supplier_phone: string | null
  amount: number
  status: string
  delivery_status: string | null
  expected_delivery: string | null
  created_at: string
  notes: string | null
  line_items: POLineItem[]
}

interface POLineItem {
  id: string
  description: string
  quantity: number
  unit_price: number
  amount: number
  received_quantity: number | null
}

const statusVariant: Record<string, BadgeVariant> = {
  draft: 'draft',
  sent: 'sent',
  received: 'paid',
  partial: 'info',
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
 * Purchase order detail — line items, supplier details, delivery status.
 *
 * Requirements: 35.2
 */
export default function PODetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading, error } = useApiDetail<PODetail>({
    endpoint: `/api/v2/purchase-orders/${id}`,
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
        {error ?? 'Purchase order not found'}
      </div>
    )
  }

  const lineItems: POLineItem[] = data.line_items ?? []
  const status = data.status ?? 'draft'

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
            {data.po_number ?? 'Purchase Order'}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {data.supplier_name ?? 'Unknown Supplier'}
          </p>
        </div>
        <MobileBadge
          label={status.charAt(0).toUpperCase() + status.slice(1)}
          variant={statusVariant[status] ?? 'info'}
        />
      </div>

      {/* Supplier details */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">Supplier</h2>
        <div className="flex flex-col gap-1 text-sm">
          <p className="text-gray-900 dark:text-gray-100">{data.supplier_name ?? 'N/A'}</p>
          {data.supplier_email && (
            <p className="text-gray-500 dark:text-gray-400">{data.supplier_email}</p>
          )}
          {data.supplier_phone && (
            <p className="text-gray-500 dark:text-gray-400">{data.supplier_phone}</p>
          )}
        </div>
      </MobileCard>

      {/* Delivery */}
      <MobileCard>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Created</span>
            <span className="text-gray-900 dark:text-gray-100">{formatDate(data.created_at)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Expected Delivery</span>
            <span className="text-gray-900 dark:text-gray-100">{formatDate(data.expected_delivery)}</span>
          </div>
          {data.delivery_status && (
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Delivery Status</span>
              <span className="capitalize text-gray-900 dark:text-gray-100">{data.delivery_status}</span>
            </div>
          )}
        </div>
      </MobileCard>

      {/* Line items */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">Line Items</h2>
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
                  {li.received_quantity != null && ` · Received: ${li.received_quantity}`}
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
            {formatCurrency(data.amount)}
          </span>
        </div>
      </MobileCard>

      {/* Notes */}
      {data.notes && (
        <MobileCard>
          <h2 className="mb-1 text-base font-semibold text-gray-900 dark:text-gray-100">Notes</h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">{data.notes}</p>
        </MobileCard>
      )}
    </div>
  )
}
