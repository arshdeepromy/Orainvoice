import { useState, useCallback, useRef, useEffect } from 'react'
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
import type { Vehicle } from '@shared/types/vehicle'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                          */
/* ------------------------------------------------------------------ */

const PAGE_SIZE = 25

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

/**
 * Determine WOF expiry pill colour:
 * - Red if expired
 * - Amber if within 30 days
 * - Green otherwise
 */
function wofExpiryStatus(
  wofExpiry: string | null | undefined,
): { label: string; color: string; bg: string } | null {
  if (!wofExpiry) return null
  const expiry = new Date(wofExpiry)
  const now = new Date()
  const diffDays = Math.floor((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))

  if (diffDays < 0) {
    return { label: 'WOF Expired', color: 'text-red-700', bg: 'bg-red-100 dark:bg-red-900/30' }
  }
  if (diffDays < 30) {
    return { label: `WOF ${diffDays}d`, color: 'text-amber-700', bg: 'bg-amber-100 dark:bg-amber-900/30' }
  }
  return { label: 'WOF OK', color: 'text-green-700', bg: 'bg-green-100 dark:bg-green-900/30' }
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

/**
 * Vehicle list screen — Konsta UI redesign with:
 * - Searchbar (search by rego)
 * - List items: rego (large, monospace), make/model/year, owner name,
 *   WOF expiry pill (red if expired, amber if <30 days)
 * - Wrapped in ModuleGate for `vehicles` module + `automotive-transport` trade
 *
 * Requirements: 29.1, 29.4, 55.5
 */
export default function VehicleListScreen() {
  const navigate = useNavigate()

  // ── State ──────────────────────────────────────────────────────────
  const [items, setItems] = useState<(Vehicle & { wof_expiry?: string })[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const hasMore = items.length < total

  // ── Fetch data ─────────────────────────────────────────────────────
  const fetchVehicles = useCallback(
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

        const res = await apiClient.get<{
          items?: (Vehicle & { wof_expiry?: string })[]
          vehicles?: (Vehicle & { wof_expiry?: string })[]
          total?: number
        }>('/api/v1/vehicles', { params, signal })

        // Safe API consumption
        const newItems = res.data?.items ?? res.data?.vehicles ?? []
        const newTotal = res.data?.total ?? 0

        if (currentOffset === 0 || isRefresh) {
          setItems(newItems)
        } else {
          setItems((prev) => [...prev, ...newItems])
        }
        setTotal(newTotal)
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load vehicles')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
        setIsLoadingMore(false)
      }
    },
    [search],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setOffset(0)
    fetchVehicles(0, false, controller.signal)
    return () => controller.abort()
  }, [fetchVehicles])

  // ── Pull-to-refresh ────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setOffset(0)
    await fetchVehicles(0, true, controller.signal)
  }, [fetchVehicles])

  // ── Infinite scroll ────────────────────────────────────────────────
  const loadMore = useCallback(() => {
    if (isLoading || isRefreshing || isLoadingMore || !hasMore) return
    const nextOffset = offset + PAGE_SIZE
    setOffset(nextOffset)
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchVehicles(nextOffset, false, controller.signal)
  }, [isLoading, isRefreshing, isLoadingMore, hasMore, offset, fetchVehicles])

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

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading && items.length === 0) {
    return (
      <ModuleGate moduleSlug="vehicles" tradeFamily="automotive-transport">
        <Page data-testid="vehicle-list-page">
          <div className="flex flex-1 items-center justify-center p-8">
            <Preloader />
          </div>
        </Page>
      </ModuleGate>
    )
  }

  return (
    <ModuleGate moduleSlug="vehicles" tradeFamily="automotive-transport">
      <Page data-testid="vehicle-list-page">
        <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
          <div className="flex flex-col pb-24">
            {/* ── Searchbar ─────────────────────────────────────────── */}
            <div className="px-4 pt-3">
              <Searchbar
                value={search}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                onClear={() => setSearch('')}
                placeholder="Search by rego…"
                data-testid="vehicle-searchbar"
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
                  <button type="button" onClick={() => handleRefresh()} className="ml-2 font-medium underline">
                    Retry
                  </button>
                </div>
              </Block>
            )}

            {/* ── Vehicle List ─────────────────────────────────────── */}
            {items.length === 0 && !isLoading ? (
              <Block className="text-center">
                <p className="text-sm text-gray-400 dark:text-gray-500">No vehicles found</p>
              </Block>
            ) : (
              <List strongIos outlineIos dividersIos data-testid="vehicle-list">
                {items.map((vehicle) => {
                  const wof = wofExpiryStatus(vehicle.wof_expiry)
                  const makeModel = [vehicle.make, vehicle.model].filter(Boolean).join(' ')
                  const yearStr = vehicle.year ? String(vehicle.year) : ''
                  const subtitle = [makeModel, yearStr].filter(Boolean).join(' · ')

                  return (
                    <ListItem
                      key={vehicle.id}
                      link
                      onClick={() => navigate(`/vehicles/${vehicle.id}`)}
                      title={
                        <span className="font-mono text-lg font-bold text-gray-900 dark:text-gray-100">
                          {vehicle.registration ?? 'No Rego'}
                        </span>
                      }
                      subtitle={
                        <span className="flex flex-col gap-0.5">
                          {subtitle && (
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              {subtitle}
                            </span>
                          )}
                          <span className="text-xs text-gray-400 dark:text-gray-500">
                            {vehicle.owner_name ?? ''}
                          </span>
                        </span>
                      }
                      after={
                        wof ? (
                          <Chip
                            className={`${wof.color} ${wof.bg} text-xs`}
                            colors={{
                              fillBgIos: wof.bg,
                              fillBgMaterial: wof.bg,
                              fillTextIos: wof.color,
                              fillTextMaterial: wof.color,
                            }}
                          >
                            {wof.label}
                          </Chip>
                        ) : undefined
                      }
                      data-testid={`vehicle-item-${vehicle.id}`}
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
      </Page>
    </ModuleGate>
  )
}
