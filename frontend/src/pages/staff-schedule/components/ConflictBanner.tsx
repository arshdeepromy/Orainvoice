/**
 * ConflictBanner — persistent warning banner shown above the grid
 * when a bulk submit returned non-empty `conflicts`
 * (Workstream B / task B14, R13).
 *
 * Each row shows `(staff_name, date, attempted_time_range,
 * conflicting_titles)`. Click → scrolls to the cell and focuses it.
 * Dismiss → clears state.
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
      className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <p className="font-semibold">
            ⚠ {conflicts.length} conflict{conflicts.length === 1 ? '' : 's'} found
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
                    className="rounded text-left text-xs underline-offset-2 hover:underline focus:outline-none focus:ring-2 focus:ring-red-500"
                  >
                    <span className="font-medium">{row.staff_name}</span>
                    {' · '}
                    <span>{row.date}</span>
                    {' · '}
                    <span>
                      {fmtTime(row.conflict.attempted.start_time)}–
                      {fmtTime(row.conflict.attempted.end_time)}
                    </span>
                    {conflictTitles && (
                      <>
                        {' · conflicts with '}
                        <span className="italic">{conflictTitles}</span>
                      </>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded p-1 text-red-600 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-500"
          aria-label="Dismiss conflict banner"
        >
          ×
        </button>
      </div>
    </div>
  )
}
