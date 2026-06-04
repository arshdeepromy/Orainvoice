import { useCallback } from 'react'
import type { IntervalPricing } from '@/pages/auth/signup-types'

/**
 * IntervalSelector — billing-interval segmented control (Task 13 port of
 * frontend/src/components/billing/IntervalSelector).
 *
 * ALL logic copied verbatim: the INTERVAL_ORDER canonical sort, enabled-only
 * filtering, the keyboard radiogroup navigation (ArrowLeft/Right wrap), the
 * recommended-interval label and the per-interval discount badge. Only the
 * markup classes are remapped to the prototype's `.seg` segmented control from
 * OraInvoice_Handoff/app/ds.css (card bg, 1px border, rounded-ctl, 3px padding;
 * selected segment → accent-soft bg + accent text). The import path is
 * corrected to the self-contained `@/` alias (FR-3).
 */

export interface IntervalSelectorProps {
  intervals: IntervalPricing[]
  selected: string
  onChange: (interval: string) => void
  recommendedInterval?: string
}

const INTERVAL_LABELS: Record<string, string> = {
  weekly: 'Weekly',
  fortnightly: 'Fortnightly',
  monthly: 'Monthly',
  annual: 'Annual',
}

const INTERVAL_ORDER = ['weekly', 'fortnightly', 'monthly', 'annual']

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
      className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]"
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
            className={`relative flex flex-col items-center rounded-[7px] px-4 py-1.5 text-[12.5px] font-medium
              transition-colors duration-150
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1
              ${
                isSelected
                  ? 'bg-accent-soft text-accent'
                  : 'text-muted hover:text-text'
              }`}
          >
            <span>{INTERVAL_LABELS[item.interval] ?? item.interval}</span>

            {isRecommended && (
              <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
                Recommended
              </span>
            )}

            {discount > 0 && (
              <span className="mt-0.5 text-[10px] font-semibold text-ok">
                Save {discount}%
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
