import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Spinner, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'
import SimpleBarChart from './SimpleBarChart'

interface ServiceStat {
  service_name: string
  count: number
  revenue: number
}

interface TopServicesData {
  services: ServiceStat[]
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * Top services report — ranked by revenue with count.
 * Requirements: 45.1
 */
export default function TopServices() {
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<TopServicesData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<TopServicesData>('/reports/top-services', {
        params: { start_date: range.from, end_date: range.to },
      })
      setData(res.data)
    } catch {
      setError('Failed to load top services report.')
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">Services ranked by revenue.</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6 no-print">
        <DateRangeFilter value={range} onChange={setRange} />
        <div className="flex items-center gap-2">
          <ExportButtons endpoint="/reports/top-services" params={{ start_date: range.from, end_date: range.to }} />
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
                {!data.services || data.services.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-sm text-muted">
                      No service data for this period.
                    </td>
                  </tr>
                ) : (
                  data.services.map((s, i) => (
                    <tr key={`${s.service_name}-${i}`} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="px-4 py-3 text-sm text-muted mono">{i + 1}</td>
                      <td className="px-4 py-3 text-sm text-text">{s.service_name}</td>
                      <td className="px-4 py-3 text-sm text-muted text-right mono">{s.count}</td>
                      <td className="px-4 py-3 text-sm text-text text-right mono">{fmt(s.revenue)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Chart */}
          <div className="rounded-card border border-border bg-card p-4 shadow-card">
            <h3 className="text-sm font-medium text-text mb-3">Revenue by Service</h3>
            {data.services && data.services.length > 0 ? (
              <SimpleBarChart
                title="Revenue by service"
                items={data.services.map((s) => ({ label: s.service_name, value: s.revenue }))}
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
