import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { PaymentPage } from './PaymentPage'
import { usePortalLocale } from './PortalLocaleContext'
import { formatCurrency, formatDate } from './portalFormatters'

export interface PortalInvoice {
  id: string
  invoice_number: string
  issue_date: string
  due_date: string | null
  status: string
  total: number
  balance_due: number
  line_items_summary: string
}

interface PortalInvoicesResponse {
  invoices: PortalInvoice[]
  org_has_stripe_connect: boolean
  total_outstanding: number
  total_paid: number
}

/** Invoice statuses eligible for online payment */
const PAYABLE_STATUSES = new Set(['issued', 'partially_paid', 'overdue'])

interface InvoiceHistoryProps {
  token: string
  primaryColor: string
}

const STATUS_CONFIG: Record<string, { label: string; variant: 'success' | 'warning' | 'error' | 'info' | 'neutral' }> = {
  paid: { label: 'Paid', variant: 'success' },
  partially_paid: { label: 'Partially Paid', variant: 'warning' },
  issued: { label: 'Issued', variant: 'info' },
  overdue: { label: 'Overdue', variant: 'error' },
  voided: { label: 'Voided', variant: 'neutral' },
  refunded: { label: 'Refunded', variant: 'info' },
  partially_refunded: { label: 'Partially Refunded', variant: 'info' },
}

export function InvoiceHistory({ token, primaryColor }: InvoiceHistoryProps) {
  const locale = usePortalLocale()
  const [invoices, setInvoices] = useState<PortalInvoice[]>([])
  const [orgHasStripeConnect, setOrgHasStripeConnect] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [payingInvoice, setPayingInvoice] = useState<PortalInvoice | null>(null)

  const fetchInvoices = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<PortalInvoicesResponse>(`/portal/${token}/invoices`)
      setInvoices(res.data?.invoices ?? [])
      setOrgHasStripeConnect(res.data?.org_has_stripe_connect ?? false)
    } catch {
      setError('Failed to load invoices.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    fetchInvoices()
  }, [fetchInvoices])

  if (payingInvoice) {
    return (
      <PaymentPage
        token={token}
        invoice={payingInvoice}
        primaryColor={primaryColor}
        onBack={() => {
          setPayingInvoice(null)
          fetchInvoices()
        }}
      />
    )
  }

  if (loading) {
    return (
      <div className="py-8">
        <Spinner label="Loading invoices" />
      </div>
    )
  }

  if (error) {
    return <AlertBanner variant="error">{error}</AlertBanner>
  }

  if (invoices.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-gray-500">
        No invoices found.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {invoices.map((inv) => {
        const cfg = STATUS_CONFIG[inv.status] ?? { label: inv.status, variant: 'neutral' as const }
        const canPay =
          orgHasStripeConnect &&
          inv.balance_due > 0 &&
          PAYABLE_STATUSES.has(inv.status)

        return (
          <div
            key={inv.id}
            className="rounded-lg border border-gray-200 bg-white p-4"
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{inv.invoice_number}</span>
                  <Badge variant={cfg.variant}>{cfg.label}</Badge>
                </div>
                <p className="mt-1 text-sm text-gray-500 truncate">
                  {inv.line_items_summary}
                </p>
                <p className="mt-1 text-xs text-gray-400">
                  Issued {formatDate(inv.issue_date, locale)}
                  {inv.due_date && ` · Due ${formatDate(inv.due_date, locale)}`}
                </p>
              </div>

              <div className="flex items-center gap-3">
                <div className="text-right">
                  <p className="text-sm font-semibold text-gray-900 tabular-nums">
                    {formatCurrency(inv.total, locale)}
                  </p>
                  {canPay && (
                    <p className="text-xs text-amber-600 tabular-nums">
                      {formatCurrency(inv.balance_due, locale)} due
                    </p>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    window.open(
                      `/api/v1/portal/${token}/invoices/${inv.id}/pdf`,
                      '_blank',
                    )
                  }}
                >
                  Download PDF
                </Button>
                {canPay && (
                  <Button
                    size="sm"
                    onClick={() => setPayingInvoice(inv)}
                    style={{ backgroundColor: primaryColor }}
                    className="!bg-[var(--btn-color)] hover:opacity-90"
                  >
                    Pay Now
                  </Button>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
