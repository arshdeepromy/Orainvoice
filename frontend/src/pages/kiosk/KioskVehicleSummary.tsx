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
    <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 text-center shadow-lg">
      {/* Vehicle count badge */}
      {vehicleCount > 0 && (
        <div className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800">
          {vehicleCount} vehicle{vehicleCount !== 1 ? 's' : ''} added
        </div>
      )}

      {/* Title with rego prominently displayed */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Vehicle Found</h1>
        <p className="mt-2 text-xl font-semibold tracking-wider text-blue-600">
          {vehicle.rego}
        </p>
      </div>

      {/* Vehicle details card */}
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-left">
        <dl className="space-y-2">
          {vehicle.body_type != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-gray-500">Type</dt>
              <dd className="text-lg font-medium text-gray-900">{vehicle.body_type}</dd>
            </div>
          )}

          {(vehicle.make != null || vehicle.model != null) && (
            <div className="flex justify-between">
              <dt className="text-lg text-gray-500">Vehicle</dt>
              <dd className="text-lg font-medium text-gray-900">
                {[vehicle.make, vehicle.model].filter(Boolean).join(' ')}
              </dd>
            </div>
          )}

          {getInspectionExpiry(vehicle) != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-gray-500">{getInspectionLabel(vehicle)}</dt>
              <dd className="text-lg font-medium text-gray-900">{getInspectionExpiry(vehicle)}</dd>
            </div>
          )}

          {vehicle.rego_expiry != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-gray-500">Rego Expiry</dt>
              <dd className="text-lg font-medium text-gray-900">{vehicle.rego_expiry}</dd>
            </div>
          )}

          {vehicle.odometer != null && (
            <div className="flex justify-between">
              <dt className="text-lg text-gray-500">Last Recorded KM</dt>
              <dd className="text-lg font-medium text-gray-900">
                {(vehicle.odometer ?? 0).toLocaleString()} km
              </dd>
            </div>
          )}
        </dl>
      </div>

      {/* Odometer input */}
      <div className="space-y-2 text-left">
        <label htmlFor="odometer-input" className="block text-lg font-medium text-gray-700">
          Current Kilometers <span className="text-sm font-normal text-gray-400">(optional)</span>
        </label>
        <input
          id="odometer-input"
          type="number"
          value={odometerInput}
          onChange={(e) => setOdometerInput(e.target.value)}
          placeholder="e.g. 85000"
          min={0}
          aria-label="Current Kilometers"
          className="w-full min-h-[48px] rounded-lg border border-gray-300 px-4 py-3 text-lg focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Action buttons */}
      <div className="space-y-3">
        {/* Confirm button */}
        <button
          type="button"
          onClick={handleConfirm}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-lg bg-blue-600 px-6 py-3 text-lg font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Confirm
        </button>

        {/* Add Another Vehicle button */}
        <button
          type="button"
          onClick={handleAddAnother}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-lg border border-gray-300 bg-white px-6 py-3 text-lg font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Add Another Vehicle
        </button>

        {/* Back button */}
        <button
          type="button"
          onClick={onBack}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-lg px-6 py-3 text-lg font-medium text-gray-500 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Back
        </button>
      </div>
    </div>
  )
}

export default KioskVehicleSummary
