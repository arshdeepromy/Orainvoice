import { useState, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { Quote, QuoteLineItem } from '@shared/types/quote'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileButton, MobileBadge, MobileSpinner, MobileCard } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

const statusVariantMap: Record<Quote['status'], BadgeVariant> = {
  draft: 'draft',
  sent: 'sent',
  accepted: 'paid',
  declined: 'overdue',
  expired: 'cancelled',
}

function formatCurrency(amount: number): string {
  return `${Number(amount ?? 0).toFixed(2)}`
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

/* ------------------------------------------------------------------ */
/* Exported helpers for testing                                       */
/* ------------------------------------------------------------------ */

export async function sendQuote(quoteId: string): Promise<boolean> {
  try {
    await apiClient.post(`/api/v1/quotes/${quoteId}/send`)
    return true
  } catch {
    return false
  }
}

/**
 * Convert a quote to an invoice by POSTing to the backend.
 * Returns the new invoice ID on success, or null on failure.
 */
export async function convertQuoteToInvoice(quoteId: string): Promise<string | null> {
  try {
    const res = await apiClient.post<{ id?: string }>(`/api/v1/quotes/${quoteId}/convert`)
    return res.data?.id ?? null
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Line item row                                                      */
/* ------------------------------------------------------------------ */

function LineItemRow({ item }: { item: QuoteLineItem }) {
  const qty = item.quantity ?? 0
  const price = item.unit_price ?? 0
  const amount = item.amount ?? qty * price

  return (
    <div className="flex items-start justify-between border-b border-gray-100 py-3 last:border-b-0 dark:border-gray-700">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
          {item.description || 'Unnamed item'}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {qty} × {formatCurrency(price)}
          {item.tax_rate > 0 && ` · ${Number(item.tax_rate * 100).toFixed(0)}% tax`}
        </p>
      </div>
      <span className="ml-3 text-sm font-medium text-gray-900 dark:text-gray-100">
        {formatCurrency(amount)}
      </span>
    </div>
  )
}

/**
 * Quote detail screen — full quote with line items, totals.
 * Send and Convert to Invoice buttons.
 *
 * Requirements: 9.2, 9.4, 9.5
 */
export default function QuoteDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: quote, isLoading, error, refetch } = useApiDetail<Quote>({
    endpoint: `/api/v1/quotes/${id}`,
  })

  const [isSending, setIsSending] = useState(false)
  const [isConverting, setIsConverting] = useState(false)
  const [convertError, setConvertError] = useState<string | null>(null)

  const handleSend = useCallback(async () => {
    if (!id) return
    setIsSending(true)
    await sendQuote(id)
    setIsSending(false)
    await refetch()
  }, [id, refetch])

  const handleConvertToInvoice = useCallback(async () => {
    if (!id) return
    setIsConverting(true)
    setConvertError(null)
    const invoiceId = await convertQuoteToInvoice(id)
    setIsConverting(false)
    if (invoiceId) {
      navigate(`/invoices/${invoiceId}`, { replace: true })
    } else {
      setConvertError('Failed to convert quote to invoice')
    }
  }, [id, navigate])

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !quote) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Quote not found'}
      </div>
    )
  }

  const status = quote.status ?? 'draft'
  const lineItems: QuoteLineItem[] = quote.line_items ?? []

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
            {quote.quote_number ?? 'Quote'}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {quote.customer_name ?? 'Unknown Customer'}
          </p>
        </div>
        <MobileBadge
          label={status.charAt(0).toUpperCase() + status.slice(1)}
          variant={statusVariantMap[status] ?? 'info'}
        />
      </div>

      {/* Dates */}
      <MobileCard>
        <div className="flex justify-between text-sm">
          <div>
            <span className="text-gray-500 dark:text-gray-400">Created</span>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(quote.created_at)}
            </p>
          </div>
          <div className="text-right">
            <span className="text-gray-500 dark:text-gray-400">Valid Until</span>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(quote.valid_until)}
            </p>
          </div>
        </div>
      </MobileCard>

      {/* Line items */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Line Items
        </h2>
        {lineItems.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No line items</p>
        ) : (
          lineItems.map((item) => <LineItemRow key={item.id} item={item} />)
        )}
      </MobileCard>

      {/* Totals */}
      <MobileCard>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Subtotal</span>
            <span className="text-gray-900 dark:text-gray-100">
              {formatCurrency(quote.subtotal)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Tax</span>
            <span className="text-gray-900 dark:text-gray-100">
              {formatCurrency(quote.tax_amount)}
            </span>
          </div>
          {(quote.discount_amount ?? 0) > 0 && (
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Discount</span>
              <span className="text-red-600 dark:text-red-400">
                -{formatCurrency(quote.discount_amount)}
              </span>
            </div>
          )}
          <div className="flex justify-between border-t border-gray-200 pt-2 dark:border-gray-600">
            <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
            <span className="font-semibold text-gray-900 dark:text-gray-100">
              {formatCurrency(quote.total)}
            </span>
          </div>
        </div>
      </MobileCard>

      {/* Convert error */}
      {convertError && (
        <div
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          role="alert"
        >
          {convertError}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-col gap-3">
        {status === 'draft' && (
          <MobileButton
            variant="primary"
            fullWidth
            onClick={handleSend}
            isLoading={isSending}
          >
            Send Quote
          </MobileButton>
        )}
        {(status === 'sent' || status === 'accepted') && (
          <MobileButton
            variant="primary"
            fullWidth
            onClick={handleConvertToInvoice}
            isLoading={isConverting}
          >
            Convert to Invoice
          </MobileButton>
        )}
        <MobileButton
          variant="ghost"
          fullWidth
          onClick={async () => {
            const portalUrl = `${window.location.origin}/portal/quotes/${id}`
            try {
              const { Share } = await import('@capacitor/share')
              await Share.share({
                title: `Quote ${quote.quote_number ?? ''}`,
                text: `View quote ${quote.quote_number ?? ''} from ${quote.customer_name ?? 'us'}`,
                url: portalUrl,
              })
            } catch {
              // Fallback for browser: copy to clipboard
              try {
                await navigator.clipboard.writeText(portalUrl)
              } catch {
                // Ignore clipboard errors
              }
            }
          }}
        >
          Share Portal Link
        </MobileButton>
      </div>
    </div>
  )
}
