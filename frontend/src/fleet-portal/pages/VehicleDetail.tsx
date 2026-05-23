/**
 * Fleet Portal vehicle detail page.
 *
 * Implements: B2B Fleet Portal — Requirements 6.2, 6.5, 6.6, 6.7, 7.2, 7.5–7.8.
 */
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { getVehicleDetail } from '../api/endpoints'
import type { VehicleDetail as VehicleDetailType } from '../api/types'
import { ExpiryBadge } from '../components/ExpiryBadge'
import { useFleetSession } from '../contexts/FleetSessionContext'

export default function VehicleDetail() {
  const { vehicleId } = useParams<{ vehicleId: string }>()
  const { user } = useFleetSession()
  const [vehicle, setVehicle] = useState<VehicleDetailType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const isAdmin = user?.portal_user_role === 'fleet_admin'

  const fetchVehicle = async () => {
    if (!vehicleId) return
    try {
      const data = await getVehicleDetail(vehicleId)
      setVehicle(data)
    } catch {
      setError('Failed to load vehicle details.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const data = await getVehicleDetail(vehicleId!, { signal: controller.signal })
        setVehicle(data)
      } catch {
        if (!controller.signal.aborted) setError('Failed to load vehicle details.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    if (vehicleId) void load()
    return () => controller.abort()
  }, [vehicleId])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading…</div>
  if (error || !vehicle) {
    return (
      <div className="space-y-4">
        <Link to="/fleet/vehicles" className="text-sm text-indigo-600 hover:underline">← Back to vehicles</Link>
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
          {error || 'Vehicle not found.'}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/fleet/vehicles" className="text-sm text-indigo-600 hover:underline">← Back to vehicles</Link>
          <h1 className="mt-2 text-xl font-semibold text-gray-900 dark:text-white">{vehicle.rego}</h1>
          <p className="text-sm text-gray-500">{[vehicle.make, vehicle.model, vehicle.year].filter(Boolean).join(' ')}</p>
        </div>
        {isAdmin && (
          <button onClick={async () => {
            if (!confirm(`Remove ${vehicle.rego} from your fleet? This does not delete the vehicle record.`)) return
            try { await fleetClient.delete(`/vehicles/${vehicleId}`); window.location.href = '/fleet/vehicles' } catch {}
          }} className="rounded-md border border-red-300 px-3 py-2 text-xs font-medium text-red-700 min-h-[44px] hover:bg-red-50 dark:border-red-800 dark:text-red-400">
            Remove from fleet
          </button>
        )}
      </div>

      {/* Status badges */}
      <div className="flex flex-wrap gap-3">
        <Badge label="WOF" colour={vehicle.wof_badge} date={vehicle.wof_expiry} />
        <Badge label="COF" colour={vehicle.cof_badge} date={vehicle.cof_expiry} />
        <Badge label="Service" colour={vehicle.service_badge} date={vehicle.service_due_date} />
      </div>

      {/* Vehicle info */}
      <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
        <h2 className="mb-3 text-sm font-medium text-gray-900 dark:text-white">Vehicle Information</h2>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Registration" value={vehicle.rego} />
          <Field label="Make" value={vehicle.make} />
          <Field label="Model" value={vehicle.model} />
          <Field label="Year" value={vehicle.year?.toString()} />
          <Field label="Colour" value={vehicle.colour} />
          <Field label="VIN" value={vehicle.vin} />
          <Field label="Chassis" value={vehicle.chassis} />
          <Field label="Engine No" value={vehicle.engine_no} />
          <Field label="Odometer" value={vehicle.odometer_last_recorded != null ? `${(vehicle.odometer_last_recorded ?? 0).toLocaleString()} km` : undefined} />
          <Field label="WOF Expiry" value={vehicle.wof_expiry} />
          <Field label="COF Expiry" value={vehicle.cof_expiry} />
          <Field label="Reg Expiry" value={vehicle.registration_expiry} />
          <Field label="Service Due" value={vehicle.service_due_date} />
        </dl>
      </div>

      {/* Action forms */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <OdometerForm vehicleId={vehicleId!} currentMax={vehicle.odometer_last_recorded ?? 0} onSuccess={fetchVehicle} />
        <HoursForm vehicleId={vehicleId!} onSuccess={() => {}} />
      </div>
    </div>
  )
}

/* --- Sub-components --- */

function Badge({ label, colour, date }: { label: string; colour: string | null; date: string | null }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-gray-500 uppercase">{label}</span>
      <ExpiryBadge colour={colour as 'red' | 'amber' | 'green' | null} />
      {date && <span className="text-xs text-gray-500">{date}</span>}
    </div>
  )
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500 uppercase">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-900 dark:text-white">{value || '—'}</dd>
    </div>
  )
}

function OdometerForm({ vehicleId, currentMax, onSuccess }: { vehicleId: string; currentMax: number; onSuccess: () => void }) {
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const km = parseInt(value, 10)
    if (isNaN(km) || km <= 0) { setMsg({ type: 'err', text: 'Enter a valid number.' }); return }
    if (km <= currentMax) { setMsg({ type: 'err', text: `Must be greater than ${currentMax.toLocaleString()} km.` }); return }
    setSubmitting(true)
    setMsg(null)
    try {
      await fleetClient.post(`/vehicles/${vehicleId}/odometer`, { odometer_km: km })
      setMsg({ type: 'ok', text: `Recorded ${km.toLocaleString()} km` })
      setValue('')
      onSuccess()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to log odometer.'
      setMsg({ type: 'err', text: detail })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
      <h3 className="text-sm font-medium mb-2">Log Odometer Reading</h3>
      <p className="text-xs text-gray-500 mb-3">Current: {currentMax.toLocaleString()} km</p>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input type="number" value={value} onChange={e => setValue(e.target.value)} placeholder="km" min={currentMax + 1}
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <button type="submit" disabled={submitting}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700">
          {submitting ? '…' : 'Log'}
        </button>
      </form>
      {msg && <p className={`mt-2 text-xs ${msg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>{msg.text}</p>}
    </div>
  )
}

function HoursForm({ vehicleId, onSuccess }: { vehicleId: string; onSuccess: () => void }) {
  const [startAt, setStartAt] = useState('')
  const [endAt, setEndAt] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!startAt || !endAt) { setMsg({ type: 'err', text: 'Start and end times are required.' }); return }
    setSubmitting(true)
    setMsg(null)
    try {
      await fleetClient.post(`/vehicles/${vehicleId}/hours`, {
        start_at: new Date(startAt).toISOString(),
        end_at: new Date(endAt).toISOString(),
        notes: notes.trim() || null,
      })
      setMsg({ type: 'ok', text: 'Hours logged successfully.' })
      setStartAt('')
      setEndAt('')
      setNotes('')
      onSuccess()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to log hours.'
      setMsg({ type: 'err', text: detail })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-950">
      <h3 className="text-sm font-medium mb-2">Log Driving Hours</h3>
      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-gray-500">Start</label>
            <input type="datetime-local" value={startAt} onChange={e => setStartAt(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
          </div>
          <div>
            <label className="text-xs text-gray-500">End</label>
            <input type="datetime-local" value={endAt} onChange={e => setEndAt(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
          </div>
        </div>
        <input type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notes (optional)"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm min-h-[44px] dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
        <button type="submit" disabled={submitting}
          className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white min-h-[44px] disabled:opacity-50 hover:bg-indigo-700">
          {submitting ? 'Logging…' : 'Log Hours'}
        </button>
      </form>
      {msg && <p className={`mt-2 text-xs ${msg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>{msg.text}</p>}
    </div>
  )
}
