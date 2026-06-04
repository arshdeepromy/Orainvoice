import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Badge, Button, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import { useBranch } from '@/contexts/BranchContext'

interface OutstandingInvoice {
  id: string
  invoice_number: string
  customer_name: string
  rego: string
  total: number
  balance_due: number
  due_date: string
  status: string
}

interface OutstandingData {
  invoices: OutstandingInvoice[]
  total_outstanding: number
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 3, 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * Outstanding invoices report with one-click payment reminder.
 * Requirements: 45.1, 45.5
 */
export default function OutstandingInvoices() {
  const { selectedBranchId } = useBranch()
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<OutstandingData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sendingReminder, setSendingReminder] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = { start_date: range.from, end_date: range.to }
      if (selectedBranchId) params.branch_id = selectedBranchId
      const res = await apiClient.get<OutstandingData>('/reports/outstanding', { params })
      setData(res.data)
    } catch {
      setError('Failed to load outstanding invoices.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  const sendReminder = async (invoiceId: string) => {
    setSendingReminder(invoiceId)
    try {
      await apiClient.post(`/invoices/${invoiceId}/email`, { template: 'payment_reminder' })
    } catch {
      // Silently fail — user can retry
    } finally {
      setSendingReminder(null)
    }
  }

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">
        Invoices with outstanding balances. Send payment reminders with one click.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/outstanding" params={{ start_date: range.from, end_date: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading outstanding invoices" /></div>}

      {!loading && data && (
        <>
          <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
            <p className="text-sm text-muted mb-1">Total Outstanding</p>
            <p className="text-2xl font-semibold text-danger mono">{fmt(data.total_outstanding)}</p>
          </div>

          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Outstanding invoices</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Invoice</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Customer</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Rego</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Balance Due</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Due Date</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {!data.invoices || data.invoices.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-muted">
                      No outstanding invoices for this period.
                    </td>
                  </tr>
                ) : (
                  data.invoices.map((inv, i) => (
                    <tr key={inv.id || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-text mono">{inv.invoice_number}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{inv.customer_name}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted mono">{inv.rego || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text text-right mono">{fmt(inv.total)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-danger font-medium text-right mono">{fmt(inv.balance_due)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted mono">
                        {inv.due_date ? new Date(inv.due_date).toLocaleDateString('en-NZ') : '—'}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Badge variant={inv.status === 'overdue' ? 'danger' : 'warn'}>
                          {(inv.status ?? '').replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={sendingReminder === inv.id}
                          onClick={() => sendReminder(inv.id)}
                          aria-label={`Send reminder for ${inv.invoice_number}`}
                        >
                          Send Reminder
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
