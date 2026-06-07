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
// (design-token palette per design.md §6.0)
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
    banner: 'bg-danger-soft text-danger border-danger/40',
  },
  PY: {
    glyph: '🔴',
    glyphLabel: 'Red — possible match, money owing',
    headline: 'Money Owing (possible match)',
    banner: 'bg-warn-soft text-warn border-warn/40',
  },
  M: {
    glyph: '🟠',
    glyphLabel: 'Amber — matched, no money owing',
    headline: 'Matched — no money owing',
    banner: 'bg-warn-soft text-warn border-warn/40',
  },
  PM: {
    glyph: '🟠',
    glyphLabel: 'Amber — possible match, no money owing',
    headline: 'Possible match — no money owing',
    banner: 'bg-warn-soft text-warn border-warn/40',
  },
  U: {
    glyph: '⚪',
    glyphLabel: 'Slate — unknown',
    headline: 'Unknown',
    banner: 'bg-canvas text-muted border-border-strong',
  },
  N: {
    glyph: '🟢',
    glyphLabel: 'Green — no money owing',
    headline: 'No money owing',
    banner: 'bg-ok-soft text-ok border-ok/40',
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

const OWNER_CHECK_TYPE_LABELS: Record<string, string> = {
  person_names: 'Person (name)',
  person_dl: "Driver's licence",
  company: 'Company',
}

function ownerCheckTypeLabel(type: string | null | undefined): string {
  if (!type) return 'Ownership check'
  return OWNER_CHECK_TYPE_LABELS[type] ?? 'Ownership check'
}

/**
 * Project the submitted owner-check inputs into ordered `{label, value}`
 * rows for display. Only the fields relevant to `type` are surfaced;
 * unknown / missing inputs are skipped.
 */
function buildOwnerCheckRows(
  type: string | null | undefined,
  submitted: Record<string, unknown> | null | undefined,
): Array<{ label: string; value: string }> {
  if (!type || !submitted || typeof submitted !== 'object') return []
  const get = (k: string): string => {
    const v = (submitted as Record<string, unknown>)[k]
    return typeof v === 'string' && v.trim().length > 0 ? v.trim() : ''
  }
  const rows: Array<{ label: string; value: string }> = []
  if (type === 'person_names') {
    const ln = get('owner_last_name')
    const fn = get('owner_first_name')
    const dob = get('owner_dob')
    if (ln) rows.push({ label: 'Last name', value: ln })
    if (fn) rows.push({ label: 'First name', value: fn })
    if (dob) rows.push({ label: 'Date of birth', value: dob })
  } else if (type === 'person_dl') {
    const dl = get('owner_driver_licence')
    if (dl) rows.push({ label: 'Driver licence number', value: dl })
  } else if (type === 'company') {
    const cn = get('owner_company_name')
    if (cn) rows.push({ label: 'Company name', value: cn })
  }
  return rows
}

// ===========================================================================
// Card / panel base classes (design.md §6.0)
// ===========================================================================

const CARD =
  'rounded-card border border-border bg-card p-6 shadow-card'
const SECTION_TITLE =
  'text-base font-medium text-text'
const BODY_TEXT = 'text-sm text-muted'
const TABLE_HEADER =
  'mono border-b border-border px-4 py-3 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2'
const TABLE_CELL = 'px-4 py-2 text-sm text-text'

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
  const notFound = result?.not_found === true

  // Ownership check (CarJam owner_check). owner_check_match is null/undefined
  // when no ownership check was run for this search.
  const ownerCheckType = result?.owner_check_type ?? null
  const ownerCheckMatch = result?.owner_check_match ?? null
  const ownerCheckRef = result?.owner_check_ref ?? null
  const ownerCheckSubmitted = result?.owner_check_submitted ?? null
  const hasOwnerCheck = ownerCheckType != null && ownerCheckMatch != null
  const submittedRows = buildOwnerCheckRows(ownerCheckType, ownerCheckSubmitted)

  const style = styleForMatch(match)
  const cachedAtLabel = formatCachedAt(cachedAtIso)

  const hasOwnership =
    (ownershipHistory ?? []).length > 0 || currentOwner !== null
  const hasFinancingStatements = ppsrDetails.length > 0
  const hasWarnings = warnings.length > 0

  // A PPSR money-owing check actually ran iff the row has a match code
  // (Y/PY/M/PM/U/N), any financing statements, any warnings, or is a
  // confirmed not_found result. Owner-check-only searches have none of
  // these — for those we render a "No PPSR performed" notice instead
  // of a misleading "Unknown" traffic-light banner.
  const ppsrCheckRan =
    !!match || hasFinancingStatements || hasWarnings || notFound

  return (
    <section
      className="space-y-4"
      aria-label="PPSR search result"
      data-testid="ppsr-result-panel"
    >
      {/* 1. Money-owing banner — only when a PPSR check actually ran. */}
      {ppsrCheckRan ? (
      <div
        role="status"
        aria-live="polite"
        className={`flex items-start justify-between gap-4 rounded-card border-2 p-4 ${style.banner}`}
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
              className="inline-flex items-center gap-1 rounded-full border border-accent/40 bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent"
              data-testid="ppsr-cached-badge"
            >
              <span aria-hidden="true">ℹ</span>
              Cached{cachedAtLabel ? ` at ${cachedAtLabel}` : ''} — Re-run for fresh data
            </span>
            {onForceRefresh && (
              <button
                type="button"
                onClick={onForceRefresh}
                className="inline-flex h-9 min-h-[36px] items-center rounded-ctl border border-accent/40 bg-card px-3 text-xs font-medium text-accent shadow-card hover:bg-accent-soft focus:outline-none focus:ring-2 focus:ring-accent"
              >
                Force refresh
              </button>
            )}
          </div>
        )}
      </div>
      ) : (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between gap-3 rounded-card border border-border bg-canvas px-4 py-2.5 text-sm text-muted"
          data-testid="ppsr-no-ppsr-performed"
        >
          <span className="inline-flex items-center gap-2">
            <span aria-hidden="true">ℹ</span>
            <span>No PPSR money-owing check performed for this search.</span>
          </span>
          {cached && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-accent/40 bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent"
              data-testid="ppsr-cached-badge"
            >
              <span aria-hidden="true">ℹ</span>
              Cached{cachedAtLabel ? ` at ${cachedAtLabel}` : ''}
            </span>
          )}
        </div>
      )}

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
              <span className="ml-1 text-muted-2">
                · {readString(basic, 'colour', 'color')}
              </span>
            )}
          </p>
        </div>
      )}

      {/* 3b. Ownership check result -------------------------------------- */}
      {hasOwnerCheck && (
        <div className={CARD} data-testid="ppsr-owner-check">
          <div className="flex items-center justify-between gap-3">
            <h3 className={SECTION_TITLE}>Ownership Verification</h3>
            <span
              className="mono inline-flex items-center rounded-full border border-border bg-canvas px-2.5 py-0.5 text-xs font-medium text-muted"
              aria-label={`Vehicle plate ${result?.rego ?? ''}`}
            >
              {result?.rego ?? '—'}
            </span>
          </div>

          {/* Pass/fail banner — primary visual outcome */}
          <div
            className={`mt-3 flex items-start gap-3 rounded-card border-2 p-4 ${
              ownerCheckMatch
                ? 'bg-ok-soft text-ok border-ok/40'
                : 'bg-danger-soft text-danger border-danger/40'
            }`}
            role="status"
            aria-live="polite"
          >
            <span className="text-2xl leading-none" aria-hidden="true">
              {ownerCheckMatch ? '✅' : '❌'}
            </span>
            <div className="space-y-0.5">
              <p className="text-base font-semibold">
                {ownerCheckMatch ? 'Ownership confirmed' : 'Ownership not confirmed'}
              </p>
              <p className="text-sm opacity-90">
                {ownerCheckMatch
                  ? 'The supplied details match the current registered owner.'
                  : 'The supplied details do not match the current registered owner.'}
              </p>
            </div>
          </div>

          {/* Method + submitted details — what we asked CarJam to verify */}
          <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            <div className="flex flex-col gap-0.5 sm:col-span-2">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-2">
                Verification method
              </dt>
              <dd className="text-sm text-text">
                {ownerCheckTypeLabel(ownerCheckType)}
              </dd>
            </div>
            {submittedRows.map((row) => (
              <div key={row.label} className="flex flex-col gap-0.5">
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-2">
                  {row.label}
                </dt>
                <dd className="text-sm text-text break-words">{row.value}</dd>
              </div>
            ))}
            {ownerCheckRef && (
              <div className="flex flex-col gap-0.5 sm:col-span-2">
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-2">
                  CarJam reference
                </dt>
                <dd className="mono text-sm text-text">{ownerCheckRef}</dd>
              </div>
            )}
          </dl>

          {/* Provenance — cite CarJam → NZTA Motor Vehicle Register */}
          <p className="mt-4 border-t border-border pt-3 text-xs italic text-muted-2">
            Verified via the CarJam API, accessing the official New Zealand
            Motor Vehicle Register administered by Waka Kotahi NZ Transport
            Agency (NZTA). Match reflects whether the supplied details
            correspond to the current registered owner at the time of search.
          </p>
        </div>
      )}

      {/* 4. Financing statements table ----------------------------------- */}
      {hasFinancingStatements && (
        <div className={CARD} data-testid="ppsr-financing-statements">
          <h3 className={SECTION_TITLE}>Financing statements</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr>
                  <th scope="col" className={TABLE_HEADER}>Secured party</th>
                  <th scope="col" className={TABLE_HEADER}>Collateral description</th>
                  <th scope="col" className={TABLE_HEADER}>Registration date</th>
                  <th scope="col" className={TABLE_HEADER}>Status</th>
                </tr>
              </thead>
              <tbody>
                {ppsrDetails.map((row, idx) => (
                  <tr key={idx} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className={TABLE_CELL}>
                      {readString(row, 'secured_party_name', 'secured_party') || '—'}
                    </td>
                    <td className={TABLE_CELL}>
                      {readString(row, 'collateral_description', 'collateral', 'description') || '—'}
                    </td>
                    <td className={`mono ${TABLE_CELL}`}>
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
                  ? 'border-danger/40 bg-danger-soft text-danger'
                  : severity === 'medium' || severity === 'warning'
                    ? 'border-warn/40 bg-warn-soft text-warn'
                    : 'border-border-strong bg-canvas text-muted'
              return (
                <li
                  key={idx}
                  className={`flex items-start gap-2 rounded-ctl border p-3 text-sm ${tone}`}
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
            <table className="min-w-full">
              <thead>
                <tr>
                  <th scope="col" className={TABLE_HEADER}>Owner name</th>
                  <th scope="col" className={TABLE_HEADER}>Date of ownership</th>
                  <th scope="col" className={TABLE_HEADER}>Status</th>
                </tr>
              </thead>
              <tbody>
                {currentOwner && (
                  <tr className="border-b border-border bg-ok-soft/40">
                    <td className={TABLE_CELL}>
                      {readString(currentOwner, 'name', 'owner_name', 'full_name') || '—'}
                    </td>
                    <td className={`mono ${TABLE_CELL}`}>
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
                      <span className="inline-flex items-center rounded-full border border-ok/40 bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok">
                        Current
                      </span>
                    </td>
                  </tr>
                )}
                {(ownershipHistory ?? []).map((row, idx) => (
                  <tr key={idx} className="border-b border-border last:border-b-0 hover:bg-canvas">
                    <td className={TABLE_CELL}>
                      {readString(row, 'name', 'owner_name', 'full_name') || '—'}
                    </td>
                    <td className={`mono ${TABLE_CELL}`}>
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

      {/* 8. Actions row --------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-2 pt-2">
        {onExport && (
          <button
            type="button"
            onClick={onExport}
            className="inline-flex h-10 min-h-[44px] items-center rounded-ctl border border-border bg-card px-4 text-sm font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent"
          >
            Export PDF
          </button>
        )}
        {onLink && (
          <button
            type="button"
            onClick={onLink}
            className="inline-flex h-10 min-h-[44px] items-center rounded-ctl border border-border bg-card px-4 text-sm font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent"
          >
            Save to vehicle file
          </button>
        )}
        {onNew && (
          <button
            type="button"
            onClick={onNew}
            className="inline-flex h-10 min-h-[44px] items-center rounded-ctl bg-accent px-4 text-sm font-medium text-white shadow-card hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent"
          >
            New search
          </button>
        )}
      </div>
    </section>
  )
}

export default PpsrResultPanel
