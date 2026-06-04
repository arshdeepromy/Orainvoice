/**
 * Visual work schedule editor — toggle days on/off and set start/end times.
 * Data format matches the availability_schedule JSONB:
 *   { "monday": { "start": "09:00", "end": "17:00" }, ... }
 *
 * Logic copied verbatim from frontend/src/components/WorkSchedule.tsx; the
 * presentation is remapped onto the design-system tokens (FR-2): the active
 * day toggle uses the accent token, inactive uses the canvas surface, and the
 * time inputs use the standard token-styled control.
 */

import { useCallback } from 'react'

export type DaySchedule = { start: string; end: string }
export type WeekSchedule = Record<string, DaySchedule>

const DAYS = [
  { key: 'monday', label: 'Mon' },
  { key: 'tuesday', label: 'Tue' },
  { key: 'wednesday', label: 'Wed' },
  { key: 'thursday', label: 'Thu' },
  { key: 'friday', label: 'Fri' },
  { key: 'saturday', label: 'Sat' },
  { key: 'sunday', label: 'Sun' },
]

const DEFAULT_START = '09:00'
const DEFAULT_END = '17:00'

interface Props {
  schedule: WeekSchedule
  onChange: (schedule: WeekSchedule) => void
  readOnly?: boolean
}

export default function WorkSchedule({ schedule, onChange, readOnly }: Props) {
  const toggleDay = useCallback((day: string) => {
    if (readOnly) return
    const next = { ...schedule }
    if (next[day]) {
      delete next[day]
    } else {
      next[day] = { start: DEFAULT_START, end: DEFAULT_END }
    }
    onChange(next)
  }, [schedule, onChange, readOnly])

  const updateTime = useCallback((day: string, field: 'start' | 'end', value: string) => {
    if (readOnly) return
    onChange({
      ...schedule,
      [day]: { ...schedule[day], [field]: value },
    })
  }, [schedule, onChange, readOnly])

  return (
    <div className="space-y-2">
      <label className="mb-2 block text-[12.5px] font-medium text-text">Work Days</label>
      <div className="space-y-1.5">
        {DAYS.map(({ key, label }) => {
          const active = !!schedule[key]
          return (
            <div key={key} className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => toggleDay(key)}
                disabled={readOnly}
                className={`h-8 w-10 rounded-ctl text-xs font-semibold transition-colors ${
                  active
                    ? 'bg-accent text-white hover:bg-accent-press'
                    : 'bg-canvas text-muted-2 hover:bg-border'
                } ${readOnly ? 'cursor-default' : 'cursor-pointer'}`}
              >
                {label}
              </button>
              {active ? (
                <div className="flex items-center gap-1.5 text-sm">
                  {readOnly ? (
                    <span className="mono text-text">{schedule[key].start} - {schedule[key].end}</span>
                  ) : (
                    <>
                      <input
                        type="time"
                        value={schedule[key].start}
                        onChange={e => updateTime(key, 'start', e.target.value)}
                        className="rounded-ctl border border-border bg-card px-2 py-1 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                      />
                      <span className="text-muted-2">to</span>
                      <input
                        type="time"
                        value={schedule[key].end}
                        onChange={e => updateTime(key, 'end', e.target.value)}
                        className="rounded-ctl border border-border bg-card px-2 py-1 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                      />
                    </>
                  )}
                </div>
              ) : (
                <span className="text-xs text-muted-2">{readOnly ? 'Off' : 'Off - click to enable'}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
