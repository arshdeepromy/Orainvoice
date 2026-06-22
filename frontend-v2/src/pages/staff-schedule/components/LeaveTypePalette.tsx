/**
 * LeaveTypePalette — pick a leave type to "paint" leave onto the roster
 * grid, mirroring the shift TemplatePalette.
 *
 * Leave types are the single source of truth configured under
 * Settings → People → Leave Types and fetched via `GET /api/v2/leave/types`
 * (active only). Selecting a type enters "leave paint" mode in the page:
 * the type sticks to the cursor and clicking a staff/day cell opens a
 * confirmation to mark that staff on leave (and publish their shift to
 * Open Shifts).
 *
 * Leave types carry no colour in the DB, so a stable colour is derived
 * client-side from the type id/code.
 */

import { useEffect, useState } from 'react'
import { listLeaveTypes, type LeaveType } from '@/api/leave'

export interface LeaveTypePaletteProps {
  selectedLeaveType: LeaveType | null
  onSelect: (leaveType: LeaveType | null) => void
  /** When true, palette controls are disabled (in-flight submit). */
  disabled?: boolean
}

/* A small fixed palette; a leave type maps to one entry by a stable hash. */
const SWATCHES = [
  'bg-rose-400',
  'bg-amber-400',
  'bg-emerald-400',
  'bg-sky-400',
  'bg-violet-400',
  'bg-teal-400',
  'bg-orange-400',
  'bg-pink-400',
]

export function leaveSwatch(key: string): string {
  let h = 0
  for (let i = 0; i < key.length; i += 1) {
    h = (h * 31 + key.charCodeAt(i)) >>> 0
  }
  return SWATCHES[h % SWATCHES.length]
}

export default function LeaveTypePalette({
  selectedLeaveType,
  onSelect,
  disabled,
}: LeaveTypePaletteProps) {
  const [types, setTypes] = useState<LeaveType[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setIsLoading(true)
      try {
        // Active leave types only — the single source of truth from Settings.
        const res = await listLeaveTypes({ limit: 200 }, controller.signal)
        const list = (res.items ?? [])
          .slice()
          .sort(
            (a, b) =>
              (a.display_order ?? 0) - (b.display_order ?? 0) ||
              (a.name ?? '').localeCompare(b.name ?? ''),
          )
        setTypes(list)
        setError(null)
      } catch (err: unknown) {
        if (!(err as { name?: string })?.name?.includes('Cancel')) {
          setError('Failed to load leave types')
        }
      } finally {
        setIsLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [])

  return (
    <div className="rounded-card border border-border bg-card p-3" data-no-print>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
          Leave Types
        </h3>
        {selectedLeaveType && (
          <button
            type="button"
            onClick={() => onSelect(null)}
            disabled={disabled}
            className="text-[11px] font-medium text-accent hover:underline disabled:opacity-50"
          >
            Clear
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-8 animate-pulse rounded bg-muted/10" />
          ))}
        </div>
      ) : error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : types.length === 0 ? (
        <p className="text-xs text-muted">
          No leave types configured. Add them under Settings → Leave Types.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {types.map((lt) => {
            const isSelected = selectedLeaveType?.id === lt.id
            return (
              <button
                key={lt.id}
                type="button"
                disabled={disabled}
                onClick={() => onSelect(isSelected ? null : lt)}
                className={`flex items-center gap-2 rounded-ctl border px-2 py-1.5 text-left text-[12.5px] transition-colors disabled:opacity-50 ${
                  isSelected
                    ? 'border-accent bg-accent-soft text-text'
                    : 'border-border bg-canvas text-text hover:bg-muted/5'
                }`}
                title={lt.is_paid ? 'Paid leave' : 'Unpaid leave'}
              >
                <span
                  className={`h-3 w-3 shrink-0 rounded-full ${leaveSwatch(lt.code || lt.id)}`}
                  aria-hidden="true"
                />
                <span className="truncate font-medium">{lt.name}</span>
                {!lt.is_paid && (
                  <span className="ml-auto rounded bg-muted/10 px-1 text-[9px] font-semibold uppercase text-muted">
                    Unpaid
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}

      {selectedLeaveType && (
        <p className="mt-2 text-[11px] text-muted">
          Click a staff member's day to mark{' '}
          <span className="font-medium text-text">{selectedLeaveType.name}</span>.
        </p>
      )}
    </div>
  )
}
