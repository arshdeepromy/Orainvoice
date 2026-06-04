import { useState, useEffect } from 'react'
import { useFluidsSearch } from '../hooks'
import type { PackageComponent, FluidSearchResult } from '../types'

interface FluidEntryProps {
  component: PackageComponent
  userRole: string
  onChange: (updated: PackageComponent) => void
  onRemove: () => void
}

const OIL_TYPES = [
  { value: 'engine', label: 'Engine' },
  { value: 'hydraulic', label: 'Hydraulic' },
  { value: 'brake', label: 'Brake' },
  { value: 'gear', label: 'Gear' },
  { value: 'transmission', label: 'Transmission' },
  { value: 'power_steering', label: 'Power Steering' },
]

/**
 * A single fluid entry within the FluidSelector.
 * Oil/Non-Oil toggle → oil_type dropdown (for oil) → product dropdown → litres input.
 * Cascading dropdowns: fluid_type → oil_type → product selection.
 * Uses `useFluidsSearch` hook from hooks.ts.
 * Displays cost per litre (admin only) and "No matching product" message when empty.
 *
 * Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
 */
export default function FluidEntry({ component, userRole, onChange, onRemove }: FluidEntryProps) {
  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'

  const [fluidType, setFluidType] = useState<'oil' | 'non-oil'>(
    (component.fluid_type as 'oil' | 'non-oil') ?? 'oil'
  )
  const [oilType, setOilType] = useState<string>(component.oil_type ?? '')
  const [selectedProductId, setSelectedProductId] = useState<string>(
    component.catalogue_item_id ?? ''
  )
  const [volume, setVolume] = useState<number>(component.volume ?? 0)

  // Search fluids based on current selections
  const searchQuery = fluidType === 'non-oil' ? '' : ''
  const { items: products, loading } = useFluidsSearch(
    searchQuery,
    fluidType,
    fluidType === 'oil' ? oilType || undefined : undefined
  )

  // Find the selected product in results
  const selectedProduct = (products ?? []).find((p) => p.id === selectedProductId) ?? null

  // Sync local state changes back to parent
  useEffect(() => {
    if (selectedProductId && volume > 0) {
      const product = (products ?? []).find((p) => p.id === selectedProductId)
      onChange({
        ...component,
        catalogue_item_id: selectedProductId,
        catalogue_type: 'fluid',
        fluid_type: fluidType,
        oil_type: fluidType === 'oil' ? oilType : undefined,
        grade: product?.grade ?? undefined,
        volume,
        cost_per_unit_snapshot: product?.cost_per_unit ?? component.cost_per_unit_snapshot,
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProductId, volume, fluidType, oilType])

  const handleFluidTypeChange = (newType: 'oil' | 'non-oil') => {
    setFluidType(newType)
    setOilType('')
    setSelectedProductId('')
  }

  const handleOilTypeChange = (newOilType: string) => {
    setOilType(newOilType)
    setSelectedProductId('')
  }

  return (
    <div className="rounded-card border border-border bg-card p-4">
      <div className="flex items-start justify-between">
        <div className="flex-1 space-y-3">
          {/* Fluid type toggle: Oil / Non-Oil */}
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text">Type:</span>
            <div className="inline-flex rounded-ctl border border-border">
              <button
                type="button"
                onClick={() => handleFluidTypeChange('oil')}
                className={`min-h-[44px] px-4 py-2 text-sm font-medium rounded-l-ctl ${
                  fluidType === 'oil'
                    ? 'bg-accent text-white'
                    : 'bg-card text-text hover:bg-canvas'
                }`}
              >
                Oil
              </button>
              <button
                type="button"
                onClick={() => handleFluidTypeChange('non-oil')}
                className={`min-h-[44px] px-4 py-2 text-sm font-medium rounded-r-ctl ${
                  fluidType === 'non-oil'
                    ? 'bg-accent text-white'
                    : 'bg-card text-text hover:bg-canvas'
                }`}
              >
                Non-Oil
              </button>
            </div>
          </div>

          {/* Oil type dropdown (only for oil) */}
          {fluidType === 'oil' && (
            <div>
              <label className="block text-[12.5px] font-medium text-text">
                Oil Type
              </label>
              <select
                value={oilType}
                onChange={(e) => handleOilTypeChange(e.target.value)}
                className="mt-1 min-h-[44px] w-full appearance-none rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              >
                <option value="">Select oil type...</option>
                {OIL_TYPES.map((ot) => (
                  <option key={ot.value} value={ot.value}>
                    {ot.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Product dropdown */}
          <div>
            <label className="block text-[12.5px] font-medium text-text">
              Product
            </label>
            {loading ? (
              <p className="mt-1 text-sm text-muted">Loading products...</p>
            ) : (products ?? []).length === 0 ? (
              <p className="mt-1 text-sm text-warn">
                No matching product found in inventory
              </p>
            ) : (
              <select
                value={selectedProductId}
                onChange={(e) => setSelectedProductId(e.target.value)}
                className="mt-1 min-h-[44px] w-full appearance-none rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
              >
                <option value="">Select product...</option>
                {(products ?? []).map((product: FluidSearchResult) => (
                  <option key={product.id} value={product.id}>
                    {product.product_name}
                    {product.brand_name ? ` (${product.brand_name})` : ''}
                    {product.grade ? ` - ${product.grade}` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Volume (litres) input */}
          {selectedProductId && (
            <div className="flex items-center gap-4">
              <div>
                <label className="block text-[12.5px] font-medium text-text">
                  Litres
                </label>
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={volume || ''}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value)
                    if (!isNaN(val) && val > 0) {
                      setVolume(val)
                    } else if (e.target.value === '') {
                      setVolume(0)
                    }
                  }}
                  className="mono mt-1 min-h-[44px] w-24 rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
                  placeholder="0.0"
                />
              </div>

              {/* Cost per litre (admin only) */}
              {isAdmin && selectedProduct?.cost_per_unit != null && (
                <div className="text-sm text-muted">
                  <span className="block text-xs text-muted-2">$/litre</span>
                  <span className="mono font-medium">${selectedProduct.cost_per_unit.toFixed(2)}</span>
                </div>
              )}

              {/* Line total (admin only) */}
              {isAdmin && selectedProduct?.cost_per_unit != null && volume > 0 && (
                <div className="text-sm text-text">
                  <span className="block text-xs text-muted-2">Total</span>
                  <span className="mono font-semibold">
                    ${(selectedProduct.cost_per_unit * volume).toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Remove button */}
        <button
          type="button"
          onClick={onRemove}
          className="ml-3 min-h-[44px] min-w-[44px] flex items-center justify-center rounded-ctl text-muted-2 hover:text-danger"
          aria-label="Remove fluid entry"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}
