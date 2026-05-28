/**
 * QuoteMultiVehicleSection — allows adding multiple vehicles to a quote.
 * Gated on isAutomotive && isEnabled('vehicles') in the parent.
 * Task 12.1
 */

import { useState } from 'react'

interface VehicleEntry {
  rego?: string
  make?: string
  model?: string
  year?: number | null
  odometer?: number | null
  wof_expiry?: string | null
  cof_expiry?: string | null
}

interface QuoteMultiVehicleSectionProps {
  vehicles: VehicleEntry[]
  onChange: (vehicles: VehicleEntry[]) => void
}

export default function QuoteMultiVehicleSection({ vehicles, onChange }: QuoteMultiVehicleSectionProps) {
  const [expanded, setExpanded] = useState(vehicles.length > 0)

  const addVehicle = () => {
    onChange([...vehicles, { rego: '', make: '', model: '', year: null }])
    setExpanded(true)
  }

  const removeVehicle = (index: number) => {
    onChange(vehicles.filter((_, i) => i !== index))
  }

  const updateVehicle = (index: number, field: keyof VehicleEntry, value: string | number | null) => {
    const updated = [...vehicles]
    updated[index] = { ...updated[index], [field]: value }
    onChange(updated)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-gray-700">Additional Vehicles</label>
        <button
          type="button"
          onClick={addVehicle}
          className="text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          + Add Vehicle
        </button>
      </div>

      {expanded && vehicles.length > 0 && (
        <div className="space-y-2">
          {vehicles.map((v, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md border border-gray-200 p-2">
              <input
                type="text"
                value={v.rego ?? ''}
                onChange={(e) => updateVehicle(i, 'rego', e.target.value)}
                placeholder="Rego"
                className="w-24 rounded border border-gray-300 px-2 py-1 text-sm"
              />
              <input
                type="text"
                value={v.make ?? ''}
                onChange={(e) => updateVehicle(i, 'make', e.target.value)}
                placeholder="Make"
                className="w-24 rounded border border-gray-300 px-2 py-1 text-sm"
              />
              <input
                type="text"
                value={v.model ?? ''}
                onChange={(e) => updateVehicle(i, 'model', e.target.value)}
                placeholder="Model"
                className="w-24 rounded border border-gray-300 px-2 py-1 text-sm"
              />
              <input
                type="number"
                value={v.year ?? ''}
                onChange={(e) => updateVehicle(i, 'year', e.target.value ? Number(e.target.value) : null)}
                placeholder="Year"
                className="w-20 rounded border border-gray-300 px-2 py-1 text-sm"
              />
              <button
                type="button"
                onClick={() => removeVehicle(i)}
                className="rounded px-2 py-1 text-xs text-red-500 hover:bg-red-50"
                title="Remove vehicle"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
