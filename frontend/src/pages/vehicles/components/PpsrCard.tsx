/**
 * PpsrCard — embed on the Vehicle Profile that surfaces the latest
 * PPSR check for a given rego.
 *
 * Implements design §6.5 of `.kiro/specs/ppsr-module/design.md`:
 *
 *   - Outer wrapper renders `<ModuleGate module="ppsr">` so the card
 *     disappears entirely when the PPSR module is disabled for this
 *     org. (G-CODE-3 — the prop is `module`, not `moduleSlug`, per
 *     `frontend/src/components/common/ModuleGate.tsx`.)
 *   - Inner component fetches the most recent PPSR search for `rego`
 *     via `ppsrApi.listSearches({ rego, limit: 1 })` with an
 *     `AbortController` (per safe-api-consumption.md Pattern 7).
 *   - Empty state — "No PPSR check on file for this vehicle" plus a
 *     "Run PPSR check now" CTA that navigates to
 *     `/ppsr/search?rego=<rego>`.
 *   - Latest-match state — colour chip (matches the traffic-light
 *     palette used by `PpsrResultPanel` / `PpsrHistoryTable`) plus
 *     "Last checked <relative-date>" line + a "Re-run check" button.
 *
 * Safe-API patterns: every API consumption uses `?.` + `?? []` /
 * `?? 0`. No `as any`. Strict typed generics on the API call.
 *
 * **Validates: PPSR module spec task D5**
 */

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ModuleGate } from '@/components/common/ModuleGate'
import {
  ppsrApi,
  type PpsrMatch,
  type PpsrSearchSummary,
} from '@/api/ppsr'

// ===========================================================================
// Match-chip palette (mirrors the design tokens used by the result panel
// and history table — keep in sync with design.md §6.0).
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

/**
 * Convert an ISO timestamp into a short relative-time string. Falls
 * back to a localised date when the timestamp is more than a week
 * old. Tiny inline implementation — no `Intl.RelativeTimeFormat`
 * polyfill needed because we only emit a handful of buckets.
 */
