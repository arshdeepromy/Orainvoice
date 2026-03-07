import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'

export interface PortalVehicle {
  id: string
  rego: string
  make: string
  model: string
  year: number | null
  colour: string | null
  wof_expiry: string | null
  rego_expiry: string | null
  services: VehicleService[]
}

interface VehicleService {
  invoice_number: string
  date: string
  description: string
  total: number
}

interface VehicleHistoryProps {
  token: string
}

export function VehicleHistory({ token }: VehicleHistoryProps) {
  const [vehicles, setVehicles] = useState<PortalVehicle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchVehicles = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<PortalVehicle[]>(`/portal/${token}/vehicles`)
      setVehicles(res.data)
    } catch {
      setError('Failed to load vehicle history.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    fetchVehicles()
  }, [fetchVehicles])

  if (loading) {
    return (
      <div className="py-8">
        <Spinner label="Loading vehicles" />
      </div>
    )
  }

  if (error) {
    return <AlertBanner variant="error">{error}</AlertBanner>
  }

  if (vehicles.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-gray-500">
        No vehicles found.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {vehicles.map((vehicle) => (
        <VehicleCard key={vehicle.id} vehicle={vehicle} />
      ))}
    </div>
  )
}

function VehicleCard({ vehicle }: { vehicle: PortalVehicle }) {
  const [expanded, setExpanded] = useState(false)

  const vehicleTitle = [vehicle.year, vehicle.make, vehicle.model]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      {/* Vehicle header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between p-4 text-left hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset rounded-lg"
        aria-expanded={expanded}
        aria-controls={`vehicle-${vehicle.id}-services`}
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-gray-900">
              {vehicle.rego}
            </span>
            {vehicle.colour && (
              <span className="text-xs text-gray-400">{vehicle.colour}</span>
            )}
          </div>
          <p className="mt-0.5 text-sm text-gray-600">{vehicleTitle || 'Unknown vehicle'}</p>
        </div>

        <div className="flex items-center gap-3">
          {/* Expiry badges */}
          <div className="hidden sm:flex sm:gap-2">
            {vehicle.wof_expiry && (
              <ExpiryBadge label="WOF" date={vehicle.wof_expiry} />
            )}
            {vehicle.rego_expiry && (
              <ExpiryBadge label="Rego" date={vehicle.rego_expiry} />
            )}
          </div>

          <span className="text-sm text-gray-400" aria-hidden="true">
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </button>

      {/* Mobile expiry badges */}
      {(vehicle.wof_expiry || vehicle.rego_expiry) && (
        <div className="flex gap-2 px-4 pb-2 sm:hidden">
          {vehicle.wof_expiry && <ExpiryBadge label="WOF" date={vehicle.wof_expiry} />}
          {vehicle.rego_expiry && <ExpiryBadge label="Rego" date={vehicle.rego_expiry} />}
        </div>
      )}

      {/* Service history */}
      {expanded && (
        <div
          id={`vehicle-${vehicle.id}-services`}
          className="border-t border-gray-100 px-4 py-3"
        >
          {vehicle.services.length === 0 ? (
            <p className="text-sm text-gray-500">No service history.</p>
          ) : (
            <table className="w-full text-sm" role="table">
              <caption className="sr-only">Service history for {vehicle.rego}</caption>
              <thead>
                <tr className="text-left text-xs font-medium uppercase text-gray-400">
                  <th scope="col" className="pb-2">Date</th>
                  <th scope="col" className="pb-2">Invoice</th>
                  <th scope="col" className="pb-2">Description</th>
                  <th scope="col" className="pb-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {vehicle.services.map((svc, idx) => (
                  <tr key={idx}>
                    <td className="py-2 text-gray-600">{formatDate(svc.date)}</td>
                    <td className="py-2 font-mono text-gray-700">{svc.invoice_number}</td>
                    <td className="py-2 text-gray-600 truncate max-w-[200px]">{svc.description}</td>
                    <td className="py-2 text-right tabular-nums text-gray-900">{formatNZD(svc.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function ExpiryBadge({ label, date }: { label: string; date: string }) {
  const daysUntil = Math.ceil(
    (new Date(date).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
  )

  let variant: 'success' | 'warning' | 'error' = 'success'
  if (daysUntil < 30) variant = 'error'
  else if (daysUntil < 60) variant = 'warning'

  return (
    <Badge variant={variant}>
      {label}: {formatDate(date)}
    </Badge>
  )
}

function formatNZD(amount: number): string {
  return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(amount)
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}
