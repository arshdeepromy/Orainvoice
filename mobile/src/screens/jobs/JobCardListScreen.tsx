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
  Toggle,
} from 'konsta/react'
import type { JobCard } from '@shared/types/job'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import StatusBadge from '@/components/konsta/StatusBadge'
import KonstaFAB from '@/components/konsta/KonstaFAB'
import { ModuleGate } from '@/components/common/ModuleGate'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 25

const STATUS_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'pending', label: 'Open' },
  { key: 'completed', label: 'Completed' },
  { key: 'cancelled', label: 'Cancelled' },
] as const

/* ------------------------------------------------------------------ */
/* Sorting — statusOrder: in_progress first, pending second,          */
/* completed/cancelled last, then by created_at descending            */
/* ------------------------------------------------------------------ */

const STATUS_ORDER: Record<string, number> = {
  in_progress: 0,
  pending: 1,
  open: 1,
  completed: 2,
  invoiced: 2,
  cancelled: 3,
}

export function sortJobCards(cards: JobCard[]): JobCard[] {
  return [...cards].sort((a, b) => {
    const orderA = STATUS_ORDER[a.status ?? 'pending'] ?? 99
    const orderB = STATUS_ORDER[b.status ?? 'pending'] ?? 99
    if (orderA !== orderB) return orderA - orderB
    // Within same status group, sort by created_at descending
    return (b.created_at ?? '').localeCompare(a.created_at ?? '')
  })
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Job Card list screen — Konsta UI redesign with:
 * - Sorting by statusOrder (in_progress first, open second, completed/invoiced last)
 * - Status colour pill, customer name, vehicle rego subtitle, assigned-to avatar
 * - Status filter and "assigned to me" toggle
 * - FAB for "+ New Job Card"
 * - Pull-to-refresh
 * - Wrapped in ModuleGate for `jobs` module
 *
 * Requirements: 25.1, 25.2, 25.3, 25.4, 55.1, 56.3
 */
export default function JobCardListScreen() {
  const navigate = useNavigate()
  const { user } = useAuth()

  // ── State ──────────────────────────────────────────────────────────
  const [items, setItems] = useState<JobCard[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [assignedToMe, setAssignedToMe] = useState(false)
  const [offset, setOffset] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const hasMore = items.length < total

  // ── Fetch data ─────────────────────────────────────────────────────
  const fetchJobCards = useCallback(
    async (currentOffset: number, isRefresh: boolean, signal: AbortSignal) => {
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
        if (search.trim()) params.search = search.trim()
        if (statusFilter !== 'all') params.status = statusFilter

        const res = await apiClient.get<{ items?: JobCard[]; job_cards?: JobCard[]; total?: number }>(
          '/api/v1/job-cards',
          { params, signal },
        )

        // Safe API consumption
        const newItems = res.data?.items ?? res.data?.job_cards ?? []
        const newTotal = res.data?.total ?? 0

        if (currentOffset === 0 || isRefresh) {
          setItems(newItems)
        } else {
          setItems((prev) => [...prev, ...newItems])
        }
        setTotal(newTotal)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load job cards')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
        setIsLoadingMore(false)
      }
    },
    [search, statusFilter],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setOffset(0)
    fetchJobCards(0, false, controller.signal)
    return () => controller.abort()
  }, [fetchJobCards])

  // ── Pull-to-refresh ────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setOffset(0)
    await fetchJobCards(0, true, controller.signal)
  }, [fetchJobCards])

  // ── Infinite scroll ────────────────────────────────────────────────
  const loadMore = useCallback(() => {
    if (isLoading || isRefreshing || isLoadingMore || !hasMore) return
    const nextOffset = offset + PAGE_SIZE
    setOffset(nextOffset)
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchJobCards(nextOffset, false, controller.signal)
  }, [isLoading, isRefreshing, isLoadingMore, hasMore, offset, fetchJobCards])

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMore()
      },
      { rootMargin: '200px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [loadMore])

  // ── Sort and filter ────────────────────────────────────────────────
  const displayItems = useMemo(() => {
    let filtered = items
    if (assignedToMe && user?.id) {
      filtered = filtered.filter(
        (card) => (card as unknown as Record<string, unknown>).assigned_staff_id === user.id,
      )
    }
    return sortJobCards(filtered)
  }, [items, assignedToMe, user?.id])

  // ── Active chip styling ────────────────────────────────────────────
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
      <ModuleGate moduleSlug="jobs">
        <Page data-testid="job-card-list-page">
          <div className="flex flex-1 items-center justify-center p-8">
            <Preloader />
          </div>
        </Page>
      </ModuleGate>
    )
  }

  return (
    <ModuleGate moduleSlug="jobs">
      <Page data-testid="job-card-list-page">
        <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
          <div className="flex flex-col pb-24">
            {/* ── Searchbar ─────────────────────────────────────────── */}
            <div className="px-4 pt-3">
              <Searchbar
                value={search}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                onClear={() => setSearch('')}
                placeholder="Search job cards…"
                data-testid="job-card-searchbar"
              />
            </div>

            {/* ── Status Filter Chips ───────────────────────────────── */}
            <div className="flex gap-2 overflow-x-auto px-4 py-2" data-testid="status-filter-chips">
              {STATUS_FILTERS.map((filter) => {
                const isActive = statusFilter === filter.key
                return (
                  <Chip
                    key={filter.key}
                    className={`shrink-0 cursor-pointer ${isActive ? 'font-semibold' : ''}`}
                    colors={isActive ? activeChipColors : undefined}
                    onClick={() => setStatusFilter(filter.key)}
                    data-testid={`filter-chip-${filter.key}`}
                  >
                    {filter.label}
                  </Chip>
                )
              })}
            </div>

            {/* ── Assigned to me toggle ─────────────────────────────── */}
            <div className="flex items-center justify-between px-4 py-1">
              <span className="text-sm text-gray-600 dark:text-gray-400">Assigned to me</span>
              <Toggle
                checked={assignedToMe}
                onChange={() => setAssignedToMe((v) => !v)}
                data-testid="assigned-to-me-toggle"
              />
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

            {/* ── Job Card List ────────────────────────────────────── */}
            {displayItems.length === 0 && !isLoading ? (
              <Block className="text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">No job cards found</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="job-card-list">
                {displayItems.map((card) => {
                  const status = card.status ?? 'pending'
                  const assignedName = (card as unknown as Record<string, unknown>).assigned_staff_name as string | null

                  return (
                    <ListItem
                      key={card.id}
                      link
                      onClick={() => navigate(`/job-cards/${card.id}`)}
                      title={
                        <span className="font-bold text-gray-900 dark:text-gray-100">
                          {card.customer_name ?? 'Unknown'}
                        </span>
                      }
                      subtitle={
                        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400">
                          <span className="text-gray-400 dark:text-gray-500">
                            {card.job_card_number ?? ''}
                          </span>
                          {card.vehicle_registration && (
                            <span className="font-mono">{card.vehicle_registration}</span>
                          )}
                        </span>
                      }
                      after={
                        <div className="flex flex-col items-end gap-1">
                          <StatusBadge status={status} size="sm" />
                          {assignedName && (
                            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                              {assignedName.charAt(0).toUpperCase()}
                            </span>
                          )}
                        </div>
                      }
                      data-testid={`job-card-item-${card.id}`}
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

        {/* ── FAB: + New Job Card ───────────────────────────────────── */}
        <KonstaFAB
          label="+ New Job Card"
          onClick={() => navigate('/job-cards/new')}
        />
      </Page>
    </ModuleGate>
  )
}
