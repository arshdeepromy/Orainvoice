/**
 * ShiftCoverPage — `/shift-cover` route.
 *
 * Lists open-shift cover broadcasts for the org. Eligible staff can
 * claim an open broadcast; admins / requesters can view past
 * accepted / cancelled / expired rows via the filter.
 *
 *   GET   /api/v2/shift-cover            — paginated list
 *   POST  /api/v2/shift-cover/{id}/accept — claim an open broadcast
 *
 * G6: at claim time the backend re-checks eligibility and returns
 * 409 ``scheduling_conflict_at_claim`` when the claiming staff has
 * since been scheduled into a conflicting shift.
 *
 * Refs: Phase 3 R13 / G6. Touch targets ≥ 44×44, safe API
 * consumption, AbortController in every useEffect.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'

/* ─────────────────────────────────────────────── Types ── */

type CoverStatus = 'open' | 'accepted' | 'cancelled' | 'expired'

interface ShiftCover {
  id: string
  org_id: string
  schedule_entry_id: string
  requester_staff_id: string
  requester_name: string | null
  status: CoverStatus
  accepted_by: string | null
  accepted_by_name: string | null
  broadcast_at: string
  expires_at: string | null
  accepted_at: string | null
  created_at: string
}

interface ShiftCoverListResponse {
  items: ShiftCover[]
  total: number
}

const FILTER_OPTIONS: { value: CoverStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'expired', label: 'Expired' },
]

function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}

