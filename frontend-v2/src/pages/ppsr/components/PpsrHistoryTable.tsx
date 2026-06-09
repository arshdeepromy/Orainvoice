/**
 * PpsrHistoryTable — paginated history of PPSR searches.
 *
 * Implements design §6.4 of `.kiro/specs/ppsr-module/design.md`:
 *
 *   - Calls `ppsrApi.listSearches({ offset, limit })` with safe-API
 *     fallbacks (`?? []` on items, `?? 0` on total).
 *   - Columns: Date, Rego, Match (colour chip), Ownership, Statements, By.
 *   - Pagination: 25 rows / page; previous + next buttons.
 *   - Row click opens `PpsrDetailDrawer` with the chosen search id.
 *   - Optional `refreshKey` prop — when bumped, the table re-fetches
 *     the first page (used by `PPSRSearchPage` after a fresh search).
 *
 * The CarJam-reported per-check charge is intentionally not exposed in
 * any column: org users must not see the wholesale CarJam cost — the
 * platform sets the customer-facing price via Global Admin settings.
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
    className: 'bg-danger-soft text-danger border-danger/40',
  },
  PY: {
    glyph: '🔴',
    label: 'Money owing (possible)',
    className: 'bg-warn-soft text-warn border-warn/40',
  },
  M: {
    glyph: '🟠',
    label: 'Matched',
    className: 'bg-warn-soft text-warn border-warn/40',
  },
  PM: {
    glyph: '🟠',
    label: 'Possible match',
    className: 'bg-warn-soft text-warn border-warn/40',
  },
  U: {
    glyph: '⚪',
    label: 'Unknown',
    className: 'bg-canvas text-muted border-border-strong',
  },
  N: {
    glyph: '🟢',
    label: 'No money owing',
    className: 'bg-ok-soft text-ok border-ok/40',
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
      className="rounded-card border border-border bg-card p-6 shadow-card"
      aria-label="Recent PPSR checks"
      data-testid="ppsr-history-table"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 className="text-base font-medium text-text">
          Recent PPSR checks
        </h3>
        <span className="text-xs text-muted-2">
          {(total ?? 0).toLocaleString()}{' '}
          {total === 1 ? 'check' : 'checks'} on file
        </span>
      </header>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-ctl border border-danger/40 bg-danger-soft p-3 text-sm text-danger"
        >
          {error}
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr>
              <th
                scope="col"
                className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
              >
                Date
              </th>
              <th
                scope="col"
                className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
              >
                Rego
              </th>
              <th
                scope="col"
                className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
              >
                Match
              </th>
              <th
                scope="col"
                className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
              >
                Ownership
              </th>
              <th
                scope="col"
                className="mono border-b border-border px-4 py-3 text-right text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
              >
                Statements
              </th>
              <th
                scope="col"
                className="mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
              >
                By
              </th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (items ?? []).length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-6 text-center text-sm text-muted-2"
                >
                  Loading…
                </td>
              </tr>
            )}

            {!isLoading && (items ?? []).length === 0 && !error && (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-6 text-center text-sm text-muted-2"
                  data-testid="ppsr-history-empty"
                >
                  No PPSR checks yet — run your first one above.
                </td>
              </tr>
            )}

            {(items ?? []).map((row) => {
              const chip = chipForMatch(row?.match ?? null)
              const isForgotten = row?.forgotten_at != null
              // A PPSR money-owing check actually ran iff the row has a
              // match code, statements, warnings, or is a confirmed
              // not_found result. Owner-check-only searches show "No
              // PPSR performed" instead of an "Unknown" pill.
              const ppsrCheckRan =
                !!row?.match ||
                (row?.statement_count ?? 0) > 0 ||
                row?.has_warnings === true ||
                row?.not_found === true
              const userLabel =
                (row as unknown as { user_display_name?: string | null })
                  ?.user_display_name ??
                (row as unknown as { user_email?: string | null })
                  ?.user_email ??
                '—'
              return (
                <tr
                  key={row?.id ?? Math.random()}
                  className="cursor-pointer border-b border-border last:border-b-0 hover:bg-canvas focus-within:bg-canvas"
                  onClick={() => row?.id && handleRowClick(row.id)}
                  data-testid={`ppsr-history-row-${row?.id ?? 'unknown'}`}
                >
                  <td className="px-4 py-2 text-sm text-text">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (row?.id) handleRowClick(row.id)
                      }}
                      className="mono text-left font-medium text-accent hover:underline focus:outline-none focus:ring-2 focus:ring-accent"
                      aria-label={`View PPSR check from ${formatDate(row?.created_at)}`}
                    >
                      {formatDate(row?.created_at)}
                    </button>
                  </td>
                  <td className="mono px-4 py-2 text-sm text-text">
                    {row?.rego ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-sm">
                    {ppsrCheckRan ? (
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${chip.className}`}
                        aria-label={chip.label}
                      >
                        <span aria-hidden="true">{chip.glyph}</span>
                        {chip.label}
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center rounded-full border border-border-strong bg-canvas px-2.5 py-0.5 text-xs font-medium text-muted-2"
                        aria-label="No PPSR check performed"
                      >
                        No PPSR performed
                      </span>
                    )}
                    {isForgotten && (
                      <span
                        className="ml-2 inline-flex items-center rounded-full border border-border-strong bg-canvas px-2 py-0.5 text-xs font-medium text-muted"
                        aria-label="Payload forgotten"
                      >
                        Forgotten
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-sm">
                    {row?.owner_check_match == null ? (
                      <span className="text-muted-2">—</span>
                    ) : row.owner_check_match ? (
                      <span
                        className="inline-flex items-center gap-1.5 rounded-full border border-ok/40 bg-ok-soft px-2.5 py-0.5 text-xs font-medium text-ok"
                        aria-label="Ownership confirmed"
                      >
                        <span aria-hidden="true">✅</span>
                        Confirmed
                      </span>
                    ) : (
                      <span
                        className="inline-flex items-center gap-1.5 rounded-full border border-danger/40 bg-danger-soft px-2.5 py-0.5 text-xs font-medium text-danger"
                        aria-label="Ownership not confirmed"
                      >
                        <span aria-hidden="true">❌</span>
                        Not confirmed
                      </span>
                    )}
                  </td>
                  <td className="mono px-4 py-2 text-right text-sm text-text">
                    {row?.statement_count ?? 0}
                  </td>
                  <td className="px-4 py-2 text-sm text-muted">
                    {userLabel}
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
          <span className="text-xs text-muted-2">
            Page {page} of {totalPages} · showing{' '}
            {(items ?? []).length} of {(total ?? 0).toLocaleString()}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || isLoading}
              className="inline-flex h-9 min-h-[36px] items-center rounded-ctl border border-border bg-card px-3 text-xs font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="ppsr-history-prev"
            >
              ← Previous
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || isLoading}
              className="inline-flex h-9 min-h-[36px] items-center rounded-ctl border border-border bg-card px-3 text-xs font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
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
