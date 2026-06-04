import { Input, Select } from '@/components/ui'

export interface DateRange {
  from: string
  to: string
}

export type Preset = 'today' | 'week' | 'month' | 'quarter' | 'year' | 'custom'

interface DateRangeFilterProps {
  value: DateRange
  onChange: (range: DateRange) => void
}

/**
 * Format a Date as a local YYYY-MM-DD string.
 * Avoids `toISOString()` which shifts to UTC and can flip the day in non-UTC
 * timezones (e.g. NZ/UTC+12), which would break the `start <= end` invariant
 * for presets near month boundaries.
 */
function ymd(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${dd}`
}

/**
 * Compute the date range for a given preset.
 *
 * Guarantees `start <= end` for every non-custom preset (Requirement 12.4).
 * `custom` returns empty strings — used as a sentinel that does not match any
 * other preset, so `presetFromValue` will resolve it back to `'custom'`.
 */
export function presetRange(preset: Preset): DateRange {
  const now = new Date()
  const todayStr = ymd(now)

  switch (preset) {
    case 'today':
      return { from: todayStr, to: todayStr }
    case 'week': {
      const d = new Date(now)
      d.setDate(d.getDate() - 7)
      return { from: ymd(d), to: todayStr }
    }
    case 'month': {
      // First day of last month → last day of last month
      const fromD = new Date(now.getFullYear(), now.getMonth() - 1, 1)
      const toD = new Date(now.getFullYear(), now.getMonth(), 0)
      return { from: ymd(fromD), to: ymd(toD) }
    }
    case 'quarter': {
      const currentQ = Math.floor(now.getMonth() / 3)
      const fromD = new Date(now.getFullYear(), (currentQ - 1) * 3, 1)
      const toD = new Date(now.getFullYear(), currentQ * 3, 0)
      return { from: ymd(fromD), to: ymd(toD) }
    }
    case 'year': {
      const prevYear = now.getFullYear() - 1
      return { from: `${prevYear}-01-01`, to: `${prevYear}-12-31` }
    }
    case 'custom':
      return { from: '', to: '' }
  }
}

const NON_CUSTOM_PRESETS: Preset[] = ['today', 'week', 'month', 'quarter', 'year']

/**
 * Derive the preset that matches a given value, or `'custom'` if no preset
 * matches. Satisfies the round-trip property: for every non-custom preset
 * `p`, `presetFromValue(presetRange(p)) === p` (Requirement 12.5).
 */
export function presetFromValue(value: DateRange): Preset {
  for (const p of NON_CUSTOM_PRESETS) {
    const r = presetRange(p)
    if (r.from === value.from && r.to === value.to) return p
  }
  return 'custom'
}

/**
 * Reusable date range filter with preset options (today, week, month, quarter,
 * year, custom). Fully controlled: the displayed preset is derived from the
 * `value` prop so the dropdown label always matches the queried range.
 *
 * Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 21.1, 45.2
 */
export default function DateRangeFilter({ value, onChange }: DateRangeFilterProps) {
  const preset = presetFromValue(value)

  const handlePreset = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const p = e.target.value as Preset
    // Picking a preset (including 'custom') always pushes a new value up so
    // the derived `preset` reflects the user's choice. For 'custom' this
    // clears the inputs to {from: '', to: ''} which never matches another
    // preset, so the custom inputs become visible.
    onChange(presetRange(p))
  }

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <div className="w-40">
        <Select
          label="Period"
          value={preset}
          onChange={handlePreset}
          options={[
            { value: 'today', label: 'Today' },
            { value: 'week', label: 'Last 7 days' },
            { value: 'month', label: 'Last month' },
            { value: 'quarter', label: 'Last quarter' },
            { value: 'year', label: 'Last year' },
            { value: 'custom', label: 'Custom range' },
          ]}
        />
      </div>
      {preset === 'custom' && (
        <>
          <div className="w-40">
            <Input
              label="From"
              type="date"
              value={value.from}
              onChange={(e) => onChange({ ...value, from: e.target.value })}
            />
          </div>
          <div className="w-40">
            <Input
              label="To"
              type="date"
              value={value.to}
              onChange={(e) => onChange({ ...value, to: e.target.value })}
            />
          </div>
        </>
      )}
    </div>
  )
}
