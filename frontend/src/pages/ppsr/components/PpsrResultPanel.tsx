/**
 * PpsrResultPanel — structured renderer for a PPSR search result.
 *
 * Implements design §6.3 of `.kiro/specs/ppsr-module/design.md`:
 *
 *   1. Money-owing banner (traffic-light coloured per match value)
 *   2. Cached badge (when result.cached === true)
 *   3. Basic vehicle summary (when basic is non-null)
 *   4. Financing statements table (when ppsr_details non-empty)
 *   5. Warnings rows (when warnings non-empty)
 *   6. Ownership table (when ownership_history or current_owner present)
 *   7. Charges footer (currency-formatted via Intl.NumberFormat)
 *   8. Actions row — Export PDF / Save / New
 *
 * Presentational only — no API calls, all I/O is delegated to callback
 * props supplied by the parent (PPSRSearchPage). Follows
 * `.kiro/steering/safe-api-consumption.md` patterns: every API-sourced
 * field is guarded with `?.` and `?? []` / `?? 0`. No `as any`.
 *
 * **Validates: PPSR module spec task D3**
 */

import { useLocale } from '@/contexts/LocaleContext'
import type { PpsrMatch, PpsrSearchResult } from '@/api/ppsr'

// ===========================================================================
// Props
// ===========================================================================

export interface PpsrResultPanelProps {
  result: PpsrSearchResult
  /** Trigger PDF download for this search id (parent wires the API call). */
  onExport?: () => void
  /** Save / link the report against an existing OrgVehicle row. */
  onLink?: () => void
  /** Reset the form to start a new search. */
  onNew?: () => void
  /** Bypass the 5-min cache and re-run the search against CarJam. */
  onForceRefresh?: () => void
}

// ===========================================================================
// Match → traffic-light style table
// (Tailwind class palette per design.md §6.0)
// ===========================================================================

interface MatchStyle {
  glyph: string
  glyphLabel: string
  headline: string
  banner: string
}

const MATCH_STYLES: Record<string, MatchStyle> = {
  Y: {
    glyph: '🔴',
    glyphLabel: 'Red — money owing',
    headline: 'Money Owing',
    banner:
      'bg-red-50 text-red-900 border-red-300 dark:bg-red-900/20 dark:text-red-100 dark:border-red-700',
  },
  PY: {
    glyph: '🔴',
    glyphLabel: 'Red — possible match, money owing',
    headline: 'Money Owing (possible match)',
    banner:
      'bg-orange-50 text-orange-900 border-orange-300 dark:bg-orange-900/20 dark:text-orange-100 dark:border-orange-700',
  },
  M: {
    glyph: '🟠',
    glyphLabel: 'Amber — matched, no money owing',
    headline: 'Matched — no money owing',
    banner:
      'bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-700',
  },
  PM: {
    glyph: '🟠',
    glyphLabel: 'Amber — possible match, no money owing',
    headline: 'Possible match — no money owing',
    banner:
      'bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-900/20 dark:text-amber-100 dark:border-amber-700',
  },
  U: {
    glyph: '⚪',
    glyphLabel: 'Slate — unknown',
    headline: 'Unknown',
    banner:
      'bg-slate-50 text-slate-900 border-slate-300 dark:bg-slate-800/40 dark:text-slate-100 dark:border-slate-600',
  },
  N: {
    glyph: '🟢',
    glyphLabel: 'Green — no money owing',
    headline: 'No money owing',
    banner:
      'bg-emerald-50 text-emerald-900 border-emerald-300 dark:bg-emerald-900/20 dark:text-emerald-100 dark:border-emerald-700',
  },
}

const FALLBACK_STYLE: MatchStyle = MATCH_STYLES.U

function styleForMatch(match: PpsrMatch | string | null | undefined): MatchStyle {
  if (!match) return FALLBACK_STYLE
  return MATCH_STYLES[match] ?? FALLBACK_STYLE
}

// ===========================================================================
// Field-extraction helpers (defensive — Records of unknowns from the API)
// ===========================================================================

function readString(record: Record<string, unknown> | null | undefined, ...keys: string[]): string {
  if (!record) return ''
  for (const k of keys) {
    const v = record[k]
    if (typeof v === 'string' && v.trim().length > 0) return v
    if (typeof v === 'number') return String(v)
  }
  return ''
}

