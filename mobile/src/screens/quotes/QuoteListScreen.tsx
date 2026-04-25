import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Quote } from '@shared/types/quote'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem, MobileButton, MobileBadge } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

const statusVariantMap: Record<Quote['status'], BadgeVariant> = {
  draft: 'draft',
  sent: 'sent',
  accepted: 'paid',
  declined: 'overdue',
  expired: 'cancelled',
}

function formatCurrency(amount: number): string {
  return `${Number(amount ?? 0).toFixed(2)}`
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

/**
 * Quote list screen — searchable paginated list with quote number,
 * customer, amount, status. Pull-to-refresh. Wrapped in ModuleGate
 * for quotes module.
 *
 * Requirements: 9.1, 9.6
 */
export default function QuoteListScreen() {
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
  } = useApiList<Quote>({
    endpoint: '/api/v1/quotes',
    dataKey: 'quotes',
  })

  const handleTap = useCallback(
    (quote: Quote) => {
      navigate(`/quotes/${quote.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (quote: Quote) => {
      const status = quote.status ?? 'draft'

      return (
        <MobileListItem
          title={quote.quote_number ?? 'No Number'}
          subtitle={`${quote.customer_name ?? 'Unknown'} · Valid until ${formatDate(quote.valid_until)}`}
          trailing={
            <div className="flex flex-col items-end gap-1">
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {formatCurrency(quote.total)}
              </span>
              <MobileBadge
                label={status.charAt(0).toUpperCase() + status.slice(1)}
                variant={statusVariantMap[status] ?? 'info'}
              />
            </div>
          }
          onTap={() => handleTap(quote)}
        />
      )
    },
    [handleTap],
  )

  return (
    <ModuleGate moduleSlug="quotes">
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col">
          {/* Header with title and New Quote button */}
          <div className="flex items-center justify-between px-4 pb-1 pt-4">
            <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              Quotes
            </h1>
            <MobileButton
              variant="primary"
              size="sm"
              onClick={() => navigate('/quotes/new')}
              icon={
                <svg
                  className="h-4 w-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              }
            >
              New
            </MobileButton>
          </div>

          {/* Paginated list with search */}
          <MobileList<Quote>
            items={items}
            renderItem={renderItem}
            onRefresh={refresh}
            onLoadMore={loadMore}
            isLoading={isLoading}
            isRefreshing={isRefreshing}
            hasMore={hasMore}
            emptyMessage="No quotes found"
            searchValue={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search quotes…"
            keyExtractor={(q) => q.id}
          />
        </div>
      </PullRefresh>
    </ModuleGate>
  )
}
