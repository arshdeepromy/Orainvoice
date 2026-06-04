import { useState, useCallback } from 'react'
import apiClient from '@/api/client'
import { Input, Button, Spinner, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

interface FleetVehicle {
  rego: string
  make: string
  model: string
  total_spend: number
  last_service_date: string
}

interface FleetData {
  fleet_name: string
  total_spend: number
  vehicles_serviced: number
  outstanding_balance: number
  vehicles: FleetVehicle[]
}

function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 3, 1)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number | undefined) => v != null ? `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}` : '$0.00'

/**
 * Fleet account report — total spend, vehicles serviced, outstanding balance.
 * Requirements: 66.4
 */
export default function FleetReport() {
  const [fleetId, setFleetId] = useState('')
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<FleetData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchReport = useCallback(async () => {
    if (!fleetId.trim()) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<FleetData>(`/reports/fleet/${fleetId}`, {
        params: { start_date: range.from, end_date: range.to },
      })
      setData(res.data)
    } catch {
      setError('Failed to load fleet report.')
    } finally {
      setLoading(false)
    }
  }, [fleetId, range])

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">
        Fleet account report showing total spend, vehicles serviced, and outstanding balance.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end mb-6 no-print">
        <div className="w-64">
          <Input
            label="Fleet Account ID"
            placeholder="Enter fleet account ID…"
            value={fleetId}
            onChange={(e) => setFleetId(e.target.value)}
          />
        </div>
        <DateRangeFilter value={range} onChange={setRange} />
        <Button onClick={fetchReport} disabled={!fleetId.trim()} loading={loading}>
          Generate
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading fleet report" /></div>}

      {!loading && data && (
        <>
          <h3 className="text-lg font-medium text-text mb-4">{data.fleet_name}</h3>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Total Spend</p>
              <p className="text-2xl font-semibold text-text mono">{fmt(data.total_spend)}</p>
            </div>
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Vehicles Serviced</p>
              <p className="text-2xl font-semibold text-text mono">{data.vehicles_serviced}</p>
            </div>
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Outstanding Balance</p>
              <p className="text-2xl font-semibold text-danger mono">{fmt(data.outstanding_balance)}</p>
            </div>
          </div>

          <div className="flex justify-end mb-4">
            <div className="flex items-center gap-2 no-print">
              <ExportButtons endpoint={`/reports/fleet/${fleetId}`} params={{ start_date: range.from, end_date: range.to }} />
              <PrintButton label="Print Report" />
            </div>
          </div>

          <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
            <table className="min-w-full" role="grid">
              <caption className="sr-only">Fleet vehicles</caption>
              <thead>
                <tr>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Rego</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Make</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Model</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Total Spend</th>
                  <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Last Service</th>
                </tr>
              </thead>
              <tbody>
                {!data.vehicles || data.vehicles.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-muted">
                      No vehicles serviced in this period.
                    </td>
                  </tr>
                ) : (
                  data.vehicles.map((v, i) => (
                    <tr key={v.rego || i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-text mono">{v.rego}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{v.make}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{v.model}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text text-right mono">{fmt(v.total_spend)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted mono">
                        {new Date(v.last_service_date).toLocaleDateString('en-NZ')}
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
