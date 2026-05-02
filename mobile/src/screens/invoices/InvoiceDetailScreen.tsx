import { useState, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Page,
  Card,
  Block,
  List,
  ListItem,
  Sheet,
  ListInput,
  Preloader,
  BlockTitle,
} from 'konsta/react'
import type { Invoice, InvoiceLineItem } from '@shared/types/invoice'
import { useApiDetail } from '@/hooks/useApiDetail'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import StatusBadge from '@/components/konsta/StatusBadge'
import HapticButton from '@/components/konsta/HapticButton'
import { useModules } from '@/contexts/ModuleContext'
import { buildPortalUrl, canSharePortalLink } from '@/utils/portalLink'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return ''
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

/* ------------------------------------------------------------------ */
/* Exported helpers for testing — preserved exactly                    */
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
/* Preserved helper logic — computeCreditableAmount                   */
/* ------------------------------------------------------------------ */

export function computeCreditableAmount(
  invoiceTotal: number,
  existingCreditNoteAmounts: number[],
): number {
  const sum = existingCreditNoteAmounts.reduce((acc, amt) => acc + amt, 0)
  return Math.max(0, invoiceTotal - sum)
}

/* ------------------------------------------------------------------ */
/* Preserved helper logic — computePaymentSummary                     */
/* ------------------------------------------------------------------ */

export function computePaymentSummary(
  payments: Array<{ amount: number | string; is_refund?: boolean }>,
): { totalPaid: number; totalRefunded: number; netPaid: number } {
  let totalPaid = 0
  let totalRefunded = 0
  for (const p of payments) {
    const amt =
      typeof p.amount === 'string' ? parseFloat(p.amount) || 0 : (p.amount || 0)
    if (p.is_refund) {
      totalRefunded += amt
    } else {
      totalPaid += amt
    }
  }
  return { totalPaid, totalRefunded, netPaid: totalPaid - totalRefunded }
}


/* ------------------------------------------------------------------ */
/* Extended invoice type for detail response fields                   */
/* ------------------------------------------------------------------ */

interface InvoiceDetail extends Invoice {
  vehicle_rego?: string | null
  vehicle_description?: string | null
  vehicles?: Array<{
    id?: string
    rego?: string
    make?: string
    model?: string
    year?: number
  }> | null
  shipping_charges?: number
  adjustment?: number
  discount_type?: 'percentage' | 'fixed'
  discount_value?: number
  payments?: Array<{
    id?: string
    amount: number | string
    method?: string
    date?: string
    is_refund?: boolean
    refund_note?: string | null
  }> | null
  credit_notes?: Array<{
    id?: string
    credit_note_number?: string
    amount: number
    reason?: string
    date?: string
  }> | null
  attachments?: Array<{
    id?: string
    filename?: string
    url?: string
    thumbnail_url?: string
  }> | null
  notes?: string | null
  internal_notes?: string | null
  customer_notes?: string | null
  balance_due?: number
}

/* ------------------------------------------------------------------ */
/* Record Payment Sheet                                               */
/* ------------------------------------------------------------------ */

function RecordPaymentSheet({
  isOpen,
  onClose,
  invoiceId,
  amountDue,
  onSuccess,
}: {
  isOpen: boolean
  onClose: () => void
  invoiceId: string
  amountDue: number
  onSuccess: () => void
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
    if (parsed > amountDue) {
      setError(`Amount cannot exceed ${formatNZD(amountDue)}`)
      return
    }
    setIsSubmitting(true)
    setError(null)
    const ok = await recordPayment(invoiceId, parsed)
    setIsSubmitting(false)
    if (ok) {
      onSuccess()
      onClose()
    } else {
      setError('Failed to record payment')
    }
  }

  return (
    <Sheet
      opened={isOpen}
      onBackdropClick={onClose}
      data-testid="record-payment-sheet"
    >
      <Block>
        <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Record Payment
        </h3>
        <List strongIos outlineIos>
          <ListInput
            label="Amount (NZD)"
            type="number"
            placeholder="0.00"
            value={amount}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
              setAmount(e.target.value)
              setError(null)
            }}
            info={error ?? undefined}
            inputClassName={error ? 'text-red-600' : ''}
          />
        </List>
        {error && (
          <p className="mt-1 px-4 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        <div className="mt-4 flex gap-3 px-4">
          <HapticButton
            outline
            onClick={onClose}
            disabled={isSubmitting}
            className="flex-1"
          >
            Cancel
          </HapticButton>
          <HapticButton
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="flex-1"
          >
            {isSubmitting ? 'Recording…' : 'Record'}
          </HapticButton>
        </div>
      </Block>
    </Sheet>
  )
}

