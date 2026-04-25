import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Vehicle } from '@shared/types/vehicle'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function vehicleTitle(v: Vehicle): string {
  const parts = [v.make, v.model].filter(Boolean)
  if (parts.length > 0) return parts.join(' ')
  return v.registration ?? 'Unknown Vehicle'
}

function vehicleSubtitle(v: Vehicle): string {
  const parts: string[] = []
  if (v.registration) parts.push(v.registration)
  if (v.year) parts.push(String(v.year))
  if (v.colour) parts.push(v.colour)
  return parts.join(' · ')
}

/**
 * Vehicle list screen — searchable list with registration, make, model, owner.
 * Pull-to-refresh. Wrapped in ModuleGate for vehicles + automotive-transport
 * at the route level.
 *
 * Requirements: 22.1, 22.3, 22.4
 */
export default function VehicleListScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<Vehicle>({
    endpoint: '/api/v1/vehicles',
    dataKey: 'items',
  })

  const handleTap = useCallback(
    (vehicle: Vehicle) => {
      navigate(`/vehicles/${vehicle.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (vehicle: Vehicle) => (
      <MobileListItem
        title={vehicleTitle(vehicle)}
        subtitle={vehicleSubtitle(vehicle)}
        trailing={
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {vehicle.owner_name ?? ''}
          </span>
        }
        onTap={() => handleTap(vehicle)}
      />
    ),
    [handleTap],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        <div className="px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Vehicles
          </h1>
        </div>

        <MobileList<Vehicle>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No vehicles found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search by rego, make, or model…"
          keyExtractor={(v) => v.id}
        />
      </div>
    </PullRefresh>
  )
}
