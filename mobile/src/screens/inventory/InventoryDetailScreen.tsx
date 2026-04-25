import { useParams, useNavigate } from 'react-router-dom'
import type { InventoryItem } from '@shared/types/inventory'
import { useApiDetail } from '@/hooks/useApiDetail'
import { MobileCard, MobileButton, MobileSpinner } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

function stockColor(level: number): string {
  if (level <= 0) return 'text-red-600 dark:text-red-400'
  if (level <= 5) return 'text-amber-600 dark:text-amber-400'
  return 'text-green-600 dark:text-green-400'
}

/* ------------------------------------------------------------------ */
/* Detail row helper                                                  */
/* ------------------------------------------------------------------ */

function DetailRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
      <span className="text-right text-sm font-medium text-gray-900 dark:text-gray-100">
        {value}
      </span>
    </div>
  )
}

/**
 * Inventory detail screen — full description, stock levels, pricing,
 * supplier information.
 *
 * Requirements: 17.3
 */
export default function InventoryDetailScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: item, isLoading, error } = useApiDetail<InventoryItem>({
    endpoint: `/api/v1/inventory/${id}`,
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (error || !item) {
    return (
      <div className="flex flex-col items-center gap-4 p-8">
        <p className="text-gray-500 dark:text-gray-400">
          {error ?? 'Item not found'}
        </p>
        <MobileButton variant="secondary" onClick={() => navigate(-1)}>
          Go Back
        </MobileButton>
      </div>
    )
  }

  const stock = item.stock_level ?? 0

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Back button */}
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="flex min-h-[44px] items-center gap-1 self-start text-blue-600 dark:text-blue-400"
        aria-label="Back"
      >
        <svg
          className="h-5 w-5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 18-6-6 6-6" />
        </svg>
        Back
      </button>

      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          {item.name ?? 'Unnamed Item'}
        </h1>
        {item.sku && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            SKU: {item.sku}
          </p>
        )}
      </div>

      {/* Description */}
      {item.description && (
        <MobileCard>
          <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
            Description
          </h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            {item.description}
          </p>
        </MobileCard>
      )}

      {/* Stock & Pricing */}
      <MobileCard>
        <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
          Stock & Pricing
        </h2>
        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <span className="text-sm text-gray-500 dark:text-gray-400">Stock Level</span>
            <span className={`text-sm font-semibold ${stockColor(stock)}`}>
              {stock}
            </span>
          </div>
          <DetailRow label="Reorder Level" value={item.reorder_level} />
          <DetailRow label="Unit Price" value={formatCurrency(item.unit_price)} />
          <DetailRow label="Category" value={item.category} />
        </div>
      </MobileCard>

      {/* Supplier */}
      {item.supplier && (
        <MobileCard>
          <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
            Supplier
          </h2>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            {item.supplier}
          </p>
        </MobileCard>
      )}
    </div>
  )
}
