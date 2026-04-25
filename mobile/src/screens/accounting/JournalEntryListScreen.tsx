import { useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import type { JournalEntry } from '@shared/types/accounting'
import { useApiList } from '@/hooks/useApiList'
import { MobileList, MobileListItem } from '@/components/ui'
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

function entryTotal(entry: JournalEntry): number {
  const lines = entry.lines ?? []
  return lines.reduce((sum, line) => sum + (line.debit ?? 0), 0)
}

/**
 * Journal entry list screen — paginated list with date, description, amount.
 * Pull-to-refresh.
 *
 * Requirements: 24.1, 24.3
 */
export default function JournalEntryListScreen() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const accountId = searchParams.get('account_id') ?? undefined

  const {
    items,
    isLoading,
    isRefreshing,
    hasMore,
    search,
    setSearch,
    refresh,
    loadMore,
  } = useApiList<JournalEntry>({
    endpoint: '/api/v1/ledger/journal-entries',
    dataKey: 'items',
    initialFilters: accountId ? { account_id: accountId } : {},
  })

  const handleTap = useCallback(
    (entry: JournalEntry) => {
      navigate(`/accounting/journal-entries/${entry.id}`)
    },
    [navigate],
  )

  const renderItem = useCallback(
    (entry: JournalEntry) => {
      const total = entryTotal(entry)

      return (
        <MobileListItem
          title={entry.description ?? 'Journal Entry'}
          subtitle={`${formatDate(entry.date)}${entry.reference ? ` · Ref: ${entry.reference}` : ''}`}
          trailing={
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              {formatCurrency(total)}
            </span>
          }
          onTap={() => handleTap(entry)}
        />
      )
    },
    [handleTap],
  )

  return (
    <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col">
        {/* Back + title */}
        <div className="flex items-center gap-2 px-4 pb-1 pt-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="flex min-h-[44px] items-center gap-1 text-blue-600 dark:text-blue-400"
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
          </button>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Journal Entries
          </h1>
        </div>

        <MobileList<JournalEntry>
          items={items}
          renderItem={renderItem}
          onRefresh={refresh}
          onLoadMore={loadMore}
          isLoading={isLoading}
          isRefreshing={isRefreshing}
          hasMore={hasMore}
          emptyMessage="No journal entries found"
          searchValue={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search entries…"
          keyExtractor={(e) => e.id}
        />
      </div>
    </PullRefresh>
  )
}