function readErrorDetail(err: unknown): string | null {
  if (axios.isCancel?.(err)) return null
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  return null
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString([], {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

interface StatusBadgeProps {
  status: CoverStatus
}

function StatusBadge({ status }: StatusBadgeProps) {
  const cls =
    status === 'open'
      ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200'
      : status === 'accepted'
        ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200'
        : status === 'cancelled'
          ? 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200'
          : 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-100'
  return (
    <span
      data-testid={`cover-status-badge-${status}`}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {status}
    </span>
  )
}

export default function ShiftCoverPage() {
  const [filter, setFilter] = useState<CoverStatus | 'all'>('open')
  const [items, setItems] = useState<ShiftCover[]>([])
  const [total, setTotal] = useState<number>(0)
  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState<number>(0)

  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())
  const [actionError, setActionError] = useState<{ id: string; message: string } | null>(null)
  const [claimedIds, setClaimedIds] = useState<Set<string>>(new Set())

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  const setRowBusy = useCallback((id: string, busy: boolean) => {
    setBusyIds((prev) => {
      const next = new Set(prev)
      if (busy) next.add(id)
      else next.delete(id)
      return next
    })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      setLoadError(null)
      try {
        const params: Record<string, string> = { offset: '0', limit: '100' }
        if (filter !== 'all') params.status = filter
        const res = await apiClient.get<ShiftCoverListResponse>(
          '/api/v2/shift-cover',
          { params, signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setItems(res.data?.items ?? [])
        setTotal(res.data?.total ?? 0)
      } catch (err) {
        if (controller.signal.aborted || isAbortError(err)) return
        setLoadError("Couldn't load open shifts.")
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [filter, refreshKey])

  const handleClaim = useCallback(
    async (coverId: string) => {
      setActionError(null)
      setRowBusy(coverId, true)
      const controller = new AbortController()
      try {
        await apiClient.post(
          `/api/v2/shift-cover/${coverId}/accept`,
          {},
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setClaimedIds((prev) => {
          const next = new Set(prev)
          next.add(coverId)
          return next
        })
        refresh()
      } catch (err) {
        if (controller.signal.aborted || isAbortError(err)) return
        const detail = readErrorDetail(err)
        const status = (err as { response?: { status?: number } })?.response
          ?.status
        let message = 'Could not claim this shift. Please try again.'
        if (status === 409) {
          if (detail === 'scheduling_conflict_at_claim') {
            message =
              "You've been scheduled into a conflicting shift since this was broadcast. The shift is still open for someone else."
          } else if (detail === 'invalid_state') {
            message = 'This shift is no longer open for cover.'
          } else if (detail === 'not_eligible') {
            message =
              'You are not eligible to claim this shift. Talk to your manager.'
          }
        } else if (status === 403) {
          message = 'You are not eligible to claim this shift.'
        } else if (detail) {
          message = detail
        }
        setActionError({ id: coverId, message })
      } finally {
        if (!controller.signal.aborted) setRowBusy(coverId, false)
      }
    },
    [refresh, setRowBusy],
  )

  const openCount = useMemo(
    () => (items ?? []).filter((c) => c?.status === 'open').length,
    [items],
  )

  return (
    <div className="space-y-4 p-4 lg:p-6" data-testid="shift-cover-page">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Open shifts
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Open-shift cover broadcasts for your org. Claim an open shift to
            take it on.
            {filter === 'open' && openCount > 0 && (
              <>
                {' '}
                <span
                  className="ml-2 inline-flex items-center rounded-full bg-blue-600 px-2 py-0.5 text-xs font-medium text-white"
                  data-testid="open-shift-count"
                >
                  {openCount} open
                </span>
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label
            htmlFor="cover-filter"
            className="text-sm text-gray-700 dark:text-gray-200"
          >
            Filter
          </label>
          <select
            id="cover-filter"
            value={filter}
            onChange={(e) =>
              setFilter(e.target.value as CoverStatus | 'all')
            }
            className="min-h-[44px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            data-testid="cover-filter-select"
          >
            {FILTER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={refresh}
            className="min-h-[44px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            Refresh
          </button>
        </div>
      </header>

      {loadError && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300"
        >
          {loadError}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-gray-500 dark:text-gray-400">
          Loading open shifts…
        </div>
      ) : items.length === 0 ? (
        <div
          className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400"
          data-testid="shift-cover-empty"
        >
          No open-shift broadcasts to show.
        </div>
      ) : (
        <ul
          className="space-y-3"
          aria-label="Open shifts"
          data-testid="shift-cover-list"
        >
          {items.map((cover) => {
            const isBusy = busyIds.has(cover.id)
            const justClaimed = claimedIds.has(cover.id)
            const errMessage =
              actionError && actionError.id === cover.id
                ? actionError.message
                : null
            return (
              <li
                key={cover.id}
                data-testid={`shift-cover-row-${cover.id}`}
                className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {cover?.requester_name ?? 'Someone'}{' '}
                      <span className="font-normal text-gray-600 dark:text-gray-400">
                        needs cover
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      Broadcast {formatDateTime(cover?.broadcast_at)}
                      {cover?.expires_at && (
                        <>
                          {' '}
                          · Expires {formatDateTime(cover.expires_at)}
                        </>
                      )}
                      {cover?.accepted_by_name && (
                        <>
                          {' '}
                          · Claimed by{' '}
                          <span className="font-medium">
                            {cover.accepted_by_name}
                          </span>{' '}
                          {formatDateTime(cover?.accepted_at)}
                        </>
                      )}
                    </p>
                  </div>
                  <StatusBadge status={cover.status} />
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {cover.status === 'open' && !justClaimed && (
                    <button
                      type="button"
                      onClick={() => void handleClaim(cover.id)}
                      disabled={isBusy}
                      className="min-h-[44px] rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                      data-testid={`cover-claim-${cover.id}`}
                    >
                      {isBusy ? 'Claiming…' : 'Claim shift'}
                    </button>
                  )}
                  {justClaimed && (
                    <span
                      className="text-sm font-medium text-emerald-700 dark:text-emerald-300"
                      data-testid={`cover-claimed-${cover.id}`}
                    >
                      Claimed — refreshing list…
                    </span>
                  )}
                </div>

                {errMessage && (
                  <p
                    role="alert"
                    className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300"
                    data-testid={`cover-action-error-${cover.id}`}
                  >
                    {errMessage}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {!loading && items.length > 0 && total > items.length && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Showing {items.length} of {total} broadcasts.
        </p>
      )}
    </div>
  )
}
