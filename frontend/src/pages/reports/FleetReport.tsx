import { useState, useCallback } from 'react'
import apiClient from '../../api/client'
import { Input, Button, Spinner, PrintButton } from '../../components/ui'
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
  const from = new Date(now)
  from.setMonth(from.getMonth() - 3)
  return { from: from.toISOString().slice(0, 10), to: now.toISOString().slice(0, 10) }
}

const fmt = (v: number) => `$${v.toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`

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
        params: { from: range.from, to: range.to },
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
      <p className="text-sm text-gray-500 mb-4">
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
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && <div className="py-16"><Spinner label="Loading fleet report" /></div>}

      {!loading && data && (
        <>
          <h3 className="text-lg font-medium text-gray-900 mb-4">{data.fleet_name}</h3>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Total Spend</p>
              <p className="text-2xl font-semibold text-gray-900">{fmt(data.total_spend)}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Vehicles Serviced</p>
              <p className="text-2xl font-semibold text-gray-900">{data.vehicles_serviced}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <p className="text-sm text-gray-500">Outstanding Balance</p>
              <p className="text-2xl font-semibold text-red-600">{fmt(data.outstanding_balance)}</p>
            </div>
          </div>

          <div className="flex justify-end mb-4">
            <div className="flex items-center gap-2 no-print">
              <ExportButtons endpoint={`/reports/fleet/${fleetId}`} params={{ from: range.from, to: range.to }} />
              <PrintButton label="Print Report" />
            </div>
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200" role="grid">
              <caption className="sr-only">Fleet vehicles</caption>
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rego</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Make</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Model</th>
                  <th scope="col" className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Total Spend</th>
                  <th scope="col" className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Last Service</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {data.vehicles.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-gray-500">
                      No vehicles serviced in this period.
                    </td>
                  </tr>
                ) : (
                  data.vehicles.map((v) => (
                    <tr key={v.rego} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">{v.rego}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{v.make}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">{v.model}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-900 text-right">{fmt(v.total_spend)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
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
