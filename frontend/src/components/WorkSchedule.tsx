/**
 * Visual work schedule editor — toggle days on/off and set start/end times.
 * Data format matches the availability_schedule JSONB:
 *   { "monday": { "start": "09:00", "end": "17:00" }, ... }
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
      <label className="block text-sm font-medium text-gray-700 mb-2">Work Days</label>
      <div className="space-y-1.5">
        {DAYS.map(({ key, label }) => {
          const active = !!schedule[key]
          return (
            <div key={key} className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => toggleDay(key)}
                disabled={readOnly}
                className={`w-10 h-8 rounded text-xs font-semibold transition-colors ${
                  active
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                } ${readOnly ? 'cursor-default' : 'cursor-pointer'}`}
              >
                {label}
              </button>
              {active ? (
                <div className="flex items-center gap-1.5 text-sm">
                  {readOnly ? (
                    <span className="text-gray-700">{schedule[key].start} - {schedule[key].end}</span>
                  ) : (
                    <>
                      <input
                        type="time"
                        value={schedule[key].start}
                        onChange={e => updateTime(key, 'start', e.target.value)}
                        className="rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                      <span className="text-gray-400">to</span>
                      <input
                        type="time"
                        value={schedule[key].end}
                        onChange={e => updateTime(key, 'end', e.target.value)}
                        className="rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </>
                  )}
                </div>
              ) : (
                <span className="text-xs text-gray-400">{readOnly ? 'Off' : 'Off - click to enable'}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
