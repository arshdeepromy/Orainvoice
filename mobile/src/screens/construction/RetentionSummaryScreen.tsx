import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

interface RetentionSummary {
  total_retained: number
  total_released: number
  total_pending: number
  release_schedules: ReleaseSchedule[]
}

interface ReleaseSchedule {
  id: string
  project_name: string | null
  amount: number
  release_date: string
  status: string
}

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
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

function RetentionSummaryContent() {
  const { data, isLoading, error, refetch } = useApiDetail<RetentionSummary>({
    endpoint: '/api/v2/retentions/summary',
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 text-center text-red-600 dark:text-red-400">{error}</div>
    )
  }

  const summary = data
  const schedules: ReleaseSchedule[] = summary?.release_schedules ?? []

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Retentions</h1>

      <PullRefresh onRefresh={refetch} isRefreshing={false}>
        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-2">
          <MobileCard>
            <p className="text-xs text-gray-500 dark:text-gray-400">Retained</p>
            <p className="text-lg font-bold text-gray-900 dark:text-gray-100">
              {formatCurrency(summary?.total_retained ?? 0)}
            </p>
          </MobileCard>
          <MobileCard>
            <p className="text-xs text-gray-500 dark:text-gray-400">Released</p>
            <p className="text-lg font-bold text-green-600 dark:text-green-400">
              {formatCurrency(summary?.total_released ?? 0)}
            </p>
          </MobileCard>
          <MobileCard>
            <p className="text-xs text-gray-500 dark:text-gray-400">Pending</p>
            <p className="text-lg font-bold text-amber-600 dark:text-amber-400">
              {formatCurrency(summary?.total_pending ?? 0)}
            </p>
          </MobileCard>
        </div>

        {/* Release schedules */}
        <h2 className="mt-4 text-base font-semibold text-gray-900 dark:text-gray-100">
          Release Schedule
        </h2>
        {schedules.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-500 dark:text-gray-400">
            No scheduled releases
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {schedules.map((s) => (
              <MobileCard key={s.id}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {s.project_name ?? 'Project'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      Release: {formatDate(s.release_date)}
                    </p>
                  </div>
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {formatCurrency(s.amount)}
                  </span>
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
 * Retention summary screen — total retained amounts and release schedules.
 *
 * Requirements: 32.3
 */
export default function RetentionSummaryScreen() {
  return (
    <ModuleGate moduleSlug="retentions">
      <RetentionSummaryContent />
    </ModuleGate>
  )
}
