import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { GstPeriod } from '@shared/types/accounting'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileBadge } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

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

const statusVariant: Record<GstPeriod['status'], 'draft' | 'info' | 'paid'> = {
  open: 'draft',
  filed: 'info',
  paid: 'paid',
}

function statusLabel(status: GstPeriod['status']): string {
  return (status ?? 'open').charAt(0).toUpperCase() + (status ?? 'open').slice(1)
}

/**
 * GST periods screen — list with period dates, status, GST amounts.
 * Pull-to-refresh. Wrapped in ModuleGate at the route level.
 *
 * Requirements: 26.1, 26.4
 */
export default function GstPeriodsScreen() {
  const navigate = useNavigate()

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    refresh,
    loadMore,
  } = useApiList<GstPeriod>({
    endpoint: '/api/v1/gst/periods',
    dataKey: 'items',
  })

  const handleTap = useCallback(
    (period: GstPeriod) => {
      navigate(`/accounting/gst/${period.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (period: GstPeriod) => (
      <MobileListItem
        title={`${formatDate(period.start_date)} – ${formatDate(period.end_date)}`}
        subtitle={`Net GST: ${formatCurrency(period.net_gst)}`}
        trailing={
          <MobileBadge
            label={statusLabel(period.status)}
            variant={statusVariant[period.status] ?? 'draft'}
          />
        }
        onTap={() => handleTap(period)}
      />
    ),
    [handleTap],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        <div className="px-4 pb-1 pt-4">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            GST Periods
          </h1>
        </div>

        <MobileList<GstPeriod>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No GST periods found"
          keyExtractor={(p) => p.id}
        />
      </div>
    </PullRefresh>
  )
}
