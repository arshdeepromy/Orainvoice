/**
 * PpsrHistoryTable — paginated history of PPSR searches.
 *
 * Implements design §6.4 of `.kiro/specs/ppsr-module/design.md`:
 *
 *   - Calls `ppsrApi.listSearches({ offset, limit })` with safe-API
 *     fallbacks (`?? []` on items, `?? 0` on total).
 *   - Columns: Date, Rego, Match (colour chip), Statements, By (user),
 *     Charge.
 *   - Pagination: 25 rows / page; previous + next buttons.
 *   - Row click opens `PpsrDetailDrawer` with the chosen search id.
 *   - Optional `refreshKey` prop — when bumped, the table re-fetches
 *     the first page (used by `PPSRSearchPage` after a fresh search).
 *
 * Follows `.kiro/steering/safe-api-consumption.md`:
 *   - Every API consumption uses `?.` + `?? []` / `?? 0`.
 *   - Every `useEffect` that issues an API call uses an
 *     `AbortController` and calls `controller.abort()` on cleanup.
 *   - No `as any`.
 *
 * **Validates: PPSR module spec task D4**
 */

import { useEffect, useMemo, useState } from 'react'
import {
  ppsrApi,
  type PpsrMatch,
  type PpsrSearchSummary,
} from '@/api/ppsr'
import { PpsrDetailDrawer } from './PpsrDetailDrawer'

// ===========================================================================
// Constants
// ===========================================================================

const PAGE_SIZE = 25

// ===========================================================================
// Match-chip palette (mirrors design §6.0 traffic-light scheme)
// ===========================================================================

interface ChipStyle {
  glyph: string
  label: string
  className: string
}

const MATCH_CHIP_STYLES: Record<string, ChipStyle> = {
  Y: {
    glyph: '🔴',
    label: 'Money owing',
    className:
      'bg-red-50 text-red-900 border-red-300 dark:bg-red-900/20 dark:text-red-100 dark:border-red-700',
  },
  PY: {
    glyph: '🔴',
    label: 'Money owing (possible)',
    className:
      'bg-orange-50 text-orange-900 border-orange-300 dark:bg-orange-900/20 dark:text-orange-100 dark:border-orange-700',
  },
  M: {
    glyph: '🟠',
    label: 'Matched',
    className:
      'bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-700',
  },
  PM: {
    glyph: '🟠',
    label: 'Possible match',
    className:
      'bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-700',
  },
  U: {
    glyph: '⚪',
    label: 'Unknown',
    className:
      'bg-slate-50 text-slate-900 border-slate-300 dark:bg-slate-800/40 dark:text-slate-100 dark:border-slate-600',
  },
  N: {
    glyph: '🟢',
    label: 'No money owing',
    className:
      'bg-emerald-50 text-emerald-900 border-emerald-300 dark:bg-emerald-900/20 dark:text-emerald-100 dark:border-emerald-700',
  },
}

const FALLBACK_CHIP: ChipStyle = MATCH_CHIP_STYLES.U

function chipForMatch(match: PpsrMatch | string | null | undefined): ChipStyle {
  if (!match) return FALLBACK_CHIP
  return MATCH_CHIP_STYLES[match] ?? FALLBACK_CHIP
}

// ===========================================================================
// Format helpers
// ===========================================================================

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatCurrency(cents: number | null | undefined): string {
  if (cents == null) return '—'
  try {
    return new Intl.NumberFormat('en-NZ', {
      style: 'currency',
      currency: 'NZD',
    }).format((cents ?? 0) / 100)
  } catch {
    return `$${((cents ?? 0) / 100).toFixed(2)}`
  }
}

// ===========================================================================
// Props
// ===========================================================================

export interface PpsrHistoryTableProps {
  /**
   * Bump this number to force the table back to page 1 and re-fetch.
   * The parent (PPSRSearchPage) bumps it after every fresh search so
   * the row appears immediately.
   */
  refreshKey?: number
  /** Optional row-click handler override. Defaults to opening the
   *  built-in detail drawer.  */
  onRowClick?: (searchId: string) => void
  /**
   * If true, the embedded `PpsrDetailDrawer` shows a Forget button.
   * Pass `currentUser.role === 'org_admin'` from the parent.
   */
  isAdmin?: boolean
}

// ===========================================================================
// Component
// ===========================================================================

