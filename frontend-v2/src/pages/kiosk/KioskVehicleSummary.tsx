import { useState } from 'react'
import type { VehicleLookupResult } from './types'
import { getInspectionLabel, getInspectionExpiry } from '@/utils/vehicleHelpers'

/* ── Types ── */

interface KioskVehicleSummaryProps {
  vehicle: VehicleLookupResult
  vehicleCount: number
  onConfirm: (odometer_km: number | null) => void
  onAddAnother: () => void
  onBack: () => void
}

/* ── KioskVehicleSummary ── */

export function KioskVehicleSummary({
  vehicle,
  vehicleCount,
  onConfirm,
  onAddAnother,
  onBack,
}: KioskVehicleSummaryProps) {
  const [odometerInput, setOdometerInput] = useState('')

  const handleConfirm = () => {
    const value = odometerInput.trim()
    const odometer = value ? Number(value) : null
    onConfirm(odometer)
  }

  const handleAddAnother = () => {
    const value = odometerInput.trim()
    const odometer = value ? Number(value) : null
    onConfirm(odometer)
    onAddAnother()
  }

  return (
    <div className="w-full max-w-md space-y-6 rounded-card bg-card p-8 text-center shadow-pop">
      {/* Vehicle count badge */}
      {vehicleCount > 0 && (
        <div className="inline-flex items-center rounded-full bg-ok-soft px-3 py-1 text-sm font-medium text-ok">
          {vehicleCount} vehicle{vehicleCount !== 1 ? 's' : ''} added
        </div>
      )}

      {/* Title with rego prominently displayed */}
      <div>
        <h1 className="text-2xl font-bold text-text">Vehicle Found</h1>
        <p className="mono mt-2 text-xl font-semibold tracking-wider text-accent">
          {vehicle.rego}
        </p>
      </div>

      {/* Vehicle details card */}
      <div className="rounded-ctl border border-border bg-canvas p-4 text-left">
        <dl className="space-y-2">
          {vehicle.body_type != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-muted">Type</dt>
              <dd className="text-lg font-medium text-text">{vehicle.body_type}</dd>
            </div>
          )}

          {(vehicle.make != null || vehicle.model != null) && (
            <div className="flex justify-between">
              <dt className="text-lg text-muted">Vehicle</dt>
              <dd className="text-lg font-medium text-text">
                {[vehicle.make, vehicle.model].filter(Boolean).join(' ')}
              </dd>
            </div>
          )}

          {getInspectionExpiry(vehicle) != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-muted">{getInspectionLabel(vehicle)}</dt>
              <dd className="text-lg font-medium text-text">{getInspectionExpiry(vehicle)}</dd>
            </div>
          )}

          {vehicle.rego_expiry != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-muted">Rego Expiry</dt>
              <dd className="text-lg font-medium text-text">{vehicle.rego_expiry}</dd>
            </div>
          )}

          {vehicle.odometer != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-muted">Last Recorded KM</dt>
              <dd className="text-lg font-medium text-text">
                {(vehicle.odometer ?? 0).toLocaleString()} km
              </dd>
            </div>
          )}
        </dl>
      </div>

      {/* Odometer input */}
      <div className="space-y-2 text-left">
        <label htmlFor="odometer-input" className="block text-lg font-medium text-text">
          Current Kilometers <span className="text-sm font-normal text-muted-2">(optional)</span>
        </label>
        <input
          id="odometer-input"
          type="number"
          value={odometerInput}
          onChange={(e) => setOdometerInput(e.target.value)}
          placeholder="e.g. 85000"
          min={0}
          aria-label="Current Kilometers"
          className="w-full min-h-[48px] rounded-ctl border border-border-strong px-4 py-3 text-lg focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent"
        />
      </div>

      {/* Action buttons */}
      <div className="space-y-3">
        {/* Confirm button */}
        <button
          type="button"
          onClick={handleConfirm}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-ctl bg-accent px-6 py-3 text-lg font-medium text-white shadow-card hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2"
        >
          Confirm
        </button>

        {/* Add Another Vehicle button */}
        <button
          type="button"
          onClick={handleAddAnother}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-ctl border border-border-strong bg-card px-6 py-3 text-lg font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2"
        >
          Add Another Vehicle
        </button>

        {/* Back button */}
        <button
          type="button"
          onClick={onBack}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-ctl px-6 py-3 text-lg font-medium text-muted hover:text-text focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2"
        >
          Back
        </button>
      </div>
    </div>
  )
}

export default KioskVehicleSummary
