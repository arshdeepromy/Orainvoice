import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, Badge, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'
import { useBranch } from '@/contexts/BranchContext'

interface StatusBreakdownRow {
  status: string
  count: number
  total: number
}

interface InvoiceStatusData {
  breakdown?: StatusBreakdownRow[]
  period_start?: string
  period_end?: string
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

// Seed the initial range to match DateRangeFilter's `presetRange('month')` semantics
// (first day of last month → last day of last month) so the dropdown label
// ('Last month') and the queried data agree on mount.
function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  const to = new Date(now.getFullYear(), now.getMonth(), 0)
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) }
}

const fmt = (v: number) => `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`
const formatStatus = (s: string) =>
  s.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())

/**
 * Invoice status report — breakdown of invoices by status with counts and amounts.
 * Reads `breakdown[]` from the backend (each row: `{status, count, total}`)
 * and computes the total invoice count as the sum of `count` across rows.
 *
 * Requirements: 2.1, 2.2, 2.3, 2.4, 14.1, 14.2, 19.1, 19.2, 19.3, 19.5, 21.1
 */
export default function InvoiceStatus() {
  const { selectedBranchId } = useBranch()
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<InvoiceStatusData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = { start_date: range.from, end_date: range.to }
      if (selectedBranchId) params.branch_id = selectedBranchId
      const res = await apiClient.get<InvoiceStatusData>('/reports/invoices/status', { params, signal })
      setData(res.data ?? null)
    } catch {
      if (!signal?.aborted) setError('Failed to load invoice status report.')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [range, selectedBranchId])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  const rows = data?.breakdown ?? []
  const totalInvoices = rows.reduce((sum, r) => sum + (r?.count ?? 0), 0)
  const hasRows = rows.length > 0

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">Breakdown of invoices by status.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons
            endpoint="/reports/invoices/status"
            params={{
              start_date: range.from,
              end_date: range.to,
              ...(selectedBranchId ? { branch_id: selectedBranchId } : {}),
            }}
          />
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
            <p className="text-2xl font-semibold text-text mono">{totalInvoices}</p>
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
                {!hasRows ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-12 text-center text-sm text-muted">
                      No invoice data for this period.
                    </td>
                  </tr>
                ) : (
                  rows.map((r, i) => (
                    <tr key={r?.status || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="px-4 py-3 text-sm">
                        <Badge variant={STATUS_BADGE[r?.status] ?? 'neutral'}>
                          {formatStatus(r?.status ?? '')}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-sm text-text text-right mono">{r?.count ?? 0}</td>
                      <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(r?.total ?? 0)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Chart */}
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <h3 className="text-sm font-medium text-text mb-3">Invoice Count by Status</h3>
            {hasRows ? (
              <SimpleBarChart
                title="Invoice count by status"
                items={rows.map((r) => ({
                  label: formatStatus(r?.status ?? ''),
                  value: r?.count ?? 0,
                  colour: STATUS_COLOUR[r?.status] ?? 'bg-muted-2',
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
