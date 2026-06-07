/**
 * DayPips — the compact seven-square work-days indicator for the Staff list
 * Work days cell (R3). Renders one labelled square per weekday, ordered
 * Monday through Sunday. A pip is in the ACTIVE style when the staff member's
 * `availability_schedule` contains a (truthy) entry for that day, and the
 * INACTIVE style otherwise. When the schedule is null/undefined/empty, all
 * seven pips are inactive (R3.4).
 *
 * Presentation mirrors the `Staff.html` prototype `.day-pip` look: a small
 * rounded square with a mono single-letter label; the active pip uses the
 * accent-soft background + accent text + transparent border, the inactive pip
 * uses the canvas background + muted-2 text + border tokens (so both adapt to
 * dark mode via the design-system CSS variables, R14.2).
 *
 * Each pip exposes stable identifying attributes for tests:
 *   - `data-day`    — the lowercase day key (`monday` … `sunday`)
 *   - `data-active` — `"true"` | `"false"`
 *   - `aria-label`  — the full day name
 *   - `title`       — the full day name (hover tooltip, matches prototype)
 *
 * _Requirements: 3.1, 3.2, 3.3, 3.4, 14.2_
 */

/** Day key + full name + single-letter label, ordered Monday → Sunday. */
const DAYS: ReadonlyArray<{ key: string; name: string; initial: string }> = [
  { key: 'monday', name: 'Monday', initial: 'M' },
  { key: 'tuesday', name: 'Tuesday', initial: 'T' },
  { key: 'wednesday', name: 'Wednesday', initial: 'W' },
  { key: 'thursday', name: 'Thursday', initial: 'T' },
  { key: 'friday', name: 'Friday', initial: 'F' },
  { key: 'saturday', name: 'Saturday', initial: 'S' },
  { key: 'sunday', name: 'Sunday', initial: 'S' },
]

interface DayPipsProps {
  /** The staff member's `availability_schedule`; a day is active when present. */
  schedule: Record<string, { start: string; end: string }> | null | undefined
}

export default function DayPips({ schedule }: DayPipsProps) {
  return (
    <div className="flex gap-[3px]">
      {DAYS.map((day) => {
        const isActive = Boolean(schedule?.[day.key])
        return (
          <span
            key={day.key}
            data-day={day.key}
            data-active={isActive ? 'true' : 'false'}
            aria-label={day.name}
            title={day.name}
            className={
              'mono grid h-[22px] w-[22px] place-items-center rounded-[6px] border text-[10px] font-semibold ' +
              (isActive
                ? 'border-transparent bg-accent-soft text-accent'
                : 'border-border bg-canvas text-muted-2')
            }
          >
            {day.initial}
          </span>
        )
      })}
    </div>
  )
}
