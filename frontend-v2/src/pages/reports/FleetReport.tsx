import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Select, Spinner, PrintButton } from '@/components/ui'
import DateRangeFilter, { type DateRange } from './DateRangeFilter'
import ExportButtons from './ExportButtons'

interface FleetVehicle {
  rego: string
  make: string | null
  model: string | null
  total_spend: number
  last_service_date: string | null
}

interface FleetData {
  fleet_name?: string
  total_spend?: number
  vehicles_serviced?: number
  outstanding_balance?: number
  vehicles?: FleetVehicle[]
}

interface FleetAccountOption {
  id: string
  name: string
}

interface FleetAccountsResponse {
  fleet_accounts?: FleetAccountOption[]
  total?: number
}

// Seed the initial range to match DateRangeFilter's `presetRange('month')`
// (first day of last month → last day of last month) so the dropdown label
// ('Last month') and the queried data agree on mount.
function defaultRange(): DateRange {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  const to = new Date(now.getFullYear(), now.getMonth(), 0)
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) }
}

const fmt = (v: number | null | undefined) =>
  `$${(v ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2 })}`

const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-NZ')
}

/**
 * Fleet account report — total spend, vehicles serviced, outstanding balance,
 * and a per-vehicle breakdown. The fleet account is chosen from a populated
 * `Select` (sourced from `GET /customers/fleet-accounts`) rather than a raw
 * UUID input, and selection auto-fetches `GET /reports/fleet/{id}`.
 *
 * Requirements: 6.3, 6.4, 6.5, 6.6, 14.1, 14.2, 19.1, 19.3, 19.4, 21.1
 */
export default function FleetReport() {
  const [accounts, setAccounts] = useState<FleetAccountOption[]>([])
  const [accountsLoading, setAccountsLoading] = useState(true)
  const [accountsError, setAccountsError] = useState('')
  const [selectedFleetId, setSelectedFleetId] = useState('')
  const [range, setRange] = useState<DateRange>(defaultRange)
  const [data, setData] = useState<FleetData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Load fleet accounts for the picker.
  useEffect(() => {
    const controller = new AbortController()
    setAccountsLoading(true)
    setAccountsError('')
    apiClient
      .get<FleetAccountsResponse>('/customers/fleet-accounts', {
        params: { limit: 100 },
        signal: controller.signal,
      })
      .then((res) => {
        setAccounts(res.data?.fleet_accounts ?? [])
      })
      .catch(() => {
        if (!controller.signal.aborted) setAccountsError('Failed to load fleet accounts.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setAccountsLoading(false)
      })
    return () => controller.abort()
  }, [])

  const fetchReport = useCallback(
    async (signal?: AbortSignal) => {
      if (!selectedFleetId) {
        setData(null)
        return
      }
      setLoading(true)
      setError('')
      try {
        const res = await apiClient.get<FleetData>(`/reports/fleet/${selectedFleetId}`, {
          params: { start_date: range.from, end_date: range.to },
          signal,
        })
        setData(res.data ?? null)
      } catch {
        if (!signal?.aborted) setError('Failed to load fleet report.')
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [selectedFleetId, range],
  )

  useEffect(() => {
    const controller = new AbortController()
    fetchReport(controller.signal)
    return () => controller.abort()
  }, [fetchReport])

  const accountOptions = [
    { value: '', label: accountsLoading ? 'Loading fleet accounts…' : 'Select a fleet account…' },
    ...accounts.map((a) => ({ value: a.id, label: a.name })),
  ]

  const vehicles = data?.vehicles ?? []
  const hasVehicles = vehicles.length > 0

  return (
    <div data-print-content>
      <p className="text-sm text-muted mb-4 no-print">
        Fleet account report showing total spend, vehicles serviced, and outstanding balance.
      </p>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end mb-6 no-print">
        <div className="w-72">
          <Select
            label="Fleet Account"
            value={selectedFleetId}
            onChange={(e) => setSelectedFleetId(e.target.value)}
            options={accountOptions}
            disabled={accountsLoading || accounts.length === 0}
            error={accountsError || undefined}
          />
        </div>
        <DateRangeFilter value={range} onChange={setRange} />
      </div>

      {!accountsLoading && !accountsError && accounts.length === 0 && (
        <div className="mb-4 rounded-ctl border border-border bg-card px-4 py-3 text-sm text-muted">
          No fleet accounts available. Create one from Customers → Fleet Accounts.
        </div>
      )}

      {!selectedFleetId && !accountsLoading && accounts.length > 0 && (
        <div className="rounded-card border border-border bg-card p-8 text-center text-sm text-muted shadow-card">
          Select a fleet account to view its report.
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-ctl border border-danger-soft bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="py-16">
          <Spinner label="Loading fleet report" />
        </div>
      )}

      {!loading && selectedFleetId && data && (
        <>
          {data.fleet_name && (
            <h3 className="text-lg font-medium text-text mb-4">{data.fleet_name}</h3>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Total Spend</p>
              <p className="text-2xl font-semibold text-text mono">{fmt(data.total_spend)}</p>
            </div>
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Vehicles Serviced</p>
              <p className="text-2xl font-semibold text-text mono">{data.vehicles_serviced ?? 0}</p>
            </div>
            <div className="rounded-card border border-border bg-card p-4 shadow-card">
              <p className="text-sm text-muted">Outstanding Balance</p>
              <p className="text-2xl font-semibold text-danger mono">{fmt(data.outstanding_balance)}</p>
            </div>
          </div>

          <div className="flex justify-end mb-4">
            <div className="flex items-center gap-2 no-print">
              <ExportButtons
                endpoint={`/reports/fleet/${selectedFleetId}`}
                params={{ start_date: range.from, end_date: range.to }}
              />
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
                {!hasVehicles ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-muted">
                      No vehicles serviced in this period.
                    </td>
                  </tr>
                ) : (
                  vehicles.map((v, i) => (
                    <tr key={v.rego ?? i} className="border-b border-border last:border-b-0 hover:bg-canvas">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-text mono">{v.rego ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{v.make ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted">{v.model ?? '—'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-text text-right mono">{fmt(v.total_spend)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted mono">
                        {fmtDate(v.last_service_date)}
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
