/**
 * Fleet Portal vehicle list (admin and driver).
 *
 * Implements: B2B Fleet Portal task 15.1 — Requirements 6.1–6.4, 6.5, 7.1, 7.8.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { listVehicles } from '../api/endpoints'
import type { VehicleListItem } from '../api/types'
import { ExpiryBadge } from '../components/ExpiryBadge'
import { useFleetSession } from '../contexts/FleetSessionContext'

export default function VehicleList() {
  const { user } = useFleetSession()
  const isAdmin = user?.portal_user_role === 'fleet_admin'
  const [items, setItems] = useState<VehicleListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchVehicles = async () => {
    try {
      const page = await listVehicles(0, 50)
      setItems(page.items ?? [])
      setTotal(page.total ?? 0)
    } catch {
      setError('Failed to load vehicles.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const page = await listVehicles(0, 50, { signal: controller.signal })
        setItems(page.items ?? [])
        setTotal(page.total ?? 0)
      } catch {
        if (!controller.signal.aborted) setError('Failed to load vehicles.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>
  if (error)
    return (
      <div
        className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
        role="alert"
      >
        {error}
      </div>
    )

  if ((items ?? []).length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">Vehicles</h1>
          {isAdmin && <AddVehicleButton onAdded={fetchVehicles} />}
        </div>
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <h2 className="text-lg font-semibold mb-2">No vehicles</h2>
          <p className="text-sm text-gray-500">
            {isAdmin
              ? 'Add your first vehicle to get started.'
              : 'Vehicles linked to your fleet will appear here.'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Vehicles</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">{(total ?? 0).toLocaleString()} total</span>
          {isAdmin && <AddVehicleButton onAdded={fetchVehicles} />}
        </div>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-800 text-sm">
          <thead className="bg-gray-50 dark:bg-gray-900">
            <tr>
              <Th>Rego</Th>
              <Th>Make / Model</Th>
              <Th>Year</Th>
              <Th>Odometer</Th>
              <Th>WOF</Th>
              <Th>COF</Th>
              <Th>Service</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-800 bg-white dark:bg-gray-950">
            {(items ?? []).map((v) => (
              <tr key={v.customer_vehicle_id}>
                <td className="px-3 py-2 font-medium">
                  <Link
                    to={`/fleet/vehicles/${v.customer_vehicle_id}`}
                    className="text-brand-600 hover:underline dark:text-brand-400"
                  >
                    {v.rego}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  {[v.make, v.model].filter(Boolean).join(' ') || '—'}
                </td>
                <td className="px-3 py-2">{v.year ?? '—'}</td>
                <td className="px-3 py-2 tabular-nums">
                  {v.odometer_last_recorded != null
                    ? `${(v.odometer_last_recorded ?? 0).toLocaleString()} km`
                    : '—'}
                </td>
                <td className="px-3 py-2">
                  <ExpiryBadge colour={v.wof_badge ?? null} />
                </td>
                <td className="px-3 py-2">
                  <ExpiryBadge colour={v.cof_badge ?? null} />
                </td>
                <td className="px-3 py-2">
                  <ExpiryBadge colour={v.service_badge ?? null} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th
      scope="col"
      className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500"
    >
      {children}
    </th>
  )
}

function AddVehicleButton({ onAdded }: { onAdded: () => void }) {
  const [show, setShow] = useState(false)
  const [rego, setRego] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!rego.trim()) { setError('Enter a registration number.'); return }
    setSubmitting(true); setError(null)
    try {
      await fleetClient.post('/vehicles', { rego: rego.trim().toUpperCase(), odometer_at_link: null })
      setShow(false)
      setRego('')
      onAdded()
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to add vehicle.')
    } finally { setSubmitting(false) }
  }

  if (!show) {
    return (
      <button onClick={() => setShow(true)} className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white min-h-[44px] hover:bg-indigo-700">
        + Add Vehicle
      </button>
    )
  }

  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-red-600">{error}</span>}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input type="text" value={rego} onChange={e => setRego(e.target.value)} placeholder="Rego (e.g. ABC123)"
          className="w-32 rounded-md border border-gray-300 px-2 py-1.5 text-sm min-h-[44px] uppercase dark:border-gray-700 dark:bg-gray-900 dark:text-white" autoFocus />
        <button type="submit" disabled={submitting} className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white min-h-[44px] disabled:opacity-50">
          {submitting ? '…' : 'Add'}
        </button>
        <button type="button" onClick={() => { setShow(false); setError(null) }} className="rounded-md border border-gray-300 px-3 py-1.5 text-sm min-h-[44px] dark:border-gray-700">
          ✕
        </button>
      </form>
    </div>
  )
}
