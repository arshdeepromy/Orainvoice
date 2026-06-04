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
} from '@/api/leave'
import { Spinner } from '@/components/ui'

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
        <h1 className="text-xl font-semibold text-text">
          Family-Violence Leave Visibility
        </h1>
        <p className="text-sm text-muted">
          Grant or revoke permission to view confidential family-violence
          leave requests.
        </p>
      </div>

      {!nagDismissed && (
        <div
          role="status"
          data-testid="fv-nag-banner"
          className="flex items-start justify-between gap-3 rounded-ctl border border-warn bg-warn-soft px-4 py-3 text-sm text-warn"
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
            className="shrink-0 rounded-ctl px-2 py-1 min-h-[36px] text-xs font-medium text-warn hover:bg-warn-soft"
            aria-label="Dismiss banner"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-ctl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          <p>{error}</p>
          <button
            type="button"
            onClick={refresh}
            className="mt-2 px-3 py-1 min-h-[36px] rounded-ctl bg-danger text-white text-xs font-medium hover:brightness-95"
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
        <div className="rounded-card border border-dashed border-border bg-card px-6 py-12 text-center text-sm text-muted">
          No users to display.
        </div>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-card shadow-card">
          <table className="min-w-full text-sm">
            <thead>
              <tr>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">User</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Email</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Role</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">Granted</th>
                <th scope="col" className="mono border-b border-border px-4 py-3 text-center text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2">FV-leave view</th>
              </tr>
            </thead>
            <tbody>
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
                    className="border-b border-border last:border-b-0 hover:bg-canvas"
                  >
                    <td className="px-4 py-2 whitespace-nowrap text-text">
                      {u.name ?? '—'}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-muted">
                      {u.email}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-text">
                      {u.role}
                    </td>
                    <td className="mono px-4 py-2 whitespace-nowrap text-muted">
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
                          className="h-5 w-5 rounded border-border text-accent focus:ring-2 focus:ring-accent disabled:opacity-50"
                        />
                      </label>
                      {errMessage && (
                        <p
                          role="alert"
                          className="mt-1 text-xs text-danger"
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
