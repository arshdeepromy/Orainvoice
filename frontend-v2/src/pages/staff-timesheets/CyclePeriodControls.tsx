/**
 * Cycle-first period controls shared by TimesheetsTab and PayRunsTab.
 *
 * Replaces the old single cross-cycle <select> (which mixed every cycle's
 * periods into one dropdown and mislabelled them, e.g. a fortnight showing
 * "This week"). The new control is cycle-first:
 *
 *   1. A row of clickable cycle "boxes" — one per active cycle — each labelled
 *      with the cycle name + frequency and the cycle's current period range.
 *      The selected box is highlighted with the accent tokens.
 *   2. A period stepper scoped to the selected cycle: Prev / Next chronological
 *      buttons, a "Current period" quick-jump, and a compact dropdown listing
 *      ONLY the selected cycle's periods (no cross-cycle optgroups).
 *
 * Relative labels are period-agnostic (derived from the period vs today):
 * "Just finished" (most recent completed), "Current" (in progress), "Upcoming"
 * (future) and "Completed" (older past). The ISO week number is kept only as
 * supplementary text, never as the primary "This week" claim.
 *
 * All inputs are consumed safely (`?.` / `?? []`); a cycle/period array that is
 * missing or empty simply renders nothing rather than throwing.
 */

// ---------------------------------------------------------------------------
// Shared types (structural — both tabs have slightly different cycle/period
// shapes, so these only require the fields the controls actually read).
// ---------------------------------------------------------------------------

export interface CycleLike {
  id: string
  name: string
  frequency: string
  is_default: boolean
  active?: boolean
}

export interface PeriodLike {
  id: string
  start_date: string
  end_date: string
  status: string
  pay_cycle_id?: string | null
  pay_cycle_name?: string | null
}

export type PeriodPhase = 'just_finished' | 'current' | 'upcoming' | 'completed'

// ---------------------------------------------------------------------------
// Pure helpers (exported for unit testing / reuse)
// ---------------------------------------------------------------------------

/** Today as an ISO date string (YYYY-MM-DD) for lexical comparison. */
export const todayISO = (): string => new Date().toISOString().split('T')[0]

/** Human label for a cycle frequency code. */
export function frequencyLabel(freq: string | null | undefined): string {
  switch ((freq ?? '').toLowerCase()) {
    case 'weekly':
      return 'Weekly'
    case 'fortnightly':
      return 'Fortnightly'
    case 'monthly':
      return 'Monthly'
    default:
      return freq ? freq.charAt(0).toUpperCase() + freq.slice(1) : 'Custom'
  }
}

/** Active cycles only (treat missing `active` as active). */
export function activeCyclesOf<T extends CycleLike>(cycles: T[] | null | undefined): T[] {
  return (cycles ?? []).filter((c) => c?.active !== false)
}

/** Default cycle id: the org default (`is_default`), else the first active. */
export function defaultCycleId<T extends CycleLike>(cycles: T[] | null | undefined): string {
  const active = activeCyclesOf(cycles)
  return (active.find((c) => c?.is_default)?.id ?? active[0]?.id) ?? ''
}

/** Periods belonging to a given cycle. */
export function periodsForCycle<T extends PeriodLike>(
  periods: T[] | null | undefined,
  cycleId: string,
): T[] {
  return (periods ?? []).filter((p) => p?.pay_cycle_id === cycleId)
}

/** Chronological ascending (oldest → newest) by start_date. */
export function sortChrono<T extends PeriodLike>(periods: T[]): T[] {
  return [...periods].sort((a, b) => (a?.start_date ?? '').localeCompare(b?.start_date ?? ''))
}

/** The in-progress period (start_date <= today <= end_date), if any. */
export function currentPeriod<T extends PeriodLike>(periods: T[] | null | undefined): T | null {
  const t = todayISO()
  return (periods ?? []).find((p) => p?.start_date <= t && p?.end_date >= t) ?? null
}

