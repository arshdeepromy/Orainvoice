import { useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import type { Vehicle } from '@shared/types/vehicle'
import { useApiDetail } from '@/hooks/useApiDetail'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileButton, MobileSpinner, MobileListItem, MobileBadge } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface ServiceHistoryEntry {
  id: string
  date: string
  description: string
  status: string
  total: number | null
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function vehicleTitle(v: Vehicle): string {
  const parts = [v.year ? String(v.year) : null, v.make, v.model].filter(Boolean)
  return parts.join(' ') || v.registration || 'Unknown Vehicle'
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

function DetailRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
      <span className="text-right text-sm font-medium text-gray-900 dark:text-gray-100">
        {value}
      </span>
    </div>
  )
}

/**
 * Vehicle profile screen — full vehicle details, owner information,
 * service history.
 *
 * Requirements: 22.2
 */
export default function VehicleProfileScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: vehicle, isLoading, error, refetch } = useApiDetail<Vehicle>({
    endpoint: `/api/v1/vehicles/${id}`,
    enabled: !!id,
  })

  const serviceHistory = useApiList<ServiceHistoryEntry>({
    endpoint: `/api/v1/vehicles/${id}/service-history`,
    dataKey: 'items',
  })

  const isRefreshing = serviceHistory.isRefreshing

  const handleRefresh = useCallback(async () => {
    await Promise.all([refetch(), serviceHistory.refresh()])
  }, [refetch, serviceHistory])

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !vehicle) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">
          {error ?? 'Vehicle not found'}
        </p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  return (
    <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        {/* Back button */}
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
          aria-label="Back"
        >
          <svg
            className="h-5 w-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m15 18-6-6 6-6" />
          </svg>
          Back
        </button>

        {/* Header */}
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            {vehicleTitle(vehicle)}
          </h1>
          {vehicle.registration && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {vehicle.registration}
            </p>
          )}
        </div>

        {/* Vehicle details */}
        <MobileCard>
          <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
            Details
          </h2>
          <div className="flex flex-col gap-3">
            <DetailRow label="Registration" value={vehicle.registration} />
            <DetailRow label="Make" value={vehicle.make} />
            <DetailRow label="Model" value={vehicle.model} />
            <DetailRow label="Year" value={vehicle.year} />
            <DetailRow label="Colour" value={vehicle.colour} />
            <DetailRow label="VIN" value={vehicle.vin} />
          </div>
        </MobileCard>

        {/* Owner */}
        <MobileCard>
          <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
            Owner
          </h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            {vehicle.owner_name ?? 'Unknown'}
          </p>
        </MobileCard>

        {/* Service history */}
        <div>
          <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
            Service History
          </h2>
          {serviceHistory.isLoading ? (
            <div className="flex justify-center py-4">
              <MobileSpinner size="sm" />
            </div>
          ) : serviceHistory.items.length === 0 ? (
            <p className="py-4 text-center text-sm text-gray-400 dark:text-gray-500">
              No service history
            </p>
          ) : (
            <div className="flex flex-col">
              {serviceHistory.items.map((entry) => (
                <MobileListItem
                  key={entry.id}
                  title={entry.description ?? 'Service'}
                  subtitle={formatDate(entry.date)}
                  trailing={
                    <div className="flex flex-col items-end gap-1">
                      {entry.total !== null && (
                        <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                          {formatCurrency(entry.total)}
                        </span>
                      )}
                      <MobileBadge
                        label={entry.status ?? 'completed'}
                        variant="paid"
                      />
                    </div>
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </PullRefresh>
  )
}
