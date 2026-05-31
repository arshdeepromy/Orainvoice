/**
 * PermissionsPage — Settings → People → People Permissions.
 *
 * Family-Violence Leave Visibility manager. Lists every org user with a
 * checkbox controlling the `leave.fv_view` permission via the
 * `user_permission_overrides` table.
 *
 * Behaviour (per Phase 2 design §9.1):
 * - Header explains the purpose.
 * - 30-day post-migration nag banner reminds the org owner to review who
 *   inherited the permission via the migration backfill. Dismissible
 *   via localStorage (per-user-per-browser).
 * - Toggling a checkbox calls `grantFvLeaveView(userId)` /
 *   `revokeFvLeaveView(userId)` with optimistic UI; on error the toggle
 *   reverts and an inline message surfaces.
 *
 * **Validates: Staff Management Phase 2 task D11**
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import {
  grantFvLeaveView,
  listFvLeaveViewPermissions,
  revokeFvLeaveView,
  type FvLeaveViewUser,
} from '../../../api/leave'
import { Spinner } from '../../../components/ui'

const NAG_DISMISS_KEY = 'fv-permission-nag-dismissed-v1'

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

function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const inner = detail as { reason?: string; detail?: string }
      if (typeof inner.reason === 'string') return inner.reason
      if (typeof inner.detail === 'string') return inner.detail
    }
    if (err.message) return err.message
  }
  if (err instanceof Error && err.message) return err.message
  return 'Action failed'
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function readNagDismissed(): boolean {
  try {
    return window.localStorage.getItem(NAG_DISMISS_KEY) === '1'
  } catch {
    return false
  }
}

function persistNagDismissed(): void {
  try {
    window.localStorage.setItem(NAG_DISMISS_KEY, '1')
  } catch {
    /* ignore — incognito or storage disabled */
  }
}

export default function PermissionsPage() {
  const [items, setItems] = useState<FvLeaveViewUser[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState<number>(0)
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null)
  const [nagDismissed, setNagDismissed] = useState<boolean>(() => readNagDismissed())

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await listFvLeaveViewPermissions(controller.signal)
        if (cancelled || controller.signal.aborted) return
        setItems(res.items ?? [])
      } catch (err) {
        if (cancelled || controller.signal.aborted || isAbortError(err)) return
        setError(extractError(err) || 'Failed to load permissions')
      } finally {
        if (!cancelled && !controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [refreshKey])

  const dismissNag = useCallback(() => {
    persistNagDismissed()
    setNagDismissed(true)
  }, [])

  const setRowBusy = useCallback((id: string, busy: boolean) => {
    setBusyIds((prev) => {
      const next = new Set(prev)
      if (busy) next.add(id)
      else next.delete(id)
      return next
    })
  }, [])

  const handleToggle = useCallback(
    async (user: FvLeaveViewUser, nextChecked: boolean) => {
      const previous = user.has_fv_view
      // Optimistic update
      setItems((prev) =>
        (prev ?? []).map((u) =>
          u.user_id === user.user_id ? { ...u, has_fv_view: nextChecked } : u,
        ),
      )
      setRowBusy(user.user_id, true)
      setRowError(null)
      try {
        if (nextChecked) {
          await grantFvLeaveView(user.user_id)
        } else {
          await revokeFvLeaveView(user.user_id)
        }
      } catch (err) {
        // Revert on failure
        setItems((prev) =>
          (prev ?? []).map((u) =>
            u.user_id === user.user_id ? { ...u, has_fv_view: previous } : u,
          ),
        )
        setRowError({
          id: user.user_id,
          message: extractError(err) || 'Failed to update permission',
        })
      } finally {
        setRowBusy(user.user_id, false)
      }
    },
    [setRowBusy],
  )

  const sortedUsers = useMemo(() => {
    return [...(items ?? [])].sort((a, b) => {
      const aName = (a.name ?? a.email ?? '').toLowerCase()
      const bName = (b.name ?? b.email ?? '').toLowerCase()
      if (aName < bName) return -1
      if (aName > bName) return 1
      return 0
    })
  }, [items])

  return (
    <div className="space-y-4" data-testid="permissions-page">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Family-Violence Leave Visibility
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Grant or revoke permission to view confidential family-violence
          leave requests.
        </p>
      </div>

      {!nagDismissed && (
        <div
          role="status"
          data-testid="fv-nag-banner"
          className="flex items-start justify-between gap-3 rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-200"
        >
          <p>
            Review who has FV-leave-view permission. After migration, all
            org_admins were granted automatically — please remove anyone
            who shouldn't see these confidential requests.
          </p>
          <button
            type="button"
            onClick={dismissNag}
            data-testid="fv-nag-dismiss"
            className="shrink-0 rounded px-2 py-1 min-h-[36px] text-xs font-medium text-amber-900 dark:text-amber-100 hover:bg-amber-100 dark:hover:bg-amber-800/40"
            aria-label="Dismiss banner"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-700 dark:text-red-300"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={refresh}
            className="mt-2 px-3 py-1 min-h-[36px] rounded bg-red-600 text-white text-xs font-medium hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" label="Loading permissions" />
        </div>
      ) : sortedUsers.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 px-6 py-12 text-center text-sm text-gray-500 dark:text-gray-400">
          No users to display.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/40">
              <tr className="text-left text-xs uppercase tracking-wider text-gray-500 dark:text-gray-400">
                <th scope="col" className="px-4 py-2 font-medium">User</th>
                <th scope="col" className="px-4 py-2 font-medium">Email</th>
                <th scope="col" className="px-4 py-2 font-medium">Role</th>
                <th scope="col" className="px-4 py-2 font-medium">Granted</th>
                <th scope="col" className="px-4 py-2 font-medium text-center">FV-leave view</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {sortedUsers.map((u) => {
                const busy = busyIds.has(u.user_id)
                const errMessage =
                  rowError && rowError.id === u.user_id
                    ? rowError.message
                    : null
                return (
                  <tr
                    key={u.user_id}
                    data-testid={`permissions-row-${u.user_id}`}
                    className="hover:bg-gray-50 dark:hover:bg-gray-800/40"
                  >
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {u.name ?? '—'}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {u.email}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-200">
                      {u.role}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {formatDate(u.granted_at)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-center">
                      <label className="inline-flex items-center justify-center min-h-[44px] min-w-[44px]">
                        <span className="sr-only">
                          Toggle FV-leave-view for {u.email}
                        </span>
                        <input
                          type="checkbox"
                          data-testid={`fv-toggle-${u.user_id}`}
                          checked={u.has_fv_view}
                          disabled={busy}
                          onChange={(e) => handleToggle(u, e.target.checked)}
                          className="h-5 w-5 rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                        />
                      </label>
                      {errMessage && (
                        <p
                          role="alert"
                          className="mt-1 text-xs text-red-600 dark:text-red-400"
                        >
                          {errMessage}
                        </p>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
