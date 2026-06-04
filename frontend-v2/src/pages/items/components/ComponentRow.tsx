import type { PackageComponent } from '../types'

interface ComponentRowProps {
  component: PackageComponent
  name: string
  costPerUnit: number | null
  isAvailable: boolean
  userRole: string
  onQuantityChange: (quantity: number) => void
  onRemove: () => void
}

/**
 * Displays a single component row within the parts/tyre selector.
 * Shows name, quantity input, cost per unit (admin only), line total (admin only), and remove button.
 * Marks unavailable components with strikethrough and "Unavailable" badge.
 *
 * Validates: Requirements 4.3, 4.4, 4.7, 4.8, 11.2
 */
export default function ComponentRow({
  component,
  name,
  costPerUnit,
  isAvailable,
  userRole,
  onQuantityChange,
  onRemove,
}: ComponentRowProps) {
  const isAdmin = userRole === 'org_admin' || userRole === 'global_admin'
  const quantity = component.quantity ?? 1
  const lineTotal = (costPerUnit ?? 0) * quantity

  return (
    <div
      className={`flex items-center gap-3 rounded-ctl border px-3 py-2 ${
        isAvailable
          ? 'border-border bg-card'
          : 'border-danger/40 bg-danger-soft'
      }`}
    >
      {/* Name + availability badge */}
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span
          className={`truncate text-sm font-medium ${
            isAvailable
              ? 'text-text'
              : 'text-muted-2 line-through'
          }`}
        >
          {name}
        </span>
        {!isAvailable && (
          <span className="inline-flex shrink-0 items-center rounded-full bg-danger-soft px-2 py-0.5 text-xs font-medium text-danger">
            Unavailable
          </span>
        )}
      </div>

      {/* Quantity input */}
      <div className="flex items-center gap-1">
        <label className="sr-only" htmlFor={`qty-${component.catalogue_item_id}`}>
          Quantity
        </label>
        <input
          id={`qty-${component.catalogue_item_id}`}
          type="number"
          min={1}
          value={quantity}
          onChange={(e) => {
            const val = parseInt(e.target.value, 10)
            if (!isNaN(val) && val >= 1) {
              onQuantityChange(val)
            }
          }}
          className="mono min-h-[44px] w-16 rounded-ctl border border-border bg-card px-2 py-1 text-center text-sm text-text focus:border-accent focus:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)]"
          aria-label={`Quantity for ${name}`}
        />
      </div>

      {/* Cost per unit (admin only) */}
      {isAdmin && costPerUnit != null && (
        <span className="mono w-20 text-right text-sm text-muted">
          ${costPerUnit.toFixed(2)}
        </span>
      )}

      {/* Line total (admin only) */}
      {isAdmin && costPerUnit != null && (
        <span className="mono w-24 text-right text-sm font-medium text-text">
          ${lineTotal.toFixed(2)}
        </span>
      )}

      {/* Remove button */}
      <button
        type="button"
        onClick={onRemove}
        className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-ctl text-muted-2 hover:text-danger"
        aria-label={`Remove ${name}`}
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}
