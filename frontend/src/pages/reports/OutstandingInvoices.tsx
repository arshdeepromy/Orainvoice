import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Badge, Button, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

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
  const from = new Date(now)
  from.setMonth(from.getMonth() - 3)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number) => `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`

/**
 * Outstanding invoices report with one-click payment reminder.
 * Requirements: 45.1, 45.5
 */
export default function OutstandingInvoices() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<OutstandingData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sendingReminder, setSendingReminder] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<OutstandingData>('/reports/outstanding', {
        params: { from: range.from, to: range.to },
      })
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
      <p className="text-sm text-gray-500 mb-4">
        Invoices with outstanding balances. Send payment reminders with one click.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/outstanding" params={{ from: range.from, to: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading outstanding invoices" /></div>}

      {!loading && data && (
        <>
          <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
            <p className="text-sm text-gray-500 mb-1">Total Outstanding</p>
            <p className="text-2xl font-semibold text-red-600">{fmt(data.total_outstanding)}</p>
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Outstanding invoices</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Invoice</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Customer</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Balance Due</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Due Date</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.invoices.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-sm text-gray-500">
                      No outstanding invoices for this period.
                    </td>
                  </tr>
                ) : (
                  data.invoices.map((inv) => (
                    <tr key={inv.id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{inv.invoice_number}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{inv.customer_name}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{inv.rego || '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right">{fmt(inv.total)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-red-600 font-medium text-right">{fmt(inv.balance_due)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {new Date(inv.due_date).toLocaleDateString('en-NZ')}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Badge variant={inv.status === 'overdue' ? 'error' : 'warning'}>
                          {inv.status.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right">
                        <Button
                          variant="secondary"
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