/** Most recently completed period = latest end_date strictly before today. */
export function mostRecentCompleted<T extends PeriodLike>(
  periods: T[] | null | undefined,
): T | null {
  const t = todayISO()
  const completed = (periods ?? [])
    .filter((p) => (p?.end_date ?? '') < t)
    .sort((a, b) => (b?.end_date ?? '').localeCompare(a?.end_date ?? ''))
  return completed[0] ?? null
}

/**
 * Smart default period for a cycle: the most recently completed period (what
 * you pay / review). If none are completed yet, fall back to the in-progress
 * period, else the most recent period overall.
 */
export function pickDefaultPeriodId<T extends PeriodLike>(
  periods: T[] | null | undefined,
): string {
  const list = periods ?? []
  if (list.length === 0) return ''
  const completed = mostRecentCompleted(list)
  if (completed) return completed.id
  const current = currentPeriod(list)
  if (current) return current.id
  // Most recent by start_date (descending) as a last resort.
  const byRecent = [...list].sort((a, b) => (b?.start_date ?? '').localeCompare(a?.start_date ?? ''))
  return byRecent[0]?.id ?? ''
}

/** Classify a period relative to today, within its cycle's period set. */
export function periodPhase<T extends PeriodLike>(period: T, cyclePeriods: T[]): PeriodPhase {
  const t = todayISO()
  if (period.start_date <= t && period.end_date >= t) return 'current'
  if (period.start_date > t) return 'upcoming'
  const mrc = mostRecentCompleted(cyclePeriods)
  return mrc && mrc.id === period.id ? 'just_finished' : 'completed'
}

const PHASE_META: Record<PeriodPhase, { label: string; cls: string }> = {
  just_finished: { label: 'Just finished', cls: 'bg-success/10 text-success' },
  current: { label: 'Current', cls: 'bg-accent/10 text-accent' },
  upcoming: { label: 'Upcoming', cls: 'bg-warning/10 text-warning' },
  completed: { label: 'Completed', cls: 'bg-muted/20 text-muted' },
}

export function phaseMeta(phase: PeriodPhase): { label: string; cls: string } {
  return PHASE_META[phase]
}

/** ISO 8601 week number (weeks start Monday; week 1 contains the first Thursday). */
export function isoWeek(iso: string): number {
  const d = new Date(iso + 'T00:00:00')
  const target = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNr = (target.getUTCDay() + 6) % 7
  target.setUTCDate(target.getUTCDate() - dayNr + 3)
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4))
  const firstDayNr = (firstThursday.getUTCDay() + 6) % 7
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstDayNr + 3)
  return 1 + Math.round((target.getTime() - firstThursday.getTime()) / (7 * 24 * 3600 * 1000))
}

/** Compact date range, e.g. "8 – 14 Jun 2026" (collapses shared month/year). */
export function fmtRange(p: PeriodLike): string {
  const start = new Date(p.start_date + 'T00:00:00')
  const end = new Date(p.end_date + 'T00:00:00')
  const sameMonth = start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear()
  const sameYear = start.getFullYear() === end.getFullYear()
  const startLabel = sameMonth
    ? start.toLocaleDateString('en-NZ', { day: 'numeric' })
    : sameYear
      ? start.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' })
      : start.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  const endLabel = end.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' })
  return `${startLabel} – ${endLabel}`
}

/** Dropdown option label: phase + range, with the ISO week as supplementary. */
export function fmtPeriodOption(p: PeriodLike, cyclePeriods: PeriodLike[]): string {
  const meta = phaseMeta(periodPhase(p, cyclePeriods))
  const statusTag = p.status && p.status !== 'open' ? ` (${p.status})` : ''
  return `${meta.label} · ${fmtRange(p)} · Wk ${isoWeek(p.start_date)}${statusTag}`
}

// ---------------------------------------------------------------------------
// Cycle boxes — one clickable chip per active cycle.
// ---------------------------------------------------------------------------

interface CycleBoxesProps {
  cycles: CycleLike[]
  periods: PeriodLike[]
  selectedCycleId: string
  onSelect: (cycleId: string) => void
  /** Optional per-cycle count (e.g. timesheets) rendered under the range. */
  countForCycle?: (cycleId: string) => number | null
  countNoun?: string
}