/* ------------------------------------------------------------------ */
/* Void Reason Sheet                                                  */
/* ------------------------------------------------------------------ */

function VoidReasonSheet({
  isOpen,
  onClose,
  invoiceId,
  onSuccess,
}: {
  isOpen: boolean
  onClose: () => void
  invoiceId: string
  onSuccess: () => void
}) {
  const [reason, setReason] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!reason.trim()) {
      setError('Reason is required')
      return
    }
    setIsSubmitting(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/invoices/${invoiceId}/void`, { reason })
      onSuccess()
      onClose()
    } catch {
      setError('Failed to void invoice')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Sheet
      opened={isOpen}
      onBackdropClick={onClose}
      data-testid="void-reason-sheet"
    >
      <Block>
        <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Void Invoice
        </h3>
        <List strongIos outlineIos>
          <ListInput
            label="Reason"
            type="textarea"
            placeholder="Enter reason for voiding…"
            value={reason}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
              setReason(e.target.value)
              setError(null)
            }}
          />
        </List>
        {error && (
          <p className="mt-1 px-4 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        <div className="mt-4 flex gap-3 px-4">
          <HapticButton
            outline
            onClick={onClose}
            disabled={isSubmitting}
            className="flex-1"
          >
            Cancel
          </HapticButton>
          <HapticButton
            hapticStyle="heavy"
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="flex-1"
            colors={{ fillBgIos: 'bg-red-500', fillBgMaterial: 'bg-red-500' }}
          >
            {isSubmitting ? 'Voiding…' : 'Void Invoice'}
          </HapticButton>
        </div>
      </Block>
    </Sheet>
  )
}


/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Invoice detail screen — Konsta UI redesign with:
 * - KonstaNavbar with back button and overflow menu (•••)
 * - Hero card: customer name, vehicle, status badge, total NZD, balance due
 * - Sections: Vehicles, Line items (collapsible), Totals, Payments,
 *   Credit notes, Attachments, Notes
 * - Bottom sheet action menu
 * - Konsta Sheet for modal forms (record payment, void reason)
 * - Preserves computeCreditableAmount() and computePaymentSummary() exactly
 * - Calls GET /invoices/:id and all action endpoints unchanged
 *
 * Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 56.1, 56.5
 */
export default function InvoiceDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { isModuleEnabled } = useModules()

  const {
    data: invoice,
    isLoading,
    error,
    refetch,
  } = useApiDetail<InvoiceDetail>({
    endpoint: `/api/v1/invoices/${id}`,
  })

  const [isSending, setIsSending] = useState(false)
  const [showPaymentSheet, setShowPaymentSheet] = useState(
    searchParams.get('action') === 'record-payment',
  )
  const [showVoidSheet, setShowVoidSheet] = useState(false)
  const [showActionSheet, setShowActionSheet] = useState(false)
  const [lineItemsExpanded, setLineItemsExpanded] = useState(true)
  const [toast, setToast] = useState<{
    message: string
    variant: 'success' | 'error'
  } | null>(null)

  /* ── Action handlers ──────────────────────────────────────────── */

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
    setShowPaymentSheet(false)
    setToast({ message: 'Payment recorded', variant: 'success' })
    await refetch()
  }, [refetch])

  const handleVoidSuccess = useCallback(async () => {
    setShowVoidSheet(false)
    setToast({ message: 'Invoice voided', variant: 'success' })
    await refetch()
  }, [refetch])

  const handleDuplicate = useCallback(async () => {
    if (!id) return
    try {
      await apiClient.post(`/api/v1/invoices/${id}/duplicate`)
      setToast({ message: 'Invoice duplicated', variant: 'success' })
    } catch {
      setToast({ message: 'Failed to duplicate', variant: 'error' })
    }
    setShowActionSheet(false)
  }, [id])

  const handleEmail = useCallback(async () => {
    if (!id) return
    try {
      await apiClient.post(`/api/v1/invoices/${id}/email`)
      setToast({ message: 'Email sent', variant: 'success' })
    } catch {
      setToast({ message: 'Failed to send email', variant: 'error' })
    }
    setShowActionSheet(false)
  }, [id])

  const handleDelete = useCallback(async () => {
    if (!id) return
    try {
      await apiClient.delete(`/api/v1/invoices/${id}`)
      setToast({ message: 'Invoice deleted', variant: 'success' })
      navigate('/invoices')
    } catch {
      setToast({ message: 'Failed to delete', variant: 'error' })
    }
    setShowActionSheet(false)
  }, [id, navigate])

  const handleSendReminder = useCallback(async () => {
    if (!id) return
    try {
      await apiClient.post(`/api/v1/invoices/${id}/reminder`)
      setToast({ message: 'Reminder sent', variant: 'success' })
    } catch {
      setToast({ message: 'Failed to send reminder', variant: 'error' })
    }
    setShowActionSheet(false)
  }, [id])

  const handleShareLink = useCallback(async () => {
    if (!invoice) return
    const portalUrl = buildPortalUrl(window.location.origin, invoice.customer_portal_token)
    if (!portalUrl) return
    try {
      const { Share } = await import('@capacitor/share')
      await Share.share({
        title: `Invoice ${invoice.invoice_number ?? ''}`,
        text: `View invoice ${invoice.invoice_number ?? ''} from ${invoice.customer_name ?? 'us'}`,
        url: portalUrl,
      })
    } catch {
      try {
        await navigator.clipboard.writeText(portalUrl)
        setToast({ message: 'Link copied to clipboard', variant: 'success' })
      } catch {
        // Ignore clipboard errors
      }
    }
    setShowActionSheet(false)
  }, [invoice])

  /* ── Loading state ────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <Page data-testid="invoice-detail-page">
        <KonstaNavbar title="Invoice" showBack />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  if (error || !invoice) {
    return (
      <Page data-testid="invoice-detail-page">
        <KonstaNavbar title="Invoice" showBack />
        <Block>
          <div className="py-8 text-center text-red-600 dark:text-red-400">
            {error ?? 'Invoice not found'}
          </div>
        </Block>
      </Page>
    )
  }

  /* ── Derived data ─────────────────────────────────────────────── */

  const status = invoice.status ?? 'draft'
  const lineItems: InvoiceLineItem[] = invoice.line_items ?? []
  const payments = invoice.payments ?? []
  const creditNotes = invoice.credit_notes ?? []
  const attachments = invoice.attachments ?? []
  const vehicles = invoice.vehicles ?? []
  const vehiclesModuleEnabled = isModuleEnabled('vehicles')
  const balanceDue = invoice.balance_due ?? invoice.amount_due ?? 0

  // Use preserved helper logic
  const paymentSummary = computePaymentSummary(payments)
  const creditableAmount = computeCreditableAmount(
    invoice.total ?? 0,
    creditNotes.map((cn) => cn.amount ?? 0),
  )

  /* ── Overflow menu (•••) ──────────────────────────────────────── */

  const overflowButton = (
    <button
      type="button"
      onClick={() => setShowActionSheet(true)}
      className="flex min-h-[44px] min-w-[44px] items-center justify-center text-lg text-primary"
      aria-label="More actions"
      data-testid="overflow-menu-button"
    >
      •••
    </button>
  )

  return (
    <Page data-testid="invoice-detail-page">
      {/* ── Navbar ──────────────────────────────────────────────── */}
      <KonstaNavbar
        title={invoice.invoice_number ?? 'Invoice'}
        showBack
        rightActions={overflowButton}
      />

      <div className="flex flex-col gap-4 pb-24">
        {/* ── Toast ───────────────────────────────────────────────── */}
        {toast && (
          <div
            className={`mx-4 mt-2 rounded-lg p-3 text-sm ${
              toast.variant === 'success'
                ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
            }`}
            role="alert"
          >
            {toast.message}
            <button
              type="button"
              onClick={() => setToast(null)}
              className="ml-2 font-medium underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* ── Hero Card ───────────────────────────────────────────── */}
        <Card className="mx-4 mt-2" data-testid="hero-card">
          <div className="flex flex-col gap-3 p-4">
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
                  {invoice.customer_name ?? 'Unknown Customer'}
                </h2>
                {(invoice.vehicle_rego || invoice.vehicle_description) && (
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    🚗 {invoice.vehicle_rego ?? ''}{' '}
                    {invoice.vehicle_description ?? ''}
                  </p>
                )}
              </div>
              <StatusBadge status={status} size="md" />
            </div>

            <div className="flex items-end justify-between border-t border-gray-100 pt-3 dark:border-gray-700">
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Total
                </p>
                <p className="text-xl font-bold text-gray-900 dark:text-gray-100">
                  {formatNZD(invoice.total)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  Balance Due
                </p>
                <p
                  className={`text-xl font-bold ${
                    balanceDue > 0
                      ? 'text-red-600 dark:text-red-400'
                      : 'text-emerald-600 dark:text-emerald-400'
                  }`}
                >
                  {formatNZD(balanceDue)}
                </p>
              </div>
            </div>

            {/* Dates row */}
            <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400">
              <span>Created {formatDate(invoice.created_at)}</span>
              <span>Due {formatDate(invoice.due_date)}</span>
            </div>
          </div>
        </Card>

        {/* ── Vehicles Section (if vehicles module) ───────────────── */}
        {vehiclesModuleEnabled && vehicles.length > 0 && (
          <>
            <BlockTitle>Vehicles</BlockTitle>
            <List strongIos outlineIos dividersIos>
              {vehicles.map((v) => (
                <ListItem
                  key={v.id ?? v.rego}
                  title={v.rego ?? 'Unknown'}
                  subtitle={
                    [v.make, v.model, v.year].filter(Boolean).join(' ') ||
                    undefined
                  }
                  link
                  onClick={() => v.id && navigate(`/vehicles/${v.id}`)}
                />
              ))}
            </List>
          </>
        )}

        {/* ── Line Items (collapsible) ────────────────────────────── */}
        <BlockTitle>
          <button
            type="button"
            onClick={() => setLineItemsExpanded(!lineItemsExpanded)}
            className="flex w-full items-center justify-between"
          >
            <span>Line Items ({lineItems.length})</span>
            <svg
              className={`h-4 w-4 transition-transform ${
                lineItemsExpanded ? 'rotate-180' : ''
              }`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </button>
        </BlockTitle>
        {lineItemsExpanded && (
          <List strongIos outlineIos dividersIos data-testid="line-items-list">
            {lineItems.length === 0 ? (
              <ListItem title="No line items" />
            ) : (
              lineItems.map((item) => {
                const qty = item.quantity ?? 0
                const price = item.unit_price ?? 0
                const amount = item.amount ?? qty * price

                return (
                  <ListItem
                    key={item.id}
                    title={item.description || 'Unnamed item'}
                    subtitle={
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {qty} × {formatNZD(price)}
                        {item.tax_rate > 0 &&
                          ` · ${Number(item.tax_rate * 100).toFixed(0)}% tax`}
                      </span>
                    }
                    after={
                      <span className="font-medium tabular-nums text-gray-900 dark:text-gray-100">
                        {formatNZD(amount)}
                      </span>
                    }
                  />
                )
              })
            )}
          </List>
        )}

        {/* ── Totals ──────────────────────────────────────────────── */}
        <BlockTitle>Totals</BlockTitle>
        <Card className="mx-4" data-testid="totals-card">
          <div className="flex flex-col gap-2 p-4 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Subtotal</span>
              <span className="tabular-nums text-gray-900 dark:text-gray-100">
                {formatNZD(invoice.subtotal)}
              </span>
            </div>
            {(invoice.discount_amount ?? 0) > 0 && (
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Discount
                  {invoice.discount_type === 'percentage' &&
                    invoice.discount_value != null &&
                    ` (${invoice.discount_value}%)`}
                </span>
                <span className="tabular-nums text-red-600 dark:text-red-400">
                  -{formatNZD(invoice.discount_amount)}
                </span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">GST</span>
              <span className="tabular-nums text-gray-900 dark:text-gray-100">
                {formatNZD(invoice.tax_amount)}
              </span>
            </div>
            {(invoice.shipping_charges ?? 0) > 0 && (
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Shipping
                </span>
                <span className="tabular-nums text-gray-900 dark:text-gray-100">
                  {formatNZD(invoice.shipping_charges)}
                </span>
              </div>
            )}
            {(invoice.adjustment ?? 0) !== 0 && (
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Adjustment
                </span>
                <span className="tabular-nums text-gray-900 dark:text-gray-100">
                  {formatNZD(invoice.adjustment)}
                </span>
              </div>
            )}
            <div className="flex justify-between border-t border-gray-200 pt-2 dark:border-gray-600">
              <span className="font-semibold text-gray-900 dark:text-gray-100">
                Total
              </span>
              <span className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                {formatNZD(invoice.total)}
              </span>
            </div>
          </div>
        </Card>

        {/* ── Payments ────────────────────────────────────────────── */}
        <BlockTitle>Payments</BlockTitle>
        <Card className="mx-4" data-testid="payments-card">
          <div className="flex flex-col gap-2 p-4 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">
                Amount Paid
              </span>
              <span className="tabular-nums text-green-600 dark:text-green-400">
                {formatNZD(paymentSummary.totalPaid)}
              </span>
            </div>
            {paymentSummary.totalRefunded > 0 && (
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">
                  Refunded
                </span>
                <span className="tabular-nums text-red-600 dark:text-red-400">
                  -{formatNZD(paymentSummary.totalRefunded)}
                </span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">
                Amount Due
              </span>
              <span className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                {formatNZD(balanceDue)}
              </span>
            </div>
          </div>
          {payments.length > 0 && (
            <List strongIos outlineIos dividersIos className="mt-2">
              {payments.map((p, idx) => (
                <ListItem
                  key={p.id ?? idx}
                  title={p.is_refund ? 'Refund' : 'Payment'}
                  subtitle={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {p.method ?? 'Unknown method'}
                      {p.date ? ` · ${formatDate(p.date)}` : ''}
                    </span>
                  }
                  after={
                    <span
                      className={`font-medium tabular-nums ${
                        p.is_refund
                          ? 'text-red-600 dark:text-red-400'
                          : 'text-green-600 dark:text-green-400'
                      }`}
                    >
                      {p.is_refund ? '-' : ''}
                      {formatNZD(
                        typeof p.amount === 'string'
                          ? parseFloat(p.amount) || 0
                          : p.amount ?? 0,
                      )}
                    </span>
                  }
                />
              ))}
            </List>
          )}
        </Card>

        {/* ── Credit Notes ────────────────────────────────────────── */}
        {creditNotes.length > 0 && (
          <>
            <BlockTitle>Credit Notes</BlockTitle>
            <List strongIos outlineIos dividersIos>
              {creditNotes.map((cn, idx) => (
                <ListItem
                  key={cn.id ?? idx}
                  title={cn.credit_note_number ?? `Credit Note ${idx + 1}`}
                  subtitle={cn.reason ?? undefined}
                  after={
                    <span className="font-medium tabular-nums text-orange-600 dark:text-orange-400">
                      -{formatNZD(cn.amount)}
                    </span>
                  }
                />
              ))}
            </List>
            <Block>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Creditable amount remaining:{' '}
                <span className="font-medium">
                  {formatNZD(creditableAmount)}
                </span>
              </p>
            </Block>
          </>
        )}

        {/* ── Attachments ─────────────────────────────────────────── */}
        {(attachments.length > 0 || true) && (
          <>
            <BlockTitle>Attachments</BlockTitle>
            {attachments.length > 0 ? (
              <div className="flex gap-2 overflow-x-auto px-4">
                {attachments.map((att, idx) => (
                  <a
                    key={att.id ?? idx}
                    href={att.url ?? '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800"
                  >
                    {att.thumbnail_url ? (
                      <img
                        src={att.thumbnail_url}
                        alt={att.filename ?? 'Attachment'}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <span className="text-xs text-gray-400">
                        {att.filename?.split('.').pop()?.toUpperCase() ?? 'FILE'}
                      </span>
                    )}
                  </a>
                ))}
              </div>
            ) : (
              <Block>
                <p className="text-sm text-gray-400 dark:text-gray-500">
                  No attachments
                </p>
              </Block>
            )}
            <Block>
              <HapticButton
                outline
                small
                onClick={async () => {
                  try {
                    const { Camera, CameraResultType } = await import(
                      '@capacitor/camera'
                    )
                    const photo = await Camera.getPhoto({
                      resultType: CameraResultType.Uri,
                      quality: 80,
                    })
                    if (photo?.webPath && id) {
                      const blob = await fetch(photo.webPath).then((r) =>
                        r.blob(),
                      )
                      const formData = new FormData()
                      formData.append('file', blob, 'photo.jpg')
                      await apiClient.post(
                        `/api/v1/invoices/${id}/attachments`,
                        formData,
                      )
                      setToast({
                        message: 'Photo attached',
                        variant: 'success',
                      })
                      await refetch()
                    }
                  } catch {
                    // Camera cancelled or unavailable — silent
                  }
                }}
              >
                📷 Add Photo
              </HapticButton>
            </Block>
          </>
        )}

        {/* ── Notes ───────────────────────────────────────────────── */}
        {(invoice.notes || invoice.customer_notes || invoice.internal_notes) && (
          <>
            <BlockTitle>Notes</BlockTitle>
            <Card className="mx-4">
              <div className="flex flex-col gap-2 p-4 text-sm">
                {invoice.customer_notes && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                      Customer Notes
                    </p>
                    <p className="text-gray-900 dark:text-gray-100">
                      {invoice.customer_notes}
                    </p>
                  </div>
                )}
                {invoice.internal_notes && (
                  <div>
                    <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                      Internal Notes
                    </p>
                    <p className="text-gray-900 dark:text-gray-100">
                      {invoice.internal_notes}
                    </p>
                  </div>
                )}
                {invoice.notes && !invoice.customer_notes && !invoice.internal_notes && (
                  <p className="text-gray-900 dark:text-gray-100">
                    {invoice.notes}
                  </p>
                )}
              </div>
            </Card>
          </>
        )}

        {/* ── Quick Action Buttons ────────────────────────────────── */}
        <Block className="flex flex-col gap-3 px-4">
          {status === 'draft' && (
            <HapticButton
              large
              onClick={handleSend}
              disabled={isSending}
              data-testid="send-invoice-button"
            >
              {isSending ? 'Sending…' : 'Send Invoice'}
            </HapticButton>
          )}
          {status !== 'paid' && status !== 'cancelled' && (
            <HapticButton
              large
              outline
              onClick={() => setShowPaymentSheet(true)}
              data-testid="record-payment-button"
            >
              Record Payment
            </HapticButton>
          )}
          <HapticButton
            large
            outline
            onClick={() => navigate(`/invoices/${id}/pdf`)}
            data-testid="preview-pdf-button"
          >
            Preview PDF
          </HapticButton>
        </Block>
      </div>

      {/* ── Record Payment Sheet ──────────────────────────────────── */}
      <RecordPaymentSheet
        isOpen={showPaymentSheet}
        onClose={() => setShowPaymentSheet(false)}
        invoiceId={invoice.id}
        amountDue={balanceDue}
        onSuccess={handlePaymentSuccess}
      />

      {/* ── Void Reason Sheet ─────────────────────────────────────── */}
      <VoidReasonSheet
        isOpen={showVoidSheet}
        onClose={() => setShowVoidSheet(false)}
        invoiceId={invoice.id}
        onSuccess={handleVoidSuccess}
      />

      {/* ── Bottom Sheet Action Menu ──────────────────────────────── */}
      <Sheet
        opened={showActionSheet}
        onBackdropClick={() => setShowActionSheet(false)}
        data-testid="action-sheet"
      >
        <Block>
          <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
            Actions
          </h3>
        </Block>
        <List strongIos outlineIos dividersIos>
          <ListItem
            link
            title="Email"
            onClick={() => {
              void handleEmail()
            }}
          />
          {status === 'draft' && (
            <ListItem
              link
              title="Mark Sent"
              onClick={() => {
                void handleSend()
                setShowActionSheet(false)
              }}
            />
          )}
          {!['voided', 'paid'].includes(status) && (
            <ListItem
              link
              title="Void"
              onClick={() => {
                setShowActionSheet(false)
                setShowVoidSheet(true)
              }}
            />
          )}
          <ListItem
            link
            title="Duplicate"
            onClick={() => {
              void handleDuplicate()
            }}
          />
          <ListItem
            link
            title="Download PDF"
            onClick={() => {
              navigate(`/invoices/${id}/pdf`)
              setShowActionSheet(false)
            }}
          />
          <ListItem
            link
            title="Print"
            onClick={() => {
              window.print()
              setShowActionSheet(false)
            }}
          />
          <ListItem
            link
            title="Print POS Receipt"
            onClick={() => {
              navigate(`/invoices/${id}/pos-receipt`)
              setShowActionSheet(false)
            }}
          />
          {status !== 'paid' && status !== 'cancelled' && (
            <ListItem
              link
              title="Record Payment"
              onClick={() => {
                setShowActionSheet(false)
                setShowPaymentSheet(true)
              }}
            />
          )}
          {creditableAmount > 0 && (
            <ListItem
              link
              title="Create Credit Note"
              onClick={() => {
                navigate(`/invoices/${id}/credit-note`)
                setShowActionSheet(false)
              }}
            />
          )}
          {paymentSummary.netPaid > 0 && (
            <ListItem
              link
              title="Process Refund"
              onClick={() => {
                navigate(`/invoices/${id}/refund`)
                setShowActionSheet(false)
              }}
            />
          )}
          {canSharePortalLink(invoice.customer_portal_token, invoice.customer_enable_portal) && (
            <ListItem
              link
              title="Share Link"
              onClick={() => {
                void handleShareLink()
              }}
            />
          )}
          {status === 'overdue' && (
            <ListItem
              link
              title="Send Reminder"
              onClick={() => {
                void handleSendReminder()
              }}
            />
          )}
          <ListItem
            link
            title="Delete"
            className="text-red-600 dark:text-red-400"
            onClick={() => {
              void handleDelete()
            }}
          />
        </List>
      </Sheet>
    </Page>
  )
}