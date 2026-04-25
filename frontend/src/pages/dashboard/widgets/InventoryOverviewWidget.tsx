/**
 * Inventory Overview Widget
 *
 * Displays summary boxes per category (tyres, parts, fluids, other)
 * with total count and low-stock count. Low-stock counts are highlighted
 * in amber/red. Each category navigates to the inventory page filtered
 * by that category.
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
        <p className="text-sm text-gray-500">No inventory items</p>
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
                className="rounded-lg border border-gray-200 p-3 hover:border-blue-300 hover:bg-blue-50/30 transition-colors"
              >
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                  {categoryLabel(catSlug)}
                </p>
                <p className="mt-1 text-lg font-semibold text-gray-900">
                  {(total ?? 0).toLocaleString()}
                </p>
                {lowStock > 0 ? (
                  <p className="mt-0.5 text-xs font-medium text-amber-600">
                    {(lowStock ?? 0).toLocaleString()} low stock
                  </p>
                ) : (
                  <p className="mt-0.5 text-xs text-gray-400">
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
