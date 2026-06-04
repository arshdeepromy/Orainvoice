import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Badge, PrintButton } from '@/components/ui'
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

const STATUS_BADGE: Record<string, 'success' | 'warn' | 'danger' | 'info' | 'neutral'> = {
  paid: 'success',
  issued: 'info',
  partially_paid: 'warn',
  overdue: 'danger',
  draft: 'neutral',
  voided: 'neutral',
}

const STATUS_COLOUR: Record<string, string> = {
  paid: 'bg-ok',
  issued: 'bg-accent',
  partially_paid: 'bg-warn',
  overdue: 'bg-danger',
  draft: 'bg-muted-2',
  voided: 'bg-border-strong',
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
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
        params: { start_date: range.from, end_date: range.to },
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
      <p className="text-sm text-muted mb-4 no-print">Breakdown of invoices by status.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/invoices/status" params={{ start_date: range.from, end_date: range.to }} />
          <PrintButton label="Print Report" />
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading invoice status report" /></div>}

      {!loading && data && (
        <>
          <div className="rounded-card border border-border bg-card p-4 mb-6 shadow-card">
            <p className="text-sm text-muted mb-1">Total Invoices</p>
            <p className="text-2xl font-semibold text-text mono">{data.total_invoices}</p>
          </div>

          {/* Status table */}
          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card mb-6">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Invoice status breakdown</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Status</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Count</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total Amount</th>
                </tr>
              </thead>
              <tbody>
                {!data.statuses || data.statuses.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-12 text-center text-sm text-muted">
                      No invoice data for this period.
                    </td>
                  </tr>
                ) : (
                  data.statuses.map((s, i) => (
                    <tr key={s.status || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="px-4 py-3 text-sm">
                        <Badge variant={STATUS_BADGE[s.status] || 'neutral'}>
                          {s.status.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-sm text-text text-right mono">{s.count}</td>
                      <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(s.total_amount)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Chart */}
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <h3 className="text-sm font-medium text-text mb-3">Invoice Count by Status</h3>
            {data.statuses && data.statuses.length > 0 ? (
              <SimpleBarChart
                title="Invoice count by status"
                items={data.statuses.map((s) => ({
                  label: s.status.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
                  value: s.count,
                  colour: STATUS_COLOUR[s.status] || 'bg-muted-2',
                }))}
              />
            ) : (
              <p className="text-sm text-muted py-8 text-center">No invoice data available for this period.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
