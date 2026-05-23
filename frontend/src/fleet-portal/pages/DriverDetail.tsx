/**
 * Driver detail page — vehicle assignments + activity view.
 *
 * Implements: B2B Fleet Portal — Requirements 5.5, 5.6, 14.1–14.5.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { listVehicles } from '../api/endpoints'
import type { DriverListItem, VehicleListItem, DriverActivityVehicleRow } from '../api/types'

interface DriverActivityResponse {
  portal_account_id: string
  date_from: string
  date_to: string
  rows: DriverActivityVehicleRow[]
  total_submissions: number
  total_failures: number
  total_odometer_logs: number
  total_hours_logs: number
}

export default function DriverDetail() {
  const { driverId } = useParams<{ driverId: string }>()
  const [driver, setDriver] = useState<DriverListItem | null>(null)
  const [vehicles, setVehicles] = useState<VehicleListItem[]>([])
  const [assignedIds, setAssignedIds] = useState<Set<string>>(new Set())
  const [activity, setActivity] = useState<DriverActivityResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [dateRange, setDateRange] = useState('30')

  const fetchData = async () => {
    if (!driverId) return
    try {
      const [driversRes, vehiclesRes, activityRes] = await Promise.all([
        fleetClient.get<{ items: DriverListItem[] }>('/drivers', { params: { limit: 100 } }),
        listVehicles(0, 100),
        fleetClient.get<DriverActivityResponse>(`/drivers/${driverId}/activity`, { params: { date_from: getDateFrom(dateRange) } }),
      ])
      const d = (driversRes.data?.items ?? []).find(x => x.portal_account_id === driverId)
      setDriver(d ?? null)
      setVehicles(vehiclesRes.items ?? [])
      setActivity(activityRes.data ?? null)
      // TODO: fetch actual assignments — for now derive from activity
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [driverId, dateRange])

  const assignVehicle = async (vehicleId: string) => {
    try {
      await fleetClient.post(`/drivers/${driverId}/assignments`, { customer_vehicle_id: vehicleId })
      setAssignedIds(prev => new Set([...prev, vehicleId]))
    } catch {}
  }

  const unassignVehicle = async (vehicleId: string) => {
    try {
      await fleetClient.delete(`/drivers/${driverId}/assignments/${vehicleId}`)
      setAssignedIds(prev => { const n = new Set(prev); n.delete(vehicleId); return n })
    } catch {}
  }

  const exportCsv = () => {
    if (!activity?.rows?.length) return
    const header = 'Date,Vehicle,Rego,Submissions,Failures,Odometer Logs,Hours Logs\n'
    const rows = (activity.rows ?? []).map(r =>
      `${r.date},${r.customer_vehicle_id},${r.rego},${r.submissions_count},${r.failures_count},${r.odometer_log_count},${r.hours_log_count}`
    ).join('\n')
    const blob = new Blob([header + rows], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `driver-activity-${driverId}.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>
  if (!driver) return <div className="p-4"><Link to="/fleet/drivers" className="text-sm text-indigo-600 hover:underline">← Back</Link><p className="mt-2 text-sm text-gray-500">Driver not found.</p></div>

  return (
    <div className="space-y-6">
      <Link to="/fleet/drivers" className="text-sm text-indigo-600 hover:underline">← Back to drivers</Link>

      {/* Driver info */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{[driver.first_name, driver.last_name].filter(Boolean).join(' ')}</h1>
          <p className="text-sm text-gray-500">{driver.email}</p>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${driver.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
          {driver.is_active ? 'Active' : 'Inactive'}
        </span>
      </div>

      {/* Vehicle assignments */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-sm font-medium mb-3">Vehicle Assignments</h2>
        <p className="text-xs text-gray-500 mb-3">Toggle vehicles this driver can access.</p>
        <div className="space-y-2">
          {(vehicles ?? []).map(v => {
            const isAssigned = assignedIds.has(v.customer_vehicle_id) || (driver.assigned_vehicle_count ?? 0) > 0
            return (
              <div key={v.customer_vehicle_id} className="flex items-center justify-between rounded border border-gray-100 px-3 py-2 dark:border-gray-800">
                <span className="text-sm">{v.rego} — {v.make} {v.model}</span>
                <button
                  onClick={() => isAssigned ? unassignVehicle(v.customer_vehicle_id) : assignVehicle(v.customer_vehicle_id)}
                  className={`text-xs px-3 py-1.5 rounded min-h-[44px] font-medium ${isAssigned ? 'bg-red-100 text-red-700 hover:bg-red-200' : 'bg-green-100 text-green-700 hover:bg-green-200'}`}
                >
                  {isAssigned ? 'Unassign' : 'Assign'}
                </button>
              </div>
            )
          })}
        </div>
      </div>

      {/* Activity */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium">Activity</h2>
          <div className="flex items-center gap-2">
            <select value={dateRange} onChange={e => setDateRange(e.target.value)} className="rounded border border-gray-300 px-2 py-1 text-xs min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white">
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
            </select>
            <button onClick={exportCsv} disabled={!(activity?.rows?.length)} className="rounded border border-gray-300 px-2 py-1 text-xs min-h-[44px] hover:bg-gray-50 disabled:opacity-30 dark:border-gray-700">
              📥 CSV
            </button>
          </div>
        </div>

        {activity && (
          <div className="grid grid-cols-2 gap-3 mb-4 sm:grid-cols-4">
            <Stat label="Submissions" value={activity.total_submissions ?? 0} />
            <Stat label="Failures" value={activity.total_failures ?? 0} accent="red" />
            <Stat label="Odometer Logs" value={activity.total_odometer_logs ?? 0} />
            <Stat label="Hours Logs" value={activity.total_hours_logs ?? 0} />
          </div>
        )}

        {(activity?.rows ?? []).length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead><tr className="text-gray-500 uppercase">
                <th className="px-2 py-1 text-left">Date</th>
                <th className="px-2 py-1 text-left">Vehicle</th>
                <th className="px-2 py-1 text-right">Submissions</th>
                <th className="px-2 py-1 text-right">Failures</th>
                <th className="px-2 py-1 text-right">Hours</th>
              </tr></thead>
              <tbody>
                {(activity?.rows ?? []).map((r, i) => (
                  <tr key={i} className="border-t border-gray-100 dark:border-gray-800">
                    <td className="px-2 py-1">{r.date}</td>
                    <td className="px-2 py-1">{r.rego}</td>
                    <td className="px-2 py-1 text-right">{r.submissions_count}</td>
                    <td className="px-2 py-1 text-right">{r.failures_count > 0 ? <span className="text-red-600">{r.failures_count}</span> : '0'}</td>
                    <td className="px-2 py-1 text-right">{r.hours_log_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-gray-400">No activity in this period.</p>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="rounded border border-gray-100 p-2 dark:border-gray-800">
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-lg font-semibold ${accent === 'red' ? 'text-red-600' : 'text-gray-900 dark:text-white'}`}>{(value ?? 0).toLocaleString()}</p>
    </div>
  )
}

function getDateFrom(days: string): string {
  const d = new Date()
  d.setDate(d.getDate() - parseInt(days, 10))
  return d.toISOString().split('T')[0]
}
