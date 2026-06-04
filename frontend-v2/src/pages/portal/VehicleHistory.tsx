import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/api/client'
import { Badge, Spinner, AlertBanner } from '@/components/ui'
import { usePortalLocale } from './PortalLocaleContext'
import { formatCurrency, formatDate } from './portalFormatters'
import { getInspectionLabel, getInspectionExpiry } from '@/utils/vehicleHelpers'

export interface PortalVehicle {
  rego: string
  make: string | null
  model: string | null
  year: number | null
  colour: string | null
  wof_expiry: string | null
  cof_expiry: string | null
  inspection_type: string | null
  rego_expiry: string | null
  service_history: VehicleService[]
}

interface VehicleService {
  invoice_number: string
  date: string
  description: string
  total: number
}

interface PortalVehiclesResponse {
  branding: unknown
  vehicles: PortalVehicle[]
}

interface VehicleHistoryProps {
  token: string
}

export function VehicleHistory({ token }: VehicleHistoryProps) {
  const locale = usePortalLocale()
  const [vehicles, setVehicles] = useState<PortalVehicle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchVehicles = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get<PortalVehiclesResponse>(`/portal/${token}/vehicles`)
      setVehicles(res.data?.vehicles ?? [])
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
      <p className="py-8 text-center text-sm text-muted">
        No vehicles found.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {vehicles.map((vehicle) => (
        <VehicleCard key={vehicle.rego} vehicle={vehicle} locale={locale} />
      ))}
    </div>
  )
}

function VehicleCard({ vehicle, locale }: { vehicle: PortalVehicle; locale: string }) {
  const [expanded, setExpanded] = useState(false)

  const vehicleTitle = [vehicle.year, vehicle.make, vehicle.model]
    .filter(Boolean)
    .join(' ')

  const serviceHistory = vehicle.service_history ?? []

  return (
    <div className="rounded-card border border-border bg-card shadow-card">
      {/* Vehicle header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between p-4 text-left hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset rounded-card"
        aria-expanded={expanded}
        aria-controls={`vehicle-${vehicle.rego}-services`}
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="mono text-sm font-semibold text-text">
              {vehicle.rego}
            </span>
            {vehicle.colour && (
              <span className="text-xs text-muted-2">{vehicle.colour}</span>
            )}
          </div>
          <p className="mt-0.5 text-sm text-muted">{vehicleTitle || 'Unknown vehicle'}</p>
        </div>

        <div className="flex items-center gap-3">
          {/* Expiry badges */}
          <div className="hidden sm:flex sm:gap-2">
            {getInspectionExpiry(vehicle) != null && (
              <ExpiryBadge label={getInspectionLabel(vehicle).replace(' Expiry', '')} date={getInspectionExpiry(vehicle)!} locale={locale} />
            )}
            {vehicle.rego_expiry != null && (
              <ExpiryBadge label="Rego" date={vehicle.rego_expiry} locale={locale} />
            )}
          </div>

          <span className="text-sm text-muted-2" aria-hidden="true">
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </button>

      {/* Mobile expiry badges */}
      {(getInspectionExpiry(vehicle) != null || vehicle.rego_expiry != null) && (
        <div className="flex gap-2 px-4 pb-2 sm:hidden">
          {getInspectionExpiry(vehicle) != null && <ExpiryBadge label={getInspectionLabel(vehicle).replace(' Expiry', '')} date={getInspectionExpiry(vehicle)!} locale={locale} />}
          {vehicle.rego_expiry != null && <ExpiryBadge label="Rego" date={vehicle.rego_expiry} locale={locale} />}
        </div>
      )}

      {/* Service history */}
      {expanded && (
        <div
          id={`vehicle-${vehicle.rego}-services`}
          className="border-t border-border px-4 py-3"
        >
          {serviceHistory.length === 0 ? (
            <p className="text-sm text-muted">No service history.</p>
          ) : (
            <table className="w-full text-sm" role="table">
              <caption className="sr-only">Service history for {vehicle.rego}</caption>
              <thead>
                <tr className="text-left text-xs font-medium uppercase text-muted-2">
                  <th scope="col" className="pb-2">Date</th>
                  <th scope="col" className="pb-2">Invoice</th>
                  <th scope="col" className="pb-2">Description</th>
                  <th scope="col" className="pb-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {serviceHistory.map((svc, idx) => (
                  <tr key={idx}>
                    <td className="py-2 mono text-muted">{formatDate(svc.date, locale)}</td>
                    <td className="py-2 mono text-muted">{svc.invoice_number}</td>
                    <td className="py-2 text-muted truncate max-w-[200px]">{svc.description}</td>
                    <td className="py-2 text-right mono tabular-nums text-text">{formatCurrency(svc.total ?? 0, locale)}</td>
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

function ExpiryBadge({ label, date, locale }: { label: string; date: string; locale: string }) {
  const daysUntil = Math.ceil(
    (new Date(date).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
  )

  let variant: 'success' | 'warn' | 'danger' = 'success'
  if (daysUntil < 30) variant = 'danger'
  else if (daysUntil < 60) variant = 'warn'

  return (
    <Badge variant={variant}>
      {label}: {formatDate(date, locale)}
    </Badge>
  )
}
