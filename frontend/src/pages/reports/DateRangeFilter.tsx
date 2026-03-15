import { useState } from 'react'
import { Input, Select } from '../../components/ui'

export interface DateRange {
  from: string
  to: string
}

type Preset = 'today' | 'week' | 'month' | 'quarter' | 'year' | 'custom'

interface DateRangeFilterProps {
  value: DateRange
  onChange: (range: DateRange) => void
}

function presetRange(preset: Preset): DateRange {
  const now = new Date()
  let to = now.toISOString().slice(0, 10)
  let from = to

  switch (preset) {
    case 'today':
      break
    case 'week': {
      const d = new Date(now)
      d.setDate(d.getDate() - 7)
      from = d.toISOString().slice(0, 10)
      break
    }
    case 'month': {
      const d = new Date(now.getFullYear(), now.getMonth() - 1, 1)
      from = d.toISOString().slice(0, 10)
      const lastDay = new Date(now.getFullYear(), now.getMonth(), 0)
      to = lastDay.toISOString().slice(0, 10)
      break
    }
    case 'quarter': {
      const currentQ = Math.floor(now.getMonth() / 3)
      const prevQStart = new Date(now.getFullYear(), (currentQ - 1) * 3, 1)
      const prevQEnd = new Date(now.getFullYear(), currentQ * 3, 0)
      from = prevQStart.toISOString().slice(0, 10)
      to = prevQEnd.toISOString().slice(0, 10)
      break
    }
    case 'year': {
      const prevYear = now.getFullYear() - 1
      from = `${prevYear}-01-01`
      to = `${prevYear}-12-31`
      break
    }
    case 'custom':
      return { from: '', to: '' }
  }
  return { from, to }
}

/**
 * Reusable date range filter with preset options (today, week, month, quarter, year, custom).
 * Requirements: 45.2
 */
export default function DateRangeFilter({ value, onChange }: DateRangeFilterProps) {
  const [preset, setPreset] = useState<Preset>('month')

  const handlePreset = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const p = e.target.value as Preset
    setPreset(p)
    if (p !== 'custom') {
      onChange(presetRange(p))
    }
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
