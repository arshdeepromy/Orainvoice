/**
 * ShiftSwapPage — `/shift-swaps` route.
 *
 * Reflects the 5-state state machine (G8): pending, awaiting_manager,
 * accepted, rejected, cancelled. The page surfaces an "Awaiting manager
 * approval" badge when applicable, and managers (org_admin / branch_admin)
 * see a queue of `awaiting_manager` rows with approve / reject buttons.
 *
 * Data flow:
 *   GET    /api/v2/shift-swaps                       — paginated list
 *   POST   /api/v2/shift-swaps/{id}/accept           — target accepts
 *   POST   /api/v2/shift-swaps/{id}/reject           — target rejects
 *   POST   /api/v2/shift-swaps/{id}/manager-approve  — manager approves (G8)
 *   POST   /api/v2/shift-swaps/{id}/manager-reject   — manager rejects (G8)
 *   POST   /api/v2/shift-swaps/{id}/cancel           — requester cancels
 *
 * Refs: Phase 3 R12 / G8 / G13. Touch targets ≥ 44×44, safe API
 * consumption, AbortController in every useEffect.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'

/* ─────────────────────────────────────────────── Types ── */

type SwapStatus =
  | 'pending'
  | 'awaiting_manager'
  | 'accepted'
  | 'rejected'
  | 'cancelled'

interface ShiftSwap {
  id: string
  org_id: string
  requester_staff_id: string
  requester_name: string | null
  target_staff_id: string | null
  target_name: string | null
  schedule_entry_id: string
  status: SwapStatus
  reason: string | null
  decided_by: string | null
  decided_by_name: string | null
  created_at: string
  decided_at: string | null
}

interface ShiftSwapListResponse {
  items: ShiftSwap[]
  total: number
}

const FILTER_OPTIONS: { value: SwapStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'awaiting_manager', label: 'Awaiting manager' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'cancelled', label: 'Cancelled' },
]

const MANAGER_ROLES = new Set(['org_admin', 'branch_admin'])

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
  status: SwapStatus
}

function StatusBadge({ status }: StatusBadgeProps) {
  const label =
    status === 'awaiting_manager' ? 'Awaiting manager approval' : status
  const cls =
    status === 'accepted'
      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200'
      : status === 'rejected'
        ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200'
        : status === 'cancelled'
          ? 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200'
          : status === 'awaiting_manager'
            ? 'bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100'
            : 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200'
  return (
    <span
      data-testid={`swap-status-badge-${status}`}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </span>
  )
}

