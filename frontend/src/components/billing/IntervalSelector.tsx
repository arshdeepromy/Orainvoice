import { useCallback } from 'react'
import type { IntervalPricing } from '../../pages/auth/signup-types'

/* ── Types ── */

export interface IntervalSelectorProps {
  intervals: IntervalPricing[]
  selected: string
  onChange: (interval: string) => void
  recommendedInterval?: string
}

/* ── Constants ── */

const INTERVAL_LABELS: Record<string, string> = {
  weekly: 'Weekly',
  fortnightly: 'Fortnightly',
  monthly: 'Monthly',
  annual: 'Annual',
}

const INTERVAL_ORDER = ['weekly', 'fortnightly', 'monthly', 'annual']

/* ── Component ── */

export function IntervalSelector({
  intervals,
  selected,
  onChange,
  recommendedInterval = 'monthly',
}: IntervalSelectorProps) {
  const safeIntervals = intervals ?? []

  // Sort intervals in canonical order, only show enabled ones
  const sortedIntervals = INTERVAL_ORDER
    .filter((key) => safeIntervals.some((i) => i.interval === key && i.enabled))
    .map((key) => safeIntervals.find((i) => i.interval === key)!)

  const handleSelect = useCallback(
    (interval: string) => {
      if (interval !== selected) {
        onChange(interval)
      }
    },
    [selected, onChange],
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const currentIndex = sortedIntervals.findIndex((i) => i.interval === selected)
      let nextIndex = currentIndex

      if (e.key === 'ArrowRight') {
        nextIndex = (currentIndex + 1) % sortedIntervals.length
      } else if (e.key === 'ArrowLeft') {
        nextIndex = (currentIndex - 1 + sortedIntervals.length) % sortedIntervals.length
      } else {
        return
      }

      e.preventDefault()
      const next = sortedIntervals[nextIndex]
      if (next) {
        onChange(next.interval)
      }
    },
    [selected, sortedIntervals, onChange],
  )

  if (sortedIntervals.length === 0) return null

  return (
    <div
      role="radiogroup"
      aria-label="Billing interval"
      className="inline-flex rounded-lg border border-gray-200 bg-gray-100 p-1"
    >
      {sortedIntervals.map((item) => {
        const isSelected = item.interval === selected
        const isRecommended = item.interval === recommendedInterval
        const discount = item.discount_percent ?? 0

        return (
          <button
            key={item.interval}
            type="button"
            role="radio"
            aria-checked={isSelected}
            tabIndex={isSelected ? 0 : -1}
            onClick={() => handleSelect(item.interval)}
            onKeyDown={handleKeyDown}
            className={`relative flex flex-col items-center rounded-md px-4 py-2 text-sm font-medium
              transition-all duration-300 ease-in-out
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1
              ${
                isSelected
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
          >
            <span className="transition-colors duration-300">
              {INTERVAL_LABELS[item.interval] ?? item.interval}
            </span>

            {isRecommended && (
              <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-500">
                Recommended
              </span>
            )}

            {discount > 0 && (
              <span className="mt-0.5 text-[10px] font-semibold text-green-600">
                Save {discount}%
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
