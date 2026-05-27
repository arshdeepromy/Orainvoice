/**
 * Email Delivery Health view — Phase 8c task 9.11.
 *
 * Renders aggregate bounce stats (24h / 7d / 30d, broken down by
 * provider) plus a paginated table of recent bounce rows from
 * ``bounced_addresses``. Admins can clear individual bounces via the
 * Action column; the next outbound to the cleared address is then
 * attempted normally.
 *
 * Per design Risks > Decisions deferred this lives in a separate file
 * but is rendered as a tab inside ``EmailProviders.tsx`` so the route
 * stays stable.
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'
import { ToastContainer, useToast } from '@/components/ui/Toast'

// ---------------------------------------------------------------------------
// Types — must match the Phase 8c backend schemas in
// app/modules/email_providers/schemas.py
// ---------------------------------------------------------------------------

interface WindowStats {
  total: number
  by_provider: Record<string, number>
}

interface DeliveryHealthStats {
  last_24h: WindowStats
  last_7d: WindowStats
  last_30d: WindowStats
}

interface BounceRow {
  id: string
  org_id: string | null
  email_address: string
  bounce_kind: string
  reason: string | null
  first_seen_at: string
  last_seen_at: string
  hit_count: number
  expires_at: string | null
  linked_customer_id: string | null
  linked_user_id: string | null
  provider_key: string | null
}

interface DeliveryHealthResponse {
  stats: DeliveryHealthStats
  recent_bounces: BounceRow[]
  total: number
}

const EMPTY_WINDOW: WindowStats = { total: 0, by_provider: {} }
const EMPTY_STATS: DeliveryHealthStats = {
  last_24h: EMPTY_WINDOW,
  last_7d: EMPTY_WINDOW,
  last_30d: EMPTY_WINDOW,
}

// ---------------------------------------------------------------------------
// DeliveryStatsCards — three cards (24h / 7d / 30d)
// ---------------------------------------------------------------------------

function StatBar({
  count,
  total,
  label,
}: {
  count: number
  total: number
  label: string
}) {
  // Width is the share of this provider against the total. Floor at 4%
  // so non-zero providers always show a sliver.
  const pct = total > 0 ? Math.max(4, Math.round((count / total) * 100)) : 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 truncate text-gray-700 dark:text-gray-200">
        {label}
      </span>
      <div className="relative h-2 flex-1 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
        <div
          className="h-full bg-amber-500"
          style={{ width: `${pct}%` }}
          aria-hidden
        />
      </div>
      <span className="w-10 shrink-0 text-right tabular-nums text-gray-700 dark:text-gray-200">
        {(count ?? 0).toLocaleString()}
      </span>
    </div>
  )
}

function DeliveryStatsCard({
  title,
  window: w,
}: {
  title: string
  window: WindowStats
}) {
  const total = w?.total ?? 0
  const byProvider = w?.by_provider ?? {}
  const providers = Object.entries(byProvider).sort(
    ([, a], [, b]) => (b ?? 0) - (a ?? 0),
  )
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
        {title}
      </p>
      <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100 tabular-nums">
        {total.toLocaleString()}
        <span className="ml-1 text-sm font-normal text-gray-500">
          {total === 1 ? 'bounce' : 'bounces'}
        </span>
      </p>
      {providers.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {providers.map(([key, count]) => (
            <StatBar
              key={key}
              count={count ?? 0}
              total={total}
              label={key}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function DeliveryStatsCards({ stats }: { stats: DeliveryHealthStats }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <DeliveryStatsCard
        title="Last 24 hours"
        window={stats?.last_24h ?? EMPTY_WINDOW}
      />
      <DeliveryStatsCard
        title="Last 7 days"
        window={stats?.last_7d ?? EMPTY_WINDOW}
      />
      <DeliveryStatsCard
        title="Last 30 days"
        window={stats?.last_30d ?? EMPTY_WINDOW}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// BounceTable — recent bounce rows + Clear action
// ---------------------------------------------------------------------------

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function BounceKindBadge({ kind }: { kind: string }) {
  const palette: Record<string, string> = {
    hard: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200',
    soft: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200',
    blocked: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
  }
  const cls = palette[kind] ?? palette.soft
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {kind}
    </span>
  )
}

function ConfirmClearModal({
  email,
  busy,
  onConfirm,
  onCancel,
}: {
  email: string
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
    >
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl dark:bg-gray-800">
        <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Clear bounce?
        </h3>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          The next email to <strong>{email}</strong> will be attempted
          normally. If the address is still invalid, the bounce will be
          recorded again.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm} loading={busy}>
            Clear bounce
          </Button>
        </div>
      </div>
    </div>
  )
}

function BounceTable({
  rows,
  onClear,
  clearingId,
}: {
  rows: BounceRow[]
  onClear: (row: BounceRow) => void
  clearingId: string | null
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center dark:border-gray-700 dark:bg-gray-800">
        <p className="text-sm text-gray-600 dark:text-gray-300">
          No bounces in the last 30 days. ✓
        </p>
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead className="bg-gray-50 dark:bg-gray-900">
          <tr>
            {[
              'Recipient',
              'Provider',
              'Kind',
              'Reason',
              'First seen',
              'Last seen',
              'Hits',
              'Expires',
              'Action',
            ].map((header) => (
              <th
                key={header}
                className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {rows.map((row) => (
            <tr key={row.id} className="text-sm text-gray-700 dark:text-gray-200">
              <td className="px-3 py-2">
                <div className="flex flex-col">
                  <span className="font-medium">{row.email_address}</span>
                  {row.linked_customer_id && (
                    <a
                      className="text-xs text-blue-600 hover:underline dark:text-blue-400"
                      href={`/customers/${row.linked_customer_id}`}
                    >
                      View customer
                    </a>
                  )}
                </div>
              </td>
              <td className="px-3 py-2">{row.provider_key ?? '—'}</td>
              <td className="px-3 py-2">
                <BounceKindBadge kind={row.bounce_kind} />
              </td>
              <td className="px-3 py-2 max-w-xs truncate" title={row.reason ?? ''}>
                {row.reason ?? '—'}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {formatDate(row.first_seen_at)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {formatDate(row.last_seen_at)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {(row.hit_count ?? 0).toLocaleString()}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {row.expires_at ? formatDate(row.expires_at) : 'never'}
              </td>
              <td className="px-3 py-2">
                <Button
                  variant="secondary"
                  onClick={() => onClear(row)}
                  loading={clearingId === row.id}
                  disabled={Boolean(clearingId) && clearingId !== row.id}
                >
                  Clear
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function EmailDeliveryHealth() {
  const [stats, setStats] = useState<DeliveryHealthStats>(EMPTY_STATS)
  const [bounces, setBounces] = useState<BounceRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pendingClear, setPendingClear] = useState<BounceRow | null>(null)
  const [clearingId, setClearingId] = useState<string | null>(null)
  const { toasts, addToast, dismissToast } = useToast()

  const fetchHealth = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get<DeliveryHealthResponse>(
        '/api/v2/admin/email-providers/delivery-health',
        { params: { offset: 0, limit: 100 }, signal },
      )
      setStats(res.data?.stats ?? EMPTY_STATS)
      setBounces(res.data?.recent_bounces ?? [])
    } catch (err) {
      if ((err as { name?: string })?.name === 'CanceledError') return
      setError("Couldn't load delivery health.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
    return () => controller.abort()
  }, [fetchHealth])

  async function handleConfirmClear() {
    if (!pendingClear) return
    setClearingId(pendingClear.id)
    try {
      await apiClient.delete(
        `/api/v2/admin/email-providers/bounced-addresses/${pendingClear.id}`,
      )
      addToast('success', `Cleared bounce for ${pendingClear.email_address}`)
      setPendingClear(null)
      await fetchHealth()
    } catch {
      addToast('error', "Couldn't clear bounce")
    } finally {
      setClearingId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="lg" label="Loading delivery health" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      {error && <AlertBanner variant="error">{error}</AlertBanner>}
      <DeliveryStatsCards stats={stats} />
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Recent bounces
          </h2>
          <button
            onClick={() => fetchHealth()}
            className="text-xs text-blue-600 hover:underline dark:text-blue-400"
            type="button"
          >
            Refresh
          </button>
        </div>
        <BounceTable
          rows={bounces}
          onClear={setPendingClear}
          clearingId={clearingId}
        />
      </div>
      {pendingClear && (
        <ConfirmClearModal
          email={pendingClear.email_address}
          busy={clearingId === pendingClear.id}
          onConfirm={handleConfirmClear}
          onCancel={() => setPendingClear(null)}
        />
      )}
    </div>
  )
}

export default EmailDeliveryHealth
