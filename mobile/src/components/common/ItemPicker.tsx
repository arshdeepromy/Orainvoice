import { useCallback } from 'react'
import type { InventoryItem } from '@shared/types/inventory'
import { useApiList } from '@/hooks/useApiList'
import { MobileModal, MobileSearchBar, MobileListItem, MobileSpinner } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Props                                                              */
/* ------------------------------------------------------------------ */

export interface ItemPickerProps {
  /** Whether the picker modal is open */
  isOpen: boolean
  /** Called when the modal should close */
  onClose: () => void
  /** Called when an inventory item is selected — pre-fills description and unit price */
  onSelect: (item: InventoryItem) => void
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

/**
 * Searchable inventory item selection modal that pre-fills line item
 * description and unit price.
 *
 * Uses MobileModal + MobileSearchBar + useApiList<InventoryItem>.
 *
 * Requirements: 15.3, 15.4, 16.3
 */
export function ItemPicker({ isOpen, onClose, onSelect }: ItemPickerProps) {
  const {
    items,
    isLoading,
    search,
    setSearch,
  } = useApiList<InventoryItem>({
    endpoint: '/api/v1/inventory',
    dataKey: 'items',
  })

  const handleSelect = useCallback(
    (item: InventoryItem) => {
      onSelect(item)
      onClose()
    },
    [onSelect, onClose],
  )

  return (
    <MobileModal isOpen={isOpen} onClose={onClose} title="Select Item">
      <div className="flex flex-col gap-3">
        <MobileSearchBar
          value={search}
          onChange={setSearch}
          placeholder="Search inventory…"
        />

        {isLoading ? (
          <div className="flex justify-center py-8">
            <MobileSpinner size="sm" />
          </div>
        ) : items.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
            No items found
          </p>
        ) : (
          <div className="flex flex-col" role="list">
            {items.map((item) => (
              <div key={item.id} role="listitem">
                <MobileListItem
                  title={item.name ?? 'Unnamed'}
                  subtitle={
                    [item.sku && `SKU: ${item.sku}`, item.description]
                      .filter(Boolean)
                      .join(' · ') || undefined
                  }
                  trailing={
                    <div className="flex flex-col items-end">
                      <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {formatCurrency(item.unit_price)}
                      </span>
                      <span className="text-xs text-gray-400 dark:text-gray-500">
                        Stock: {item.stock_level ?? 0}
                      </span>
                    </div>
                  }
                  onTap={() => handleSelect(item)}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </MobileModal>
  )
}
