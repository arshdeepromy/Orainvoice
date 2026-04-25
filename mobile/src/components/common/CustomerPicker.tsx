import { useCallback } from 'react'
import type { Customer } from '@shared/types/customer'
import { useApiList } from '@/hooks/useApiList'
import { MobileModal, MobileSearchBar, MobileListItem, MobileSpinner } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Props                                                              */
/* ------------------------------------------------------------------ */

export interface CustomerPickerProps {
  /** Whether the picker modal is open */
  isOpen: boolean
  /** Called when the modal should close */
  onClose: () => void
  /** Called when a customer is selected */
  onSelect: (customer: Customer) => void
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function displayName(c: Customer): string {
  const parts = [c.first_name, c.last_name].filter(Boolean)
  return parts.join(' ') || 'Unnamed'
}

function subtitle(c: Customer): string | undefined {
  const parts: string[] = []
  if (c.phone) parts.push(c.phone)
  if (c.email) parts.push(c.email)
  return parts.length > 0 ? parts.join(' · ') : undefined
}

/**
 * Searchable customer selection modal.
 *
 * Uses MobileModal + MobileSearchBar + useApiList<Customer>.
 *
 * Requirements: 8.3, 9.3
 */
export function CustomerPicker({ isOpen, onClose, onSelect }: CustomerPickerProps) {
  const {
    items,
    isLoading,
    search,
    setSearch,
  } = useApiList<Customer>({
    endpoint: '/api/v1/customers',
    dataKey: 'customers',
  })

  const handleSelect = useCallback(
    (customer: Customer) => {
      onSelect(customer)
      onClose()
    },
    [onSelect, onClose],
  )

  return (
    <MobileModal isOpen={isOpen} onClose={onClose} title="Select Customer">
      <div className="flex flex-col gap-3">
        <MobileSearchBar
          value={search}
          onChange={setSearch}
          placeholder="Search customers…"
        />

        {isLoading ? (
          <div className="flex justify-center py-8">
            <MobileSpinner size="sm" />
          </div>
        ) : items.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
            No customers found
          </p>
        ) : (
          <div className="flex flex-col" role="list">
            {items.map((customer) => (
              <div key={customer.id} role="listitem">
                <MobileListItem
                  title={displayName(customer)}
                  subtitle={subtitle(customer)}
                  trailing={
                    customer.company ? (
                      <span className="text-xs text-gray-400 dark:text-gray-500">
                        {customer.company}
                      </span>
                    ) : undefined
                  }
                  onTap={() => handleSelect(customer)}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </MobileModal>
  )
}
