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
      className={`flex items-center gap-3 rounded-lg border px-3 py-2 ${
        isAvailable
          ? 'border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800'
          : 'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20'
      }`}
    >
      {/* Name + availability badge */}
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span
          className={`truncate text-sm font-medium ${
            isAvailable
              ? 'text-gray-900 dark:text-gray-100'
              : 'text-gray-400 line-through dark:text-gray-500'
          }`}
        >
          {name}
        </span>
        {!isAvailable && (
          <span className="inline-flex shrink-0 items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/40 dark:text-red-300">
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
          className="min-h-[44px] w-16 rounded-md border border-gray-300 px-2 py-1 text-center text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          aria-label={`Quantity for ${name}`}
        />
      </div>

      {/* Cost per unit (admin only) */}
      {isAdmin && costPerUnit != null && (
        <span className="w-20 text-right text-sm text-gray-600 dark:text-gray-400">
          ${costPerUnit.toFixed(2)}
        </span>
      )}

      {/* Line total (admin only) */}
      {isAdmin && costPerUnit != null && (
        <span className="w-24 text-right text-sm font-medium text-gray-900 dark:text-gray-100">
          ${lineTotal.toFixed(2)}
        </span>
      )}

      {/* Remove button */}
      <button
        type="button"
        onClick={onRemove}
        className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md text-gray-400 hover:text-red-500 dark:text-gray-500 dark:hover:text-red-400"
        aria-label={`Remove ${name}`}
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}