function formatCachedAt(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function formatRegistrationDate(raw: string): string {
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

// ===========================================================================
// Card / panel base classes (design.md §6.0)
// ===========================================================================

const CARD =
  'rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800'
const SECTION_TITLE =
  'text-base font-medium text-gray-900 dark:text-white'
const BODY_TEXT = 'text-sm text-gray-700 dark:text-gray-300'
const TABLE_HEADER =
  'px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400'
const TABLE_CELL = 'px-4 py-2 text-sm text-gray-800 dark:text-gray-200'

// ===========================================================================
// Component
// ===========================================================================

export function PpsrResultPanel({
  result,
  onExport,
  onLink,
  onNew,
  onForceRefresh,
}: PpsrResultPanelProps) {
  const { locale } = useLocale()

  // Safe destructuring — every field guarded per safe-api-consumption.md.
  const match = result?.match ?? null
  const matchDescription = result?.match_description ?? ''
  const statementCount = result?.statement_count ?? 0
  const ppsrDetails = result?.ppsr_details ?? []
  const warnings = result?.warnings ?? []
  const ownershipHistory = result?.ownership_history ?? []
  const currentOwner = result?.current_owner ?? null
  const basic = result?.basic ?? null
  const cached = result?.cached === true
  const cachedAtIso = result?.cached_at ?? null
  const chargesCents = result?.charges_cents ?? null
  const notFound = result?.not_found === true

  const style = styleForMatch(match)
  const cachedAtLabel = formatCachedAt(cachedAtIso)

  const hasOwnership =
    ownershipHistory.length > 0 || currentOwner !== null
  const hasFinancingStatements = ppsrDetails.length > 0
  const hasWarnings = warnings.length > 0

  // Currency formatter — design.md §6.0 G34. Falls back gracefully on
  // unsupported locale strings.
  const currencyFormatter = (() => {
    try {
      return new Intl.NumberFormat(locale, { style: 'currency', currency: 'NZD' })
    } catch {
      return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' })
    }
  })()

  return (
    <section
      className="space-y-4"
      aria-label="PPSR search result"
      data-testid="ppsr-result-panel"
    >
      {/* 1. Money-owing banner ------------------------------------------- */}
      <div
        role="status"
        aria-live="polite"
        className={`flex items-start justify-between gap-4 rounded-lg border-2 p-4 ${style.banner}`}
      >
        <div className="flex items-start gap-3">
          <span
            className="text-2xl leading-none"
            aria-label={style.glyphLabel}
            role="img"
          >
            {style.glyph}
          </span>
          <div className="space-y-0.5">
            <p className="text-base font-semibold">{style.headline}</p>
            {matchDescription && (
              <p className="text-sm opacity-90">{matchDescription}</p>
            )}
            <p className="text-xs opacity-75">
              Match: {match ?? '—'} · Statements: {statementCount}
              {notFound && ' · Vehicle not found'}
            </p>
          </div>
        </div>

        {/* 2. Cached badge ------------------------------------------------ */}
        {cached && (
          <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center">
            <span
              className="inline-flex items-center gap-1 rounded-full border border-blue-300 bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-900 dark:border-blue-700 dark:bg-blue-900/30 dark:text-blue-100"
              data-testid="ppsr-cached-badge"
            >
              <span aria-hidden="true">ℹ</span>
              Cached{cachedAtLabel ? ` at ${cachedAtLabel}` : ''} — Re-run for fresh data
            </span>
            {onForceRefresh && (
              <button
                type="button"
                onClick={onForceRefresh}
                className="inline-flex h-9 min-h-[36px] items-center rounded-md border border-blue-300 bg-white px-3 text-xs font-medium text-blue-700 shadow-sm hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 dark:border-blue-600 dark:bg-gray-800 dark:text-blue-200 dark:hover:bg-gray-700"
              >
                Force refresh
              </button>
            )}
          </div>
        )}
      </div>

      {/* 3. Basic vehicle summary ---------------------------------------- */}
      {basic && (
        <div className={CARD} data-testid="ppsr-basic-card">
          <h3 className={SECTION_TITLE}>Vehicle</h3>
          <p className={`mt-2 ${BODY_TEXT}`}>
            {[
              readString(basic, 'year'),
              readString(basic, 'make'),
              readString(basic, 'model'),
              readString(basic, 'submodel', 'sub_model'),
            ]
              .filter(Boolean)
              .join(' ') || readString(basic, 'description') || '—'}
            {readString(basic, 'colour', 'color') && (
              <span className="ml-1 text-gray-500 dark:text-gray-400">
                · {readString(basic, 'colour', 'color')}
              </span>
            )}
          </p>
        </div>
      )}

      {/* 4. Financing statements table ----------------------------------- */}
      {hasFinancingStatements && (
        <div className={CARD} data-testid="ppsr-financing-statements">
          <h3 className={SECTION_TITLE}>Financing statements</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead>
                <tr>
                  <th scope="col" className={TABLE_HEADER}>Secured party</th>
                  <th scope="col" className={TABLE_HEADER}>Collateral description</th>
                  <th scope="col" className={TABLE_HEADER}>Registration date</th>
                  <th scope="col" className={TABLE_HEADER}>Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {ppsrDetails.map((row, idx) => (
                  <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                    <td className={TABLE_CELL}>
                      {readString(row, 'secured_party_name', 'secured_party') || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      {readString(row, 'collateral_description', 'collateral', 'description') || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      {formatRegistrationDate(
                        readString(row, 'registration_date', 'date', 'created_at'),
                      ) || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      {readString(row, 'status') || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 5. Warnings ------------------------------------------------------ */}
      {hasWarnings && (
        <div className={CARD} data-testid="ppsr-warnings">
          <h3 className={SECTION_TITLE}>Warnings</h3>
          <ul className="mt-3 space-y-2">
            {warnings.map((row, idx) => {
              const severity = readString(row, 'severity', 'level').toLowerCase()
              const message =
                readString(row, 'description', 'message', 'detail') || '—'
              const code = readString(row, 'code', 'type')
              const tone =
                severity === 'high' || severity === 'critical'
                  ? 'border-red-300 bg-red-50 text-red-900 dark:border-red-700 dark:bg-red-900/20 dark:text-red-100'
                  : severity === 'medium' || severity === 'warning'
                    ? 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-100'
                    : 'border-slate-300 bg-slate-50 text-slate-900 dark:border-slate-600 dark:bg-slate-800/40 dark:text-slate-100'
              return (
                <li
                  key={idx}
                  className={`flex items-start gap-2 rounded-md border p-3 text-sm ${tone}`}
                >
                  <span aria-hidden="true">⚠</span>
                  <div>
                    {code && (
                      <p className="text-xs font-semibold uppercase tracking-wide opacity-75">
                        {code}
                      </p>
                    )}
                    <p>{message}</p>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* 6. Ownership table ---------------------------------------------- */}
      {hasOwnership && (
        <div className={CARD} data-testid="ppsr-ownership">
          <h3 className={SECTION_TITLE}>Ownership</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead>
                <tr>
                  <th scope="col" className={TABLE_HEADER}>Owner name</th>
                  <th scope="col" className={TABLE_HEADER}>Date of ownership</th>
                  <th scope="col" className={TABLE_HEADER}>Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {currentOwner && (
                  <tr className="bg-emerald-50/40 dark:bg-emerald-900/10">
                    <td className={TABLE_CELL}>
                      {readString(currentOwner, 'name', 'owner_name', 'full_name') || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      {formatRegistrationDate(
                        readString(
                          currentOwner,
                          'date_of_ownership',
                          'from_date',
                          'since',
                        ),
                      ) || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      <span className="inline-flex items-center rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-900 dark:border-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-100">
                        Current
                      </span>
                    </td>
                  </tr>
                )}
                {ownershipHistory.map((row, idx) => (
                  <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-700/30">
                    <td className={TABLE_CELL}>
                      {readString(row, 'name', 'owner_name', 'full_name') || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      {formatRegistrationDate(
                        readString(row, 'date_of_ownership', 'from_date', 'since', 'date'),
                      ) || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      {readString(row, 'status') || 'Previous'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 7. Charges footer ----------------------------------------------- */}
      {chargesCents != null && chargesCents >= 0 && (
        <p
          className="text-xs text-gray-600 dark:text-gray-400"
          data-testid="ppsr-charges-footer"
        >
          CarJam reported a charge of{' '}
          <span className="font-medium text-gray-800 dark:text-gray-200 tabular-nums">
            {currencyFormatter.format((chargesCents ?? 0) / 100)}
          </span>{' '}
          for this search.
        </p>
      )}

      {/* 8. Actions row --------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-2 pt-2">
        {onExport && (
          <button
            type="button"
            onClick={onExport}
            className="inline-flex h-10 min-h-[44px] items-center rounded-md border border-gray-300 bg-white px-4 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-1 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            Export PDF
          </button>
        )}
        {onLink && (
          <button
            type="button"
            onClick={onLink}
            className="inline-flex h-10 min-h-[44px] items-center rounded-md border border-gray-300 bg-white px-4 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-1 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            Save to vehicle file
          </button>
        )}
        {onNew && (
          <button
            type="button"
            onClick={onNew}
            className="inline-flex h-10 min-h-[44px] items-center rounded-md bg-blue-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 dark:bg-blue-500 dark:hover:bg-blue-400"
          >
            New search
          </button>
        )}
      </div>
    </section>
  )
}

export default PpsrResultPanel
