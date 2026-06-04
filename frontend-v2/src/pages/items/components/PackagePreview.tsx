import { useState } from 'react'
import { usePackageCosts } from '../hooks'
import type { PackageComponent, PackageCostComponent } from '../types'

interface PackagePreviewProps {
  itemId: string | null
  components: PackageComponent[]
  sellPrice: number
  userRole: string
}

/**
 * Read-only summary: component name, type, quantity/litres, unit cost, line total.
 * Shows total litres for fluids, total cost, sell price, profit.
 * Shows `current_stock_volume` / `current_quantity` per component.
 * "Low Stock" / "Out of Stock" badges when stock insufficient.
 * Triggered by "Preview Package" button (inline collapse, not separate modal).
 * Uses `usePackageCosts` hook from hooks.ts.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9
 */
export default function PackagePreview({
  itemId,
  components,
  sellPrice,
  userRole,
}: PackagePreviewProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const { data, loading, error, refetch } = usePackageCosts(isExpanded ? itemId : null)
  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'

  const hasComponents = (components ?? []).length > 0

  if (!hasComponents) {
    return null
  }

  // Calculate totals from local data when API data isn't available
  const resolvedComponents: PackageCostComponent[] = data?.components ?? []

  const totalLitres = resolvedComponents
    .filter((c) => c.catalogue_type === 'fluid')
    .reduce((sum, c) => sum + (c.volume ?? 0), 0)

  const totalCost = data?.total_cost ?? 0
  const profit = data?.profit ?? sellPrice - totalCost

  const getStockBadge = (comp: PackageCostComponent) => {
    const required = comp.catalogue_type === 'fluid' ? (comp.volume ?? 0) : (comp.quantity ?? 0)
    const available = comp.stock_available ?? 0

    if (available <= 0) {
      return (
        <span className="inline-flex items-center rounded-full bg-danger-soft px-2 py-0.5 text-xs font-medium text-danger">
          Out of Stock
        </span>
      )
    }
    if (available < required) {
      return (
        <span className="inline-flex items-center rounded-full bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn">
          Low Stock
        </span>
      )
    }
    return null
  }

  return (
    <div className="space-y-3">
      {/* Preview toggle button */}
      <button
        type="button"
        onClick={() => {
          setIsExpanded(!isExpanded)
          if (!isExpanded && itemId) {
            refetch()
          }
        }}
        className="min-h-[44px] inline-flex items-center gap-2 rounded-ctl border border-border px-4 py-2 text-sm font-medium text-text hover:bg-canvas"
      >
        <svg
          className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
        {isExpanded ? 'Close Preview' : 'Preview Package'}
      </button>

      {/* Expanded preview content */}
      {isExpanded && (
        <div className="rounded-card border border-border bg-card p-4">
          {loading && (
            <p className="text-sm text-muted">Loading package costs...</p>
          )}

          {error && (
            <div className="flex items-center gap-2 text-sm text-danger">
              <span>{error}</span>
              <button
                type="button"
                onClick={refetch}
                className="min-h-[44px] text-accent underline hover:text-accent-press"
              >
                Retry
              </button>
            </div>
          )}

          {!loading && !error && resolvedComponents.length > 0 && (
            <div className="space-y-4">
              {/* Component table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="pb-2 text-left font-medium text-muted">
                        Component
                      </th>
                      <th className="pb-2 text-left font-medium text-muted">
                        Type
                      </th>
                      <th className="pb-2 text-right font-medium text-muted">
                        Qty/Litres
                      </th>
                      {isAdmin && (
                        <>
                          <th className="pb-2 text-right font-medium text-muted">
                            Unit Cost
                          </th>
                          <th className="pb-2 text-right font-medium text-muted">
                            Line Total
                          </th>
                        </>
                      )}
                      <th className="pb-2 text-right font-medium text-muted">
                        Stock
                      </th>
                      <th className="pb-2 text-right font-medium text-muted">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {resolvedComponents.map((comp) => (
                      <tr key={comp.catalogue_item_id}>
                        <td className="py-2 text-text">
                          {comp.name ?? 'Unknown'}
                        </td>
                        <td className="py-2 capitalize text-muted">
                          {comp.catalogue_type}
                        </td>
                        <td className="mono py-2 text-right text-text">
                          {comp.catalogue_type === 'fluid'
                            ? `${(comp.volume ?? 0).toFixed(1)}L`
                            : comp.quantity ?? 0}
                        </td>
                        {isAdmin && (
                          <>
                            <td className="mono py-2 text-right text-muted">
                              ${(comp.cost_per_unit ?? 0).toFixed(2)}
                            </td>
                            <td className="mono py-2 text-right font-medium text-text">
                              ${(comp.line_total ?? 0).toFixed(2)}
                            </td>
                          </>
                        )}
                        <td className="mono py-2 text-right text-muted">
                          {comp.stock_available ?? 0}
                        </td>
                        <td className="py-2 text-right">{getStockBadge(comp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Summary section */}
              <div className="border-t border-border pt-3">
                <div className="space-y-1">
                  {totalLitres > 0 && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted">Total Fluids</span>
                      <span className="mono text-text">
                        {totalLitres.toFixed(1)}L
                      </span>
                    </div>
                  )}

                  {isAdmin && (
                    <>
                      <div className="flex justify-between text-sm">
                        <span className="text-muted">Total Cost</span>
                        <span className="mono font-medium text-text">
                          ${totalCost.toFixed(2)}
                        </span>
                      </div>

                      <div className="flex justify-between text-sm">
                        <span className="text-muted">Sell Price</span>
                        <span className="mono font-medium text-text">
                          ${sellPrice.toFixed(2)}
                        </span>
                      </div>

                      <div className="flex justify-between text-sm">
                        <span className="text-muted">Profit</span>
                        <span
                          className={`mono font-semibold ${
                            profit < 0
                              ? 'text-danger'
                              : 'text-ok'
                          }`}
                        >
                          ${profit.toFixed(2)}
                        </span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {!loading && !error && resolvedComponents.length === 0 && !itemId && (
            <p className="text-sm text-muted">
              Save the package first to preview live costs and stock availability.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
