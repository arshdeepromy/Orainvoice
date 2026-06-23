/**
 * ConflictBanner — persistent warning banner shown above the grid
 * when a bulk submit returned non-empty `conflicts`
 * (Workstream B / task B14, R13).
 *
 * Each row shows `(staff_name, date, attempted_time_range,
 * conflicting_titles)`. Click → scrolls to the cell and focuses it.
 * Dismiss → clears state.
 *
 * Logic copied verbatim from
 * frontend/src/pages/staff-schedule/components/ConflictBanner.tsx;
 * presentation remapped onto the design-system tokens.
 */

import type { BulkConflictItem } from '@/types/schedule'

export interface ConflictBannerEntry {
  /** The original conflict from the bulk response. */
  conflict: BulkConflictItem
  /** Resolved staff display name. */
  staff_name: string
  /** YYYY-MM-DD date the conflict belongs to. */
  date: string
}

export interface ConflictBannerProps {
  conflicts: ConflictBannerEntry[]
  onScrollToCell: (staffId: string, date: string) => void
  onDismiss: () => void
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

export default function ConflictBanner({
  conflicts,
  onScrollToCell,
  onDismiss,
}: ConflictBannerProps) {
  if (!conflicts || conflicts.length === 0) return null

  return (
    <div
      role="alert"
      data-testid="conflict-banner"
      className="border-b border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <p className="font-semibold">
            ⚠ {conflicts.length} overlapping shift{conflicts.length === 1 ? '' : 's'}
          </p>
          <p className="mt-0.5 text-xs text-danger/90">
            These staff are already rostered at the same time that day — adding
            another shift would double-book them. (This is an overlap check, not
            a legal hours limit.)
          </p>
          <ul className="mt-2 space-y-1">
            {conflicts.map((row, idx) => {
              const conflictTitles = (row.conflict.conflicts_with ?? [])
                .map((c) => c.title ?? c.entry_type)
                .join(', ')
              const staffId = row.conflict.attempted.staff_id ?? ''
              return (
                <li key={`${row.conflict.index}-${idx}`}>
                  <button
                    type="button"
                    onClick={() => onScrollToCell(staffId, row.date)}
                    className="rounded text-left text-xs underline-offset-2 hover:underline focus:outline-none focus:ring-2 focus:ring-danger"
                  >
                    <span className="font-medium">{row.staff_name}</span>
                    {' is already rostered '}
                    {conflictTitles && (
                      <span className="italic">{conflictTitles} </span>
                    )}
                    {'on '}
                    <span className="mono">{row.date}</span>
                    {' — the new '}
                    <span className="mono">
                      {fmtTime(row.conflict.attempted.start_time)}–
                      {fmtTime(row.conflict.attempted.end_time)}
                    </span>
                    {' shift overlaps it.'}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded p-1 text-danger hover:bg-danger/10 focus:outline-none focus:ring-2 focus:ring-danger"
          aria-label="Dismiss conflict banner"
        >
          ×
        </button>
      </div>
    </div>
  )
}
