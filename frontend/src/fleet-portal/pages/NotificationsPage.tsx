/**
 * Fleet Portal — Notifications inbox.
 *
 * Lists the notifications emitted by the backend that target this
 * portal user (via audience_roles). Examples: checklist failures,
 * booking acceptances/declines, quote-ready alerts.
 *
 * Implements: B2B Fleet Portal — Req 9.7, 11.2, 12.2.
 */
import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'

import { fleetClient } from '../api/client'

interface FleetNotification {
  id: string
  category: string
  severity: string
  title: string
  body: string | null
  link_url: string | null
  entity_type: string | null
  entity_id: string | null
  created_at: string | null
}

export default function NotificationsPage() {
  const [items, setItems] = useState<FleetNotification[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await fleetClient.get<{
        items: FleetNotification[]
        total: number
      }>('/notifications', { signal, params: { limit: 100 } })
      setItems(res.data?.items ?? [])
      setTotal(res.data?.total ?? 0)
    } catch (err: unknown) {
      if (!(signal?.aborted ?? false)) {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? 'Failed to load notifications.'
        setError(detail)
      }
    } finally {
      if (!(signal?.aborted ?? false)) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const c = new AbortController()
    void fetchData(c.signal)
    return () => c.abort()
  }, [fetchData])

  if (loading) return <div className="p-4 text-sm text-gray-500">Loading notifications…</div>
  if (error)
    return (
      <div
        role="alert"
        className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
      >
        {error}
      </div>
    )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Notifications</h1>
        <span className="text-xs text-gray-500">{(total ?? 0).toLocaleString()} total</span>
      </div>

      {(items ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center dark:border-gray-700">
          <p className="text-sm text-gray-500">No notifications yet.</p>
          <p className="mt-1 text-xs text-gray-400">
            You&apos;ll see updates here when bookings, quotes, or checklists change.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {(items ?? []).map((n) => {
            const sev =
              n.severity === 'success'
                ? 'border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30'
                : n.severity === 'warning'
                  ? 'border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30'
                  : n.severity === 'error'
                    ? 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30'
                    : 'border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-950'
            const Item = n.link_url ? Link : 'div'
            const props = n.link_url ? { to: n.link_url } : {}
            return (
              <li key={n.id}>
                {/* @ts-expect-error — Link/div polymorphism via dynamic component */}
                <Item
                  {...props}
                  className={`block rounded-md border px-4 py-3 ${sev} ${n.link_url ? 'hover:shadow' : ''}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white">{n.title}</p>
                      {n.body ? (
                        <p className="mt-0.5 text-xs text-gray-700 dark:text-gray-300">
                          {n.body}
                        </p>
                      ) : null}
                    </div>
                    <time className="text-[11px] text-gray-500 whitespace-nowrap">
                      {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                    </time>
                  </div>
                </Item>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
