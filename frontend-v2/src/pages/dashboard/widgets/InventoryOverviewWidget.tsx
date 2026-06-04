/**
 * Inventory Overview Widget
 *
 * Displays summary boxes per category (tyres, parts, fluids, other)
 * with total count and low-stock count. Low-stock counts are highlighted
 * in amber/red. Each category navigates to the inventory page filtered
 * by that category.
 *
 * Ported from frontend/src/pages/dashboard/widgets/InventoryOverviewWidget.tsx
 * (Task 18). Logic — `low_stock_count` / `total_count` guards, the category
 * label map, the `/inventory?category=…` links and the action link — preserved
 * verbatim (FR-1); presentation remapped onto the redesign tokens (FR-2): the
 * low-stock count uses `text-warn`, totals use `.mono`, category tiles use the
 * token border + accent hover.
 *
 * Requirements: 7.1, 7.2, 7.3, 7.4, 7.6
 */

import { Link } from 'react-router-dom'
import { WidgetCard } from './WidgetCard'
import type { InventoryCategory, WidgetDataSection } from './types'

interface InventoryOverviewWidgetProps {
  data: WidgetDataSection<InventoryCategory> | undefined | null
  isLoading: boolean
  error: string | null
}

function CubeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />
    </svg>
  )
}

function categoryLabel(category: string | null | undefined): string {
  switch (category) {
    case 'tyres': return 'Tyres'
    case 'parts': return 'Parts'
    case 'fluids': return 'Fluids'
    case 'other': return 'Other'
    default: return category ?? 'Unknown'
  }
}

export function InventoryOverviewWidget({ data, isLoading, error }: InventoryOverviewWidgetProps) {
  const items = data?.items ?? []

  return (
    <WidgetCard
      title="Inventory Overview"
      icon={CubeIcon}
      actionLink={{ label: 'View stock', to: '/inventory' }}
      isLoading={isLoading}
      error={error}
    >
      {items.length === 0 ? (
        <p className="text-[13px] text-muted">No inventory items</p>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {items.map((cat) => {
            const lowStock = cat?.low_stock_count ?? 0
            const total = cat?.total_count ?? 0
            const catSlug = cat?.category ?? 'other'

            return (
              <Link
                key={catSlug}
                to={`/inventory?category=${encodeURIComponent(catSlug)}`}
                className="rounded-ctl border border-border p-3 transition-colors hover:border-accent hover:bg-accent-soft"
              >
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted">
                  {categoryLabel(catSlug)}
                </p>
                <p className="mono mt-1 text-[18px] font-semibold text-text">
                  {(total ?? 0).toLocaleString()}
                </p>
                {lowStock > 0 ? (
                  <p className="mono mt-0.5 text-[12px] font-medium text-warn">
                    {(lowStock ?? 0).toLocaleString()} low stock
                  </p>
                ) : (
                  <p className="mt-0.5 text-[12px] text-muted-2">
                    All stocked
                  </p>
                )}
              </Link>
            )
          })}
        </div>
      )}
    </WidgetCard>
  )
}