export default function ShiftSwapPage() {
  const { user } = useAuth()
  const isManager = useMemo(() => {
    return MANAGER_ROLES.has(user?.role ?? '')
  }, [user])

  const [filter, setFilter] = useState<SwapStatus | 'all'>('all')
  const [items, setItems] = useState<ShiftSwap[]>([])
  const [total, setTotal] = useState<number>(0)
  const [loading, setLoading] = useState<boolean>(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState<number>(0)

  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())
  const [actionError, setActionError] = useState<{ id: string; message: string } | null>(null)

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
        const res = await apiClient.get<ShiftSwapListResponse>(
          '/api/v2/shift-swaps',
          { params, signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setItems(res.data?.items ?? [])
        setTotal(res.data?.total ?? 0)
      } catch (err) {
        if (controller.signal.aborted || isAbortError(err)) return
        setLoadError("Couldn't load shift-swap requests.")
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [filter, refreshKey])

  const performAction = useCallback(
    async (swapId: string, path: string) => {
      setActionError(null)
      setRowBusy(swapId, true)
      const controller = new AbortController()
      try {
        await apiClient.post(`/api/v2/shift-swaps/${swapId}/${path}`, {}, {
          signal: controller.signal,
        })
        if (!controller.signal.aborted) refresh()
      } catch (err) {
        if (controller.signal.aborted || isAbortError(err)) return
        const detail = readErrorDetail(err)
        const status = (err as { response?: { status?: number } })?.response
          ?.status
        let message = 'Action failed. Please refresh and try again.'
        if (status === 409) {
          if (detail === 'scheduling_conflict_at_accept') {
            message =
              'Scheduling conflict — the target has been scheduled into another shift since this request was raised.'
          } else if (detail === 'scheduling_conflict_at_manager_approval') {
            message =
              'Scheduling conflict — the target now has a conflicting shift. Re-check the schedule and try again.'
          } else if (detail === 'invalid_state' || detail === 'not_awaiting_manager') {
            message =
              'This request has already been actioned by someone else.'
          }
        } else if (detail) {
          message = detail
        }
        setActionError({ id: swapId, message })
      } finally {
        if (!controller.signal.aborted) setRowBusy(swapId, false)
      }
    },
    [refresh, setRowBusy],
  )

  const awaitingManagerCount = useMemo(
    () => (items ?? []).filter((s) => s?.status === 'awaiting_manager').length,
    [items],
  )

  return (
    <div className="space-y-4 p-4 lg:p-6" data-testid="shift-swap-page">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
            Shift swaps
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            View and action staff shift-swap requests.
            {isManager && awaitingManagerCount > 0 && (
              <>
                {' '}
                <span
                  className="ml-2 inline-flex items-center rounded-full bg-red-600 px-2 py-0.5 text-xs font-medium text-white"
                  data-testid="awaiting-manager-counter"
                >
                  {awaitingManagerCount} awaiting your approval
                </span>
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label
            htmlFor="swap-filter"
            className="text-sm text-gray-700 dark:text-gray-200"
          >
            Filter
          </label>
          <select
            id="swap-filter"
            value={filter}
            onChange={(e) =>
              setFilter(e.target.value as SwapStatus | 'all')
            }
            className="min-h-[44px] rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            data-testid="swap-filter-select"
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
          Loading shift swaps…
        </div>
      ) : items.length === 0 ? (
        <div
          className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400"
          data-testid="shift-swap-empty"
        >
          No shift swaps to show.
        </div>
      ) : (
        <ul
          className="space-y-3"
          aria-label="Shift swap requests"
          data-testid="shift-swap-list"
        >
          {items.map((swap) => {
            const requesterIsMe =
              !!user?.id &&
              !!swap?.requester_staff_id &&
              swap.status === 'pending'
            const targetIsMe = !!swap?.target_staff_id && !!user?.id
            // Manager queue surfaces only awaiting_manager rows.
            const showManagerActions =
              isManager && swap.status === 'awaiting_manager'
            const showTargetActions =
              swap.status === 'pending' && targetIsMe
            const showCancel = requesterIsMe || swap.status === 'awaiting_manager'
            const isBusy = busyIds.has(swap.id)
            const errMessage =
              actionError && actionError.id === swap.id
                ? actionError.message
                : null
            return (
              <li
                key={swap.id}
                data-testid={`shift-swap-row-${swap.id}`}
                className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {swap?.requester_name ?? 'Someone'}{' '}
                      <span className="font-normal text-gray-600 dark:text-gray-400">
                        wants to swap with
                      </span>{' '}
                      {swap?.target_name ?? 'anyone'}
                    </p>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      Requested {formatDateTime(swap?.created_at)}
                      {swap?.decided_at && (
                        <>
                          {' '}
                          · Decided {formatDateTime(swap.decided_at)}
                        </>
                      )}
                    </p>
                    {swap?.reason && (
                      <p className="mt-1 text-sm text-gray-700 dark:text-gray-300">
                        “{swap.reason}”
                      </p>
                    )}
                  </div>
                  <StatusBadge status={swap.status} />
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {showTargetActions && (
                    <>
                      <button
                        type="button"
                        onClick={() => void performAction(swap.id, 'accept')}
                        disabled={isBusy}
                        className="min-h-[44px] rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                        data-testid={`swap-accept-${swap.id}`}
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        onClick={() => void performAction(swap.id, 'reject')}
                        disabled={isBusy}
                        className="min-h-[44px] rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
                        data-testid={`swap-reject-${swap.id}`}
                      >
                        Reject
                      </button>
                    </>
                  )}
                  {showManagerActions && (
                    <>
                      <button
                        type="button"
                        onClick={() =>
                          void performAction(swap.id, 'manager-approve')
                        }
                        disabled={isBusy}
                        className="min-h-[44px] rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                        data-testid={`swap-manager-approve-${swap.id}`}
                      >
                        {isBusy ? 'Working…' : 'Approve'}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void performAction(swap.id, 'manager-reject')
                        }
                        disabled={isBusy}
                        className="min-h-[44px] rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-700 dark:bg-gray-900 dark:text-red-300 dark:hover:bg-red-900/20"
                        data-testid={`swap-manager-reject-${swap.id}`}
                      >
                        Reject
                      </button>
                    </>
                  )}
                  {showCancel && (
                    <button
                      type="button"
                      onClick={() => void performAction(swap.id, 'cancel')}
                      disabled={isBusy}
                      className="min-h-[44px] rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
                      data-testid={`swap-cancel-${swap.id}`}
                    >
                      Cancel
                    </button>
                  )}
                </div>

                {errMessage && (
                  <p
                    role="alert"
                    className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300"
                    data-testid={`swap-action-error-${swap.id}`}
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
          Showing {items.length} of {total} requests.
        </p>
      )}
    </div>
  )
}
