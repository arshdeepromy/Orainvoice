import { MobileInput } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Props                                                              */
/* ------------------------------------------------------------------ */

export interface DateRange {
  start: string
  end: string
}

export interface DateRangePickerProps {
  /** Current date range value */
  value: DateRange
  /** Called when either date changes */
  onChange: (range: DateRange) => void
  /** Label for the component */
  label?: string
  /** Additional CSS classes */
  className?: string
}

/**
 * Date range selection component for reports and calendar filters.
 * Two date inputs (start and end) with validation that end >= start.
 *
 * Requirements: 28.4
 */
export function DateRangePicker({
  value,
  onChange,
  label,
  className = '',
}: DateRangePickerProps) {
  const handleStartChange = (newStart: string) => {
    const updated: DateRange = { ...value, start: newStart }
    // If end is before new start, move end to match start
    if (updated.end && updated.start && updated.end < updated.start) {
      updated.end = updated.start
    }
    onChange(updated)
  }

  const handleEndChange = (newEnd: string) => {
    const updated: DateRange = { ...value, end: newEnd }
    onChange(updated)
  }

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {label && (
        <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {label}
        </p>
      )}
      <div className="flex gap-3">
        <MobileInput
          label="From"
          type="date"
          value={value.start}
          onChange={(e) => handleStartChange(e.target.value)}
          className="flex-1"
        />
        <MobileInput
          label="To"
          type="date"
          value={value.end}
          onChange={(e) => handleEndChange(e.target.value)}
          min={value.start || undefined}
          className="flex-1"
        />
      </div>
    </div>
  )
}