function formatRelative(iso: string | null | undefined): string {
  if (!iso) return 'unknown date'
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return 'unknown date'

  const now = Date.now()
  const diffMs = now - then.getTime()
  const diffSec = Math.round(diffMs / 1000)
  const diffMin = Math.round(diffSec / 60)
  const diffHr = Math.round(diffMin / 60)
  const diffDay = Math.round(diffHr / 24)

  if (diffSec < 45) return 'just now'
  if (diffMin < 60) return `${diffMin} min ago`
  if (diffHr < 24) return `${diffHr} hour${diffHr === 1 ? '' : 's'} ago`
  if (diffDay < 7) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`

  return then.toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

// ===========================================================================
// Card primitives — shared with VehicleProfile look-and-feel.
// ===========================================================================

const CARD_CLASSNAMES =
  'rounded-lg border border-gray-200 bg-white p-4 shadow-sm ' +
  'dark:border-gray-700 dark:bg-gray-800'

const TITLE_CLASSNAMES =
  'text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400'

// ===========================================================================
// Public wrapper — Module-gated. Inner component only mounts when PPSR
// is enabled, which means the API call is also gated.
// ===========================================================================

export interface PpsrCardProps {
  rego: string
}

export function PpsrCard({ rego }: PpsrCardProps) {
  return (
    <ModuleGate module="ppsr">
      <PpsrCardInner rego={rego} />
    </ModuleGate>
  )
}

// ===========================================================================
// Inner component — does the actual fetch + render.
// ===========================================================================

function PpsrCardInner({ rego }: PpsrCardProps) {
  const [latest, setLatest] = useState<PpsrSearchSummary | null>(null)
  const [isLoading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Normalise rego for both the API filter and the deep-link query string
  // so the search page lands in the same case as the row stored in the DB.
  const regoNorm = useMemo(() => (rego ?? '').trim().toUpperCase(), [rego])
  const searchHref = `/ppsr/search?rego=${encodeURIComponent(regoNorm)}`

  useEffect(() => {
    if (!regoNorm) {
      setLatest(null)
      setLoading(false)
      return
    }

    const controller = new AbortController()
    let cancelled = false

    async function fetchLatest() {
      setLoading(true)
      setError(null)
      try {
        const res = await ppsrApi.listSearches(
          { rego: regoNorm, limit: 1 },
          controller.signal,
        )
        if (cancelled) return
        const items = res?.items ?? []
        setLatest(items[0] ?? null)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if (cancelled) return
        const message =
          err instanceof Error ? err.message : 'Failed to load PPSR check'
        setError(message)
        setLatest(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchLatest()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [regoNorm])

  // ----- Render --------------------------------------------------------

  if (isLoading) {
    return (
      <section className={CARD_CLASSNAMES} aria-label="PPSR check" data-testid="ppsr-card">
        <p className={TITLE_CLASSNAMES}>PPSR</p>
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
          Loading…
        </p>
      </section>
    )
  }

  if (error) {
    return (
      <section className={CARD_CLASSNAMES} aria-label="PPSR check" data-testid="ppsr-card">
        <p className={TITLE_CLASSNAMES}>PPSR</p>
        <p
          role="alert"
          className="mt-2 text-sm text-red-700 dark:text-red-300"
        >
          {error}
        </p>
      </section>
    )
  }

  // Empty state — no prior search on file.
  if (!latest) {
    return (
      <section
        className={CARD_CLASSNAMES}
        aria-label="PPSR check"
        data-testid="ppsr-card"
      >
        <p className={TITLE_CLASSNAMES}>PPSR</p>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-gray-700 dark:text-gray-300">
            No PPSR check on file for this vehicle.
          </p>
          <Link
            to={searchHref}
            className="inline-flex h-9 min-h-[36px] items-center self-start rounded-md bg-blue-600 px-3 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 dark:bg-blue-500 dark:hover:bg-blue-400 sm:self-auto"
            data-testid="ppsr-card-run-now"
          >
            Run PPSR check now
          </Link>
        </div>
      </section>
    )
  }

  // Latest-match state.
  const chip = chipForMatch(latest?.match ?? null)
  const isForgotten = latest?.forgotten_at != null
  const lastCheckedLabel = formatRelative(latest?.created_at ?? null)
  const userLabel =
    (latest as unknown as { user_email?: string | null })?.user_email ??
    latest?.user_id ??
    'unknown user'

  return (
    <section
      className={CARD_CLASSNAMES}
      aria-label="PPSR check"
      data-testid="ppsr-card"
    >
      <div className="flex items-start justify-between gap-2">
        <p className={TITLE_CLASSNAMES}>PPSR</p>
        <Link
          to={searchHref}
          className="inline-flex h-8 min-h-[32px] items-center rounded-md border border-gray-300 bg-white px-2.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          data-testid="ppsr-card-rerun"
        >
          Re-run check
        </Link>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${chip.className}`}
          aria-label={chip.label}
          data-testid="ppsr-card-match-chip"
        >
          <span aria-hidden="true">{chip.glyph}</span>
          {chip.label}
        </span>
        {(latest?.statement_count ?? 0) > 0 && (
          <span className="text-xs text-gray-600 dark:text-gray-400">
            {latest?.statement_count ?? 0} statement
            {latest?.statement_count === 1 ? '' : 's'}
          </span>
        )}
        {isForgotten && (
          <span
            className="inline-flex items-center rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:border-slate-600 dark:bg-slate-700/40 dark:text-slate-200"
            aria-label="Payload forgotten"
          >
            Forgotten
          </span>
        )}
      </div>

      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        Last checked {lastCheckedLabel} by {userLabel}
      </p>
    </section>
  )
}

export default PpsrCard
