import { useState, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import type { Invoice, InvoiceLineItem } from '@shared/types/invoice'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileButton, MobileBadge, MobileSpinner, MobileCard, MobileInput, MobileToast } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

const statusVariantMap: Record<Invoice['status'], BadgeVariant> = {
  draft: 'draft',
  sent: 'sent',
  paid: 'paid',
  overdue: 'overdue',
  cancelled: 'cancelled',
}

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
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

export async function sendInvoice(invoiceId: string): Promise<boolean> {
  try {
    await apiClient.post(`/api/v1/invoices/${invoiceId}/send`)
    return true
  } catch {
    return false
  }
}

export async function recordPayment(
  invoiceId: string,
  amount: number,
): Promise<boolean> {
  try {
    await apiClient.post(`/api/v1/invoices/${invoiceId}/payments`, { amount })
    return true
  } catch {
    return false
  }
}

/* ------------------------------------------------------------------ */
/* Line item row                                                      */
/* ------------------------------------------------------------------ */

function LineItemRow({ item }: { item: InvoiceLineItem }) {
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

/* ------------------------------------------------------------------ */
/* Record Payment Modal (inline)                                      */
/* ------------------------------------------------------------------ */

function RecordPaymentForm({
  invoiceId,
  amountDue,
  onSuccess,
  onCancel,
}: {
  invoiceId: string
  amountDue: number
  onSuccess: () => void
  onCancel: () => void
}) {
  const [amount, setAmount] = useState(Number(amountDue ?? 0).toFixed(2))
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    const parsed = parseFloat(amount)
    if (isNaN(parsed) || parsed <= 0) {
      setError('Enter a valid amount')
      return
    }
    setIsSubmitting(true)
    setError(null)
    const ok = await recordPayment(invoiceId, parsed)
    setIsSubmitting(false)
    if (ok) {
      onSuccess()
    } else {
      setError('Failed to record payment')
    }
  }

  return (
    <MobileCard className="mt-4">
      <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
        Record Payment
      </h3>
      <MobileInput
        label="Amount"
        type="number"
        step="0.01"
        min="0"
        value={amount}
        onChange={(e) => {
          setAmount(e.target.value)
          setError(null)
        }}
        error={error ?? undefined}
        placeholder="0.00"
      />
      <div className="mt-4 flex gap-3">
        <MobileButton
          variant="secondary"
          size="sm"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          Cancel
        </MobileButton>
        <MobileButton
          variant="primary"
          size="sm"
          onClick={handleSubmit}
          isLoading={isSubmitting}
        >
          Record
        </MobileButton>
      </div>
    </MobileCard>
  )
}

/**
 * Invoice detail screen — full invoice with line items, totals, tax,
 * payment history. Send, Record Payment, Preview PDF buttons.
 *
 * Requirements: 8.2, 8.4, 8.5, 8.7
 */
export default function InvoiceDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const { data: invoice, isLoading, error, refetch } = useApiDetail<Invoice>({
    endpoint: `/api/v1/invoices/${id}`,
  })

  const [isSending, setIsSending] = useState(false)
  const [showPaymentForm, setShowPaymentForm] = useState(
    searchParams.get('action') === 'record-payment',
  )
  const [toast, setToast] = useState<{ message: string; variant: 'success' | 'error' } | null>(null)

  const handleSend = useCallback(async () => {
    if (!id) return
    setIsSending(true)
    const ok = await sendInvoice(id)
    setIsSending(false)
    if (ok) {
      setToast({ message: 'Invoice sent', variant: 'success' })
      await refetch()
    } else {
      setToast({ message: 'Failed to send invoice', variant: 'error' })
    }
  }, [id, refetch])

  const handlePaymentSuccess = useCallback(async () => {
    setShowPaymentForm(false)
    setToast({ message: 'Payment recorded', variant: 'success' })
    await refetch()
  }, [refetch])

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !invoice) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Invoice not found'}
      </div>
    )
  }

  const status = invoice.status ?? 'draft'
  const lineItems: InvoiceLineItem[] = invoice.line_items ?? []

  return (
    <div className="flex flex-col gap-4 p-4">
      <MobileToast
        message={toast?.message ?? ''}
        variant={toast?.variant ?? 'info'}
        isVisible={toast !== null}
        onDismiss={() => setToast(null)}
      />
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
            {invoice.invoice_number ?? 'Invoice'}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {invoice.customer_name ?? 'Unknown Customer'}
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
              {formatDate(invoice.created_at)}
            </p>
          </div>
          <div className="text-right">
            <span className="text-gray-500 dark:text-gray-400">Due</span>
            <p className="font-medium text-gray-900 dark:text-gray-100">
              {formatDate(invoice.due_date)}
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
              {formatCurrency(invoice.subtotal)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Tax</span>
            <span className="text-gray-900 dark:text-gray-100">
              {formatCurrency(invoice.tax_amount)}
            </span>
          </div>
          {(invoice.discount_amount ?? 0) > 0 && (
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Discount</span>
              <span className="text-red-600 dark:text-red-400">
                -{formatCurrency(invoice.discount_amount)}
              </span>
            </div>
          )}
          <div className="flex justify-between border-t border-gray-200 pt-2 dark:border-gray-600">
            <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
            <span className="font-semibold text-gray-900 dark:text-gray-100">
              {formatCurrency(invoice.total)}
            </span>
          </div>
        </div>
      </MobileCard>

      {/* Payment summary */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Payment History
        </h2>
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Amount Paid</span>
            <span className="text-green-600 dark:text-green-400">
              {formatCurrency(invoice.amount_paid)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Amount Due</span>
            <span className="font-semibold text-gray-900 dark:text-gray-100">
              {formatCurrency(invoice.amount_due)}
            </span>
          </div>
        </div>
      </MobileCard>

      {/* Record Payment form (inline) */}
      {showPaymentForm && (
        <RecordPaymentForm
          invoiceId={invoice.id}
          amountDue={invoice.amount_due ?? 0}
          onSuccess={handlePaymentSuccess}
          onCancel={() => setShowPaymentForm(false)}
        />
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
            Send Invoice
          </MobileButton>
        )}
        {status !== 'paid' && status !== 'cancelled' && !showPaymentForm && (
          <MobileButton
            variant="secondary"
            fullWidth
            onClick={() => setShowPaymentForm(true)}
          >
            Record Payment
          </MobileButton>
        )}
        <MobileButton
          variant="ghost"
          fullWidth
          onClick={() => navigate(`/invoices/${id}/pdf`)}
        >
          Preview PDF
        </MobileButton>
        <MobileButton
          variant="ghost"
          fullWidth
          onClick={async () => {
            const portalUrl = `${window.location.origin}/portal/invoices/${id}`
            try {
              const { Share } = await import('@capacitor/share')
              await Share.share({
                title: `Invoice ${invoice.invoice_number ?? ''}`,
                text: `View invoice ${invoice.invoice_number ?? ''} from ${invoice.customer_name ?? 'us'}`,
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
