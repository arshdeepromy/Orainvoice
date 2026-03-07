interface BarItem {
  label: string
  value: number
  colour?: string
}

interface SimpleBarChartProps {
  items: BarItem[]
  /** Format function for value labels */
  formatValue?: (v: number) => string
  /** Accessible chart title */
  title: string
}

/**
 * Simple, mobile-friendly horizontal bar chart using Tailwind CSS.
 * No external chart library needed — pure CSS bars.
 * Requirements: 45.4
 */
export default function SimpleBarChart({ items, formatValue = (v) => String(v), title }: SimpleBarChartProps) {
  const max = Math.max(...items.map((i) => i.value), 1)

  return (
    <div role="img" aria-label={title} className="space-y-2">
      <h3 className="sr-only">{title}</h3>
      {items.map((item) => {
        const pct = Math.round((item.value / max) * 100)
        return (
          <div key={item.label} className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-sm text-gray-700 truncate" title={item.label}>
              {item.label}
            </span>
            <div className="flex-1 h-6 bg-gray-100 rounded overflow-hidden">
              <div
                className={`h-full rounded transition-all duration-300 ${item.colour || 'bg-blue-500'}`}
                style={{ width: `${pct}%` }}
                role="presentation"
              />
            </div>
            <span className="w-24 shrink-0 text-sm text-gray-600 text-right">
              {formatValue(item.value)}
            </span>
          </div>
        )
      })}
      {items.length === 0 && (
        <p className="text-sm text-gray-500 py-4 text-center">No data for this period.</p>
      )}
    </div>
  )
}
