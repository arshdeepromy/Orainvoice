import { useNavigate } from 'react-router-dom'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface FranchiseLocation {
  id: string
  name: string
  address: string | null
  revenue: number
  staff_count: number
  status: string
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

function FranchiseDashboardContent() {
  const navigate = useNavigate()
  const { items: locations, isLoading, isRefreshing, refresh } =
    useApiList<FranchiseLocation>({ endpoint: '/api/v2/locations', dataKey: 'items', pageSize: 50 })

  if (isLoading && locations.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Franchise</h1>

      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        {locations.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
            No locations found
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {locations.map((loc) => (
              <MobileCard
                key={loc.id}
                onClick={() => navigate(`/franchise/locations/${loc.id}`)}
                className="cursor-pointer"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {loc.name ?? 'Location'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {loc.address ?? 'No address'}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {formatCurrency(loc.revenue)}
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {loc.staff_count ?? 0} staff
                    </span>
                  </div>
                </div>
              </MobileCard>
            ))}
          </div>
        )}
      </PullRefresh>
    </div>
  )
}

/**
 * Franchise dashboard — location summary cards with pull-to-refresh.
 *
 * Requirements: 33.1, 33.4
 */
export default function FranchiseDashboardScreen() {
  return (
    <ModuleGate moduleSlug="franchise">
      <FranchiseDashboardContent />
    </ModuleGate>
  )
}
