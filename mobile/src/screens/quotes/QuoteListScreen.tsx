import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Searchbar,
  Chip,
  List,
  ListItem,
  Block,
  Preloader,
} from 'konsta/react'
import type { Quote } from '@shared/types/quote'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import StatusBadge from '@/components/konsta/StatusBadge'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import { ModuleGate } from '@/components/common/ModuleGate'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 25

/** Status filter chips — "All" plus every quote status */
const STATUS_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'draft', label: 'Draft' },
  { key: 'sent', label: 'Sent' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'declined', label: 'Declined' },
  { key: 'expired', label: 'Expired' },
] as const

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Safe NZD currency formatting matching the project convention */
function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDate(dateStr: string | undefined): string {
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

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Quote list screen — Konsta UI redesign with:
 * - Full-screen list with Konsta Searchbar and status filter chips
 * - Each quote as Konsta ListItem with customer name, quote number,
 *   NZD total, status badge, valid until date
 * - Infinite scroll pagination (25 per page) using offset and limit
 * - FAB for "+ New Quote"
 * - Pull-to-refresh
 * - Wrapped in ModuleGate for `quotes` module
 * - Safe API consumption: res.data?.items ?? [], res.data?.total ?? 0
 *
 * Requirements: 24.1, 24.5, 55.1
 */
export default function QuoteListScreen() {
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────
  const [items, setItems] = useState<Quote[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [offset, setOffset] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const hasMore = items.length < total

  // ── Fetch data ─────────────────────────────────────────────────────
  const fetchQuotes = useCallback(
    async (
      currentOffset: number,
      isRefresh: boolean,
      signal: AbortSignal,
    ) => {
      if (isRefresh) {
        setIsRefreshing(true)
      } else if (currentOffset === 0) {
        setIsLoading(true)
      } else {
        setIsLoadingMore(true)
      }
      setError(null)

      try {
        const params: Record<string, string | number> = {
          offset: currentOffset,
          limit: PAGE_SIZE,
        }
        if (search.trim()) {
          params.search = search.trim()
        }
        if (statusFilter !== 'all') {
          params.status = statusFilter
        }

        const res = await apiClient.get<{ items?: Quote[]; total?: number }>(
          '/api/v1/quotes',
          { params, signal },
        )

        // Safe API consumption
        const newItems = res.data?.items ?? []
        const newTotal = res.data?.total ?? 0

        if (currentOffset === 0 || isRefresh) {
          setItems(newItems)
        } else {
          setItems((prev) => [...prev, ...newItems])
        }
        setTotal(newTotal)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load quotes')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
        setIsLoadingMore(false)
      }
    },
    [search, statusFilter],
  )

  // Fetch on mount and when search/filter changes (reset to offset 0)
  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    fetchQuotes(0, false, controller.signal)

    return () => controller.abort()
  }, [fetchQuotes])

  // ── Pull-to-refresh ────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setOffset(0)
    await fetchQuotes(0, true, controller.signal)
  }, [fetchQuotes])

  // ── Infinite scroll via IntersectionObserver ───────────────────────
  const loadMore = useCallback(() => {
    if (isLoading || isRefreshing || isLoadingMore || !hasMore) return

    const nextOffset = offset + PAGE_SIZE
    setOffset(nextOffset)

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    fetchQuotes(nextOffset, false, controller.signal)
  }, [isLoading, isRefreshing, isLoadingMore, hasMore, offset, fetchQuotes])

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadMore()
        }
      },
      { rootMargin: '200px' },
    )

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMore])

  // ── Memoised search handler ────────────────────────────────────────
  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setSearch(e.target.value)
    },
    [],
  )

  const handleSearchClear = useCallback(() => {
    setSearch('')
  }, [])

  // ── Active filter chip styling ─────────────────────────────────────
  const activeChipColors = useMemo(
    () => ({
      fillBgIos: 'bg-primary',
      fillBgMaterial: 'bg-primary',
      fillTextIos: 'text-white',
      fillTextMaterial: 'text-white',
    }),
    [],
  )

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading && items.length === 0) {
    return (
      <ModuleGate moduleSlug="quotes">
        <Page data-testid="quote-list-page">
          <div className="flex flex-1 items-center justify-center p-8">
            <Preloader />
          </div>
        </Page>
      </ModuleGate>
    )
  }

  return (
    <ModuleGate moduleSlug="quotes">
      <Page data-testid="quote-list-page">
        <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
          <div className="flex flex-col pb-24">
            {/* ── Searchbar ─────────────────────────────────────────── */}
            <div className="px-4 pt-3">
              <Searchbar
                value={search}
                onChange={handleSearchChange}
                onClear={handleSearchClear}
                placeholder="Search quotes…"
                data-testid="quote-searchbar"
              />
            </div>

            {/* ── Status Filter Chips ───────────────────────────────── */}
            <div
              className="-mx-0 flex gap-2 overflow-x-auto px-4 py-2"
              data-testid="status-filter-chips"
            >
              {STATUS_FILTERS.map((filter) => {
                const isActive = statusFilter === filter.key
                return (
                  <Chip
                    key={filter.key}
                    className={`shrink-0 cursor-pointer ${
                      isActive ? 'font-semibold' : ''
                    }`}
                    colors={isActive ? activeChipColors : undefined}
                    onClick={() => setStatusFilter(filter.key)}
                    data-testid={`filter-chip-${filter.key}`}
                  >
                    {filter.label}
                  </Chip>
                )
              })}
            </div>

            {/* ── Error Banner ──────────────────────────────────────── */}
            {error && (
              <Block>
                <div
                  role="alert"
                  className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
                >
                  {error}
                  <button
                    type="button"
                    onClick={() => handleRefresh()}
                    className="ml-2 font-medium underline"
                  >
                    Retry
                  </button>
                </div>
              </Block>
            )}

            {/* ── Quote List ──────────────────────────────────────── */}
            {items.length === 0 && !isLoading ? (
              <Block className="text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">
                  No quotes found
                </p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="quote-list">
                {items.map((quote) => {
                  const status = quote.status ?? 'draft'

                  return (
                    <ListItem
                      key={quote.id}
                      link
                      onClick={() => navigate(`/quotes/${quote.id}`)}
                      title={
                        <span className="font-bold text-gray-900 dark:text-gray-100">
                          {quote.customer_name ?? 'Unknown'}
                        </span>
                      }
                      subtitle={
                        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
                          <span className="text-gray-400 dark:text-gray-500">
                            {quote.quote_number ?? ''}
                          </span>
                          {quote.valid_until && (
                            <span>Valid until {formatDate(quote.valid_until)}</span>
                          )}
                        </span>
                      }
                      after={
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-base font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                            {formatNZD(quote.total)}
                          </span>
                          <StatusBadge status={status} size="sm" />
                        </div>
                      }
                      data-testid={`quote-item-${quote.id}`}
                    />
                  )
                })}
              </List>
            )}

            {/* ── Infinite scroll sentinel ──────────────────────────── */}
            {hasMore && (
              <div ref={sentinelRef} className="flex justify-center py-4">
                {isLoadingMore && <Preloader />}
              </div>
            )}
          </div>
        </PullRefresh>

        {/* ── FAB: + New Quote ──────────────────────────────────────── */}
        <KonstaFAB
          label="+ New Quote"
          onClick={() => navigate('/quotes/new')}
        />
      </Page>
    </ModuleGate>
  )
}
