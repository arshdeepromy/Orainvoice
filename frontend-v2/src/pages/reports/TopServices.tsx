import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'
import { useBranch } from '@/contexts/BranchContext'

interface ServiceRow {
  description: string
  count: number
  total_revenue: number
}

interface TopServicesData {
  services?: ServiceRow[]
  period_start?: string
  period_end?: string
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

/**
 * Top services report — services ranked by revenue with count.
 * Reads `services[]` from the backend (each row: `{description, count, total_revenue}`).
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 14.1, 14.2, 19.1, 19.2, 19.3, 19.5, 21.1
 */
export default function TopServices() {
  const { selectedBranchId } = useBranch()
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<TopServicesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string> = { start_date: range.from, end_date: range.to }
      if (selectedBranchId) params.branch_id = selectedBranchId
      const res = await apiClient.get<TopServicesData>('/reports/top-services', { params, signal })
      setData(res.data ?? null)
    } catch {
      if (!signal?.aborted) setError('Failed to load top services report.')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [range, selectedBranchId])

  useEffect(() => {
    const controller = new AbortController()
    fetchData(controller.signal)
    return () => controller.abort()
  }, [fetchData])

  const services = data?.services ?? []
  const hasRows = services.length > 0

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">Services ranked by revenue.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons
            endpoint="/reports/top-services"
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

      {loading && <div className="py-16"><Spinner label="Loading top services report" /></div>}

      {!loading && data && (
        <>
          {/* Table */}
          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card mb-6">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Top services by revenue</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">#</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Service</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Count</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Revenue</th>
                </tr>
              </thead>
              <tbody>
                {!hasRows ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-sm text-muted">
                      No service data for this period.
                    </td>
                  </tr>
                ) : (
                  services.map((s, i) => (
                    <tr key={`${s?.description ?? 'row'}-${i}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="px-4 py-3 text-sm text-muted mono">{i + 1}</td>
                      <td className="px-4 py-3 text-sm text-text">{s?.description ?? '—'}</td>
                      <td className="px-4 py-3 text-sm text-muted text-right mono">{s?.count ?? 0}</td>
                      <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(s?.total_revenue ?? 0)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Chart */}
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <h3 className="text-sm font-medium text-text mb-3">Revenue by Service</h3>
            {hasRows ? (
              <SimpleBarChart
                title="Revenue by service"
                items={services.map((s) => ({ label: s?.description ?? '—', value: s?.total_revenue ?? 0 }))}
                formatValue={fmt}
              />
            ) : (
              <p className="text-sm text-muted py-8 text-center">No service data available for this period.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
