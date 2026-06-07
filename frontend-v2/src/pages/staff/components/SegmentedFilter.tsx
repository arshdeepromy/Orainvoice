/**
 * SegmentedFilter — a reusable `.seg`-style pill group for the Staff list
 * filters (R2). Replaces the previous role/status `<select>` controls with a
 * controlled segmented control.
 *
 * The frontend-v2 design system does not ship a `.seg` CSS class, so this
 * mirrors the established token-based pill group used by the Reports landing
 * (`RangeSeg` in `ReportsPage.tsx`): a `rounded-ctl` bordered container with
 * one real `<button>` per option, the selected option carrying the accent-soft
 * background/accent text and `aria-pressed`. This keeps the look consistent
 * with the rest of the page and the prototype's `.seg.on` active style
 * (accent-soft background, accent text, transparent border).
 *
 * Controlled: the parent owns `value`; clicking an option calls `onChange`
 * with that option's value. Selecting marks the option active (R2.3) and the
 * parent maps the value back onto the existing filter state.
 *
 * _Requirements: 2.1, 2.2, 2.3, 14.2_
 */

export interface SegmentedFilterOption {
  label: string
  value: string
}

interface SegmentedFilterProps {
  value: string
  onChange: (value: string) => void
  options: SegmentedFilterOption[]
  /** Accessible label for the option group (R2). */
  ariaLabel?: string
}

export default function SegmentedFilter({
  value,
  onChange,
  options,
  ariaLabel,
}: SegmentedFilterProps) {
  return (
    <div
      className="inline-flex gap-0.5 rounded-ctl border border-border bg-card p-[3px]"
      role="group"
      aria-label={ariaLabel}
    >
      {options.map((opt) => {
        const isActive = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => onChange(opt.value)}
            className={
              'rounded-[7px] px-[13px] py-1.5 text-[12.5px] font-medium transition-colors ' +
              (isActive
                ? 'bg-accent-soft text-accent'
                : 'text-muted hover:text-text')
            }
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
