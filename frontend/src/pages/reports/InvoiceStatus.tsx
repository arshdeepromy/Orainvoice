import { useState, useEffect, useCallback } from 'react'
import apiClient from '../../api/client'
import { Spinner, Badge, PrintButton } from '../../components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'

interface StatusCount {
  status: string
  count: number
  total_amount: number
}

interface InvoiceStatusData {
  statuses: StatusCount[]
  total_invoices: number
}

const STATUS_BADGE: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
  paid: 'success',
  issued: 'info',
  partially_paid: 'warning',
  overdue: 'error',
  draft: 'neutral',
  voided: 'neutral',
}

const STATUS_COLOUR: Record<string, string> = {
  paid: 'bg-green-500',
  issued: 'bg-blue-500',
  partially_paid: 'bg-amber-500',
  overdue: 'bg-red-500',
  draft: 'bg-gray-400',
  voided: 'bg-gray-300',
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now)
  from.setMonth(from.getMonth() - 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * Invoice status report — breakdown of invoices by status with counts and amounts.
 * Requirements: 45.1
 */
export default function InvoiceStatus() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<InvoiceStatusData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<InvoiceStatusData>('/reports/invoices/status', {
        params: { from: range.from, to: range.to },
      })
      setData(res.data)
    } catch {
      setError('Failed to load invoice status report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div data-print-content>
      <p className="text-sm text-gray-500 mb-4">Breakdown of invoices by status.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/invoices/status" params={{ from: range.from, to: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading invoice status report" /></div>}

      {!loading && data && (
        <>
          <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
            <p className="text-sm text-gray-500 mb-1">Total Invoices</p>
            <p className="text-2xl font-semibold text-gray-900">{data.total_invoices}</p>
          </div>

          {/* Status table */}
          <div className="overflow-x-auto rounded-lg border border-gray-200 mb-6">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Invoice status breakdown</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Count</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {!data.statuses || data.statuses.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-12 text-center text-sm text-gray-500">
                      No invoice data for this period.
                    </td>
                  </tr>
                ) : (
                  data.statuses.map((s) => (
                    <tr key={s.status} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm">
                        <Badge variant={STATUS_BADGE[s.status] || 'neutral'}>
                          {s.status.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900 text-right">{s.count}</td>
                      <td className="px-4 py-3 text-sm text-gray-900 text-right">{fmt(s.total_amount)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Chart */}
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Invoice Count by Status</h3>
            {data.statuses && data.statuses.length > 0 ? (
              <SimpleBarChart
                title="Invoice count by status"
                items={data.statuses.map((s) => ({
                  label: s.status.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
                  value: s.count,
                  colour: STATUS_COLOUR[s.status] || 'bg-gray-400',
                }))}
              />
            ) : (
              <p className="text-sm text-gray-500 py-8 text-center">No invoice data available for this period.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
