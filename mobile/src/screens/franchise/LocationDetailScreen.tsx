import { useNavigate, useParams } from 'react-router-dom'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileSpinner } from '@/components/ui'

interface LocationDetail {
  id: string
  name: string
  address: string | null
  phone: string | null
  email: string | null
  revenue: number
  expenses: number
  profit: number
  staff: StaffMember[]
}

interface StaffMember {
  id: string
  name: string
  role: string
  email: string | null
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

/**
 * Location detail screen — performance metrics and staff for a franchise location.
 *
 * Requirements: 33.2
 */
export default function LocationDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: location, isLoading, error } = useApiDetail<LocationDetail>({
    endpoint: `/api/v2/locations/${id}`,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !location) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">
        {error ?? 'Location not found'}
      </div>
    )
  }

  const staff: StaffMember[] = location.staff ?? []

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        {location.name ?? 'Location'}
      </h1>

      {/* Contact info */}
      <MobileCard>
        <div className="flex flex-col gap-1 text-sm">
          {location.address && (
            <p className="text-gray-700 dark:text-gray-300">{location.address}</p>
          )}
          {location.phone && (
            <p className="text-gray-500 dark:text-gray-400">{location.phone}</p>
          )}
          {location.email && (
            <p className="text-gray-500 dark:text-gray-400">{location.email}</p>
          )}
        </div>
      </MobileCard>

      {/* Performance metrics */}
      <div className="grid grid-cols-3 gap-2">
        <MobileCard>
          <p className="text-xs text-gray-500 dark:text-gray-400">Revenue</p>
          <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
            {formatCurrency(location.revenue)}
          </p>
        </MobileCard>
        <MobileCard>
          <p className="text-xs text-gray-500 dark:text-gray-400">Expenses</p>
          <p className="text-lg font-bold text-red-600 dark:text-red-400">
            {formatCurrency(location.expenses)}
          </p>
        </MobileCard>
        <MobileCard>
          <p className="text-xs text-gray-500 dark:text-gray-400">Profit</p>
          <p className="text-lg font-bold text-green-600 dark:text-green-400">
            {formatCurrency(location.profit)}
          </p>
        </MobileCard>
      </div>

      {/* Staff */}
      <MobileCard>
        <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
          Staff ({staff.length})
        </h2>
        {staff.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No staff assigned</p>
        ) : (
          staff.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700"
            >
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {s.name}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {s.role}{s.email ? ` · ${s.email}` : ''}
                </p>
              </div>
            </div>
          ))
        )}
      </MobileCard>
    </div>
  )
}