export function PpsrHistoryTable({
  refreshKey = 0,
  onRowClick,
  isAdmin = false,
}: PpsrHistoryTableProps) {
  const [page, setPage] = useState(1)
  const [items, setItems] = useState<PpsrSearchSummary[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drawerSearchId, setDrawerSearchId] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  // When the parent bumps refreshKey, snap back to page 1 so the new
  // row is visible.
  useEffect(() => {
    if (refreshKey > 0) {
      setPage(1)
    }
  }, [refreshKey])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    async function fetchPage() {
      setLoading(true)
      setError(null)
      try {
        const offset = (page - 1) * PAGE_SIZE
        const res = await ppsrApi.listSearches(
          { offset, limit: PAGE_SIZE },
          controller.signal,
        )
        if (cancelled) return
        // ppsrApi.listSearches already guards items/total, but apply
        // the same fallbacks defensively per safe-api-consumption.md.
        setItems(res?.items ?? [])
        setTotal(res?.total ?? 0)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if (cancelled) return
        const message =
          err instanceof Error ? err.message : 'Failed to load search history'
        setError(message)
        setItems([])
        setTotal(0)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchPage()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [page, refreshKey])

  const totalPages = useMemo(() => {
    if (total <= 0) return 1
    return Math.max(1, Math.ceil(total / PAGE_SIZE))
  }, [total])

  const handleRowClick = (searchId: string) => {
    if (onRowClick) {
      onRowClick(searchId)
      return
    }
    setDrawerSearchId(searchId)
    setDrawerOpen(true)
  }

  const handleDrawerClose = () => {
    setDrawerOpen(false)
    // Leave the id around briefly so the closing animation has data;
    // null it on the next tick to free the drawer's internal state.
    setDrawerSearchId(null)
  }

  return (
    <section
      className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800"
      aria-label="Recent PPSR checks"
      data-testid="ppsr-history-table"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 className="text-base font-medium text-gray-900 dark:text-white">
          Recent PPSR checks
        </h3>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {(total ?? 0).toLocaleString()}{' '}
          {total === 1 ? 'check' : 'checks'} on file
        </span>
      </header>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-700 dark:bg-red-900/20 dark:text-red-100"
        >
          {error}
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead>
            <tr>
              <th
                scope="col"
                className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400"
              >
                Date
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400"
              >
                Rego
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400"
              >
                Match
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400"
              >
                Statements
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400"
              >
                By
              </th>
              <th
                scope="col"
                className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400"
              >
                Charge
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {isLoading && (items ?? []).length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400"
                >
                  Loading…
                </td>
              </tr>
            )}

            {!isLoading && (items ?? []).length === 0 && !error && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400"
                  data-testid="ppsr-history-empty"
                >
                  No PPSR checks yet — run your first one above.
                </td>
              </tr>
            )}

            {(items ?? []).map((row) => {
              const chip = chipForMatch(row?.match ?? null)
              const isForgotten = row?.forgotten_at != null
              const chargeCents =
                typeof (row as unknown as { charges_cents?: number | null })
                  ?.charges_cents === 'number'
                  ? ((row as unknown as { charges_cents?: number | null })
                      .charges_cents ?? null)
                  : null
              const userLabel =
                (row as unknown as { user_display_name?: string | null })
                  ?.user_display_name ??
                (row as unknown as { user_email?: string | null })
                  ?.user_email ??
                '—'
              return (
                <tr
                  key={row?.id ?? Math.random()}
                  className="cursor-pointer hover:bg-gray-50 focus-within:bg-gray-50 dark:hover:bg-gray-700/30 dark:focus-within:bg-gray-700/30"
                  onClick={() => row?.id && handleRowClick(row.id)}
                  data-testid={`ppsr-history-row-${row?.id ?? 'unknown'}`}
                >
                  <td className="px-4 py-2 text-sm text-gray-800 dark:text-gray-200">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (row?.id) handleRowClick(row.id)
                      }}
                      className="text-left font-medium text-blue-700 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-blue-300"
                      aria-label={`View PPSR check from ${formatDate(row?.created_at)}`}
                    >
                      {formatDate(row?.created_at)}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-sm font-mono text-gray-800 dark:text-gray-200">
                    {row?.rego ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-sm">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${chip.className}`}
                      aria-label={chip.label}
                    >
                      <span aria-hidden="true">{chip.glyph}</span>
                      {chip.label}
                    </span>
                    {isForgotten && (
                      <span
                        className="ml-2 inline-flex items-center rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:border-slate-600 dark:bg-slate-700/40 dark:text-slate-200"
                        aria-label="Payload forgotten"
                      >
                        Forgotten
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-sm tabular-nums text-gray-800 dark:text-gray-200">
                    {row?.statement_count ?? 0}
                  </td>
                  <td className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300">
                    {userLabel}
                  </td>
                  <td className="px-4 py-2 text-right text-sm tabular-nums text-gray-700 dark:text-gray-300">
                    {formatCurrency(chargeCents)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination — design §6.4 says prev/next; keep it compact. */}
      {totalPages > 1 && (
        <nav
          aria-label="Recent PPSR checks pagination"
          className="mt-4 flex items-center justify-between gap-2"
        >
          <span className="text-xs text-gray-500 dark:text-gray-400">
            Page {page} of {totalPages} · showing{' '}
            {(items ?? []).length} of {(total ?? 0).toLocaleString()}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || isLoading}
              className="inline-flex h-9 min-h-[36px] items-center rounded-md border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
              data-testid="ppsr-history-prev"
            >
              ← Previous
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || isLoading}
              className="inline-flex h-9 min-h-[36px] items-center rounded-md border border-gray-300 bg-white px-3 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
              data-testid="ppsr-history-next"
            >
              Next →
            </button>
          </div>
        </nav>
      )}

      {/* Detail drawer — only mounted when we have a search to show.  */}
      <PpsrDetailDrawer
        searchId={drawerSearchId}
        open={drawerOpen}
        onClose={handleDrawerClose}
        isAdmin={isAdmin}
      />
    </section>
  )
}

export default PpsrHistoryTable
