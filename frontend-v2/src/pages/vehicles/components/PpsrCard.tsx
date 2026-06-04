/**
 * PpsrCard — Task 25 port of frontend/src/pages/vehicles/components/PpsrCard.tsx.
 *
 * Embedded on the Vehicle Profile, surfacing the latest PPSR check for a rego.
 * ALL logic is copied VERBATIM from the original: the `<ModuleGate module="ppsr">`
 * wrapper (card disappears when the module is off), the
 * `ppsrApi.listSearches({ rego, limit: 1 })` fetch with AbortController +
 * cancelled guard (safe-API Pattern 7), the empty / latest-match / forgotten
 * states, the relative-time formatter, and the deep links to
 * `/ppsr/search?rego=…`. Only presentation is remapped onto the design system:
 * the prototype has no PPSR card, so it is designed on the fly (FR-2b) using the
 * v2 card / badge language (the match chip keeps its own traffic-light palette,
 * since money-owing severity is semantic and not part of the status-pill set).
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
// and history table — money-owing severity, kept on the original palette).
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
    className: 'bg-danger-soft text-danger border border-danger/30',
  },
  PY: {
    glyph: '🔴',
    label: 'Money owing (possible)',
    className: 'bg-warn-soft text-warn border border-warn/30',
  },
  M: {
    glyph: '🟠',
    label: 'Matched',
    className: 'bg-warn-soft text-warn border border-warn/30',
  },
  PM: {
    glyph: '🟠',
    label: 'Possible match',
    className: 'bg-warn-soft text-warn border border-warn/30',
  },
  U: {
    glyph: '⚪',
    label: 'Unknown',
    className: 'bg-[#EEF0F4] text-muted border border-border',
  },
  N: {
    glyph: '🟢',
    label: 'No money owing',
    className: 'bg-ok-soft text-ok border border-ok/30',
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
 * Convert an ISO timestamp into a short relative-time string. Falls back to a
 * localised date when the timestamp is more than a week old. Copied verbatim.
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
// Card primitives — shared with the VehicleProfile look-and-feel (v2 tokens).
// ===========================================================================

const CARD_CLASSNAMES = 'rounded-card border border-border bg-card p-4 shadow-card'

const TITLE_CLASSNAMES = 'mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'

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

  // Normalise rego for both the API filter and the deep-link query string.
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
        <p className="mt-2 text-[13px] text-muted">Loading…</p>
      </section>
    )
  }

  if (error) {
    return (
      <section className={CARD_CLASSNAMES} aria-label="PPSR check" data-testid="ppsr-card">
        <p className={TITLE_CLASSNAMES}>PPSR</p>
        <p role="alert" className="mt-2 text-[13px] text-danger">{error}</p>
      </section>
    )
  }

  // Empty state — no prior search on file.
  if (!latest) {
    return (
      <section className={CARD_CLASSNAMES} aria-label="PPSR check" data-testid="ppsr-card">
        <p className={TITLE_CLASSNAMES}>PPSR</p>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[13px] text-text">No PPSR check on file for this vehicle.</p>
          <Link
            to={searchHref}
            className="inline-flex h-9 min-h-[36px] items-center self-start rounded-ctl bg-accent px-3 text-[13px] font-medium text-white shadow-sm transition-colors hover:bg-accent-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 sm:self-auto"
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
    <section className={CARD_CLASSNAMES} aria-label="PPSR check" data-testid="ppsr-card">
      <div className="flex items-start justify-between gap-2">
        <p className={TITLE_CLASSNAMES}>PPSR</p>
        <Link
          to={searchHref}
          className="inline-flex h-8 min-h-[32px] items-center rounded-ctl border border-border bg-card px-2.5 text-[12px] font-medium text-text shadow-sm transition-colors hover:bg-canvas hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1"
          data-testid="ppsr-card-rerun"
        >
          Re-run check
        </Link>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-[20px] px-2.5 py-0.5 text-[12px] font-medium ${chip.className}`}
          aria-label={chip.label}
          data-testid="ppsr-card-match-chip"
        >
          <span aria-hidden="true">{chip.glyph}</span>
          {chip.label}
        </span>
        {(latest?.statement_count ?? 0) > 0 && (
          <span className="text-[12px] text-muted">
            {latest?.statement_count ?? 0} statement
            {latest?.statement_count === 1 ? '' : 's'}
          </span>
        )}
        {isForgotten && (
          <span
            className="inline-flex items-center rounded-[20px] border border-border bg-[#EEF0F4] px-2 py-0.5 text-[12px] font-medium text-muted"
            aria-label="Payload forgotten"
          >
            Forgotten
          </span>
        )}
      </div>

      <p className="mt-2 text-[12px] text-muted">
        Last checked {lastCheckedLabel} by {userLabel}
      </p>
    </section>
  )
}

export default PpsrCard