export function CycleBoxes({
  cycles,
  periods,
  selectedCycleId,
  onSelect,
  countForCycle,
  countNoun = 'timesheets',
}: CycleBoxesProps) {
  const active = activeCyclesOf(cycles)
  if (active.length === 0) return null
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Pay cycle">
      {active.map((cycle) => {
        const cyclePeriods = periodsForCycle(periods, cycle.id)
        const showcase = currentPeriod(cyclePeriods) ?? mostRecentCompleted(cyclePeriods) ?? cyclePeriods[0] ?? null
        const selected = cycle.id === selectedCycleId
        const count = countForCycle?.(cycle.id) ?? null
        return (
          <button
            key={cycle.id}
            type="button"
            onClick={() => onSelect(cycle.id)}
            aria-pressed={selected}
            className={`flex min-w-[150px] flex-col items-start gap-0.5 rounded-lg border px-3 py-2 text-left transition-colors ${
              selected
                ? 'border-accent bg-accent/5 ring-1 ring-accent/30'
                : 'border-border bg-card hover:bg-canvas'
            }`}
          >
            <span className="flex items-center gap-1.5">
              <span className={`text-sm font-semibold ${selected ? 'text-accent' : 'text-text'}`}>
                {cycle.name}
              </span>
              {cycle.is_default && (
                <span className="rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                  Default
                </span>
              )}
            </span>
            <span className="text-xs text-muted">{frequencyLabel(cycle.frequency)}</span>
            {showcase && <span className="text-xs text-muted">{fmtRange(showcase)}</span>}
            {count != null && (
              <span className="text-[11px] text-muted">
                {count} {countNoun}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Period stepper — Prev / Next + compact dropdown + "Current period" jump,
// scoped to a single cycle's periods.
// ---------------------------------------------------------------------------

interface PeriodStepperProps {
  cyclePeriods: PeriodLike[]
  selectedPeriod: string
  onChange: (periodId: string) => void
}

export function PeriodStepper({ cyclePeriods, selectedPeriod, onChange }: PeriodStepperProps) {
  if (cyclePeriods.length === 0) {
    return <span className="text-xs text-muted">No periods for this cycle yet</span>
  }
  // Chronological order drives Prev/Next; the dropdown shows newest first.
  const chrono = sortChrono(cyclePeriods)
  const descending = [...chrono].reverse()
  const idx = chrono.findIndex((p) => p.id === selectedPeriod)
  const selected = idx >= 0 ? chrono[idx] : null
  const current = currentPeriod(cyclePeriods)

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => idx > 0 && onChange(chrono[idx - 1].id)}
          disabled={idx <= 0}
          aria-label="Previous period"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card text-text hover:bg-canvas transition-colors disabled:opacity-40"
        >
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
        <select
          aria-label="Pay period"
          value={selectedPeriod}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 rounded-lg border border-border bg-canvas px-3 text-sm text-text focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        >
          {descending.map((p) => (
            <option key={p.id} value={p.id}>
              {fmtPeriodOption(p, cyclePeriods)}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => idx >= 0 && idx < chrono.length - 1 && onChange(chrono[idx + 1].id)}
          disabled={idx < 0 || idx >= chrono.length - 1}
          aria-label="Next period"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card text-text hover:bg-canvas transition-colors disabled:opacity-40"
        >
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </button>
      </div>

      {current && current.id !== selectedPeriod && (
        <button
          type="button"
          onClick={() => onChange(current.id)}
          className="inline-flex h-9 items-center rounded-lg border border-accent/40 bg-accent/5 px-3 text-xs font-medium text-accent hover:bg-accent/10 transition-colors"
        >
          Current period
        </button>
      )}

      {selected && (() => {
        const meta = phaseMeta(periodPhase(selected, cyclePeriods))
        return (
          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.cls}`}>
            {meta.label}
          </span>
        )
      })()}
    </div>
  )
}
