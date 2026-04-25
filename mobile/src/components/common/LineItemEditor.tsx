import { useCallback } from 'react'
import type { InvoiceLineItemCreate } from '@shared/types/invoice'
import { MobileButton, MobileInput } from '@/components/ui'

/* ------------------------------------------------------------------ */
/* Pure calculation function — exported for property-based testing     */
/* ------------------------------------------------------------------ */

export interface LineItemTotals {
  subtotal: number
  tax: number
  total: number
}

/**
 * Calculate subtotal, tax, and total from a set of line items and discount.
 *
 * - subtotal = sum(qty × unit_price) for all items
 * - tax = sum(qty × unit_price × tax_rate) for all items
 * - total = subtotal + tax − discount
 *
 * **Validates: Requirements 15.2, 16.2**
 */
export function calculateTotals(
  items: ReadonlyArray<{ quantity: number; unit_price: number; tax_rate: number }>,
  discount: number = 0,
): LineItemTotals {
  let subtotal = 0
  let tax = 0

  for (const item of items) {
    const qty = item.quantity ?? 0
    const price = item.unit_price ?? 0
    const rate = item.tax_rate ?? 0
    const lineAmount = qty * price
    subtotal += lineAmount
    tax += lineAmount * rate
  }

  const total = subtotal + tax - discount

  return { subtotal, tax, total }
}

/* ------------------------------------------------------------------ */
/* Inline SVG icons                                                   */
/* ------------------------------------------------------------------ */

function TrashIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 6h18" />
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* Component props                                                    */
/* ------------------------------------------------------------------ */

export interface LineItemEditorProps {
  /** Current line items */
  items: InvoiceLineItemCreate[]
  /** Called when items change */
  onChange: (items: InvoiceLineItemCreate[]) => void
  /** Discount amount (default 0) */
  discount?: number
  /** Called when discount changes */
  onDiscountChange?: (discount: number) => void
  /** Called when "Add Item" is tapped — opens ItemPicker */
  onAddItem?: () => void
}

/**
 * Line item editor — add/edit/remove line items with description, quantity,
 * unit price, tax rate. Real-time subtotal/tax/total calculation.
 *
 * Requirements: 15.1, 15.2, 15.5, 16.1, 16.2
 */
export function LineItemEditor({
  items,
  onChange,
  discount = 0,
  onDiscountChange,
  onAddItem,
}: LineItemEditorProps) {
  const totals = calculateTotals(items, discount)

  const updateItem = useCallback(
    (index: number, field: keyof InvoiceLineItemCreate, value: string | number) => {
      const updated = [...items]
      updated[index] = { ...updated[index], [field]: value }
      onChange(updated)
    },
    [items, onChange],
  )

  const removeItem = useCallback(
    (index: number) => {
      const updated = items.filter((_, i) => i !== index)
      onChange(updated)
    },
    [items, onChange],
  )

  const addBlankItem = useCallback(() => {
    const blank: InvoiceLineItemCreate = {
      description: '',
      quantity: 1,
      unit_price: 0,
      tax_rate: 0.15,
    }
    onChange([...items, blank])
  }, [items, onChange])

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
        Line Items
      </h2>

      {items.map((item, index) => (
        <div
          key={index}
          className="rounded-lg border border-gray-200 p-3 dark:border-gray-700"
        >
          {/* Description */}
          <MobileInput
            label="Description"
            value={item.description}
            onChange={(e) => updateItem(index, 'description', e.target.value)}
            placeholder="Item description"
          />

          {/* Quantity, Unit Price, Tax Rate row */}
          <div className="mt-2 grid grid-cols-3 gap-2">
            <MobileInput
              label="Qty"
              type="number"
              min="0"
              step="1"
              value={String(item.quantity)}
              onChange={(e) =>
                updateItem(index, 'quantity', parseFloat(e.target.value) || 0)
              }
            />
            <MobileInput
              label="Price"
              type="number"
              min="0"
              step="0.01"
              value={String(item.unit_price)}
              onChange={(e) =>
                updateItem(index, 'unit_price', parseFloat(e.target.value) || 0)
              }
            />
            <MobileInput
              label="Tax %"
              type="number"
              min="0"
              max="100"
              step="1"
              value={String(Number(item.tax_rate * 100).toFixed(0))}
              onChange={(e) =>
                updateItem(
                  index,
                  'tax_rate',
                  (parseFloat(e.target.value) || 0) / 100,
                )
              }
            />
          </div>

          {/* Line total + remove */}
          <div className="mt-2 flex items-center justify-between">
            <span className="text-sm text-gray-500 dark:text-gray-400">
              Line total: ${Number((item.quantity ?? 0) * (item.unit_price ?? 0)).toFixed(2)}
            </span>
            <button
              type="button"
              onClick={() => removeItem(index)}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center text-red-500 hover:text-red-700 dark:text-red-400"
              aria-label={`Remove item ${index + 1}`}
            >
              <TrashIcon className="h-5 w-5" />
            </button>
          </div>
        </div>
      ))}

      {/* Add item buttons */}
      <div className="flex gap-3">
        {onAddItem && (
          <MobileButton variant="secondary" size="sm" onClick={onAddItem}>
            Add from Inventory
          </MobileButton>
        )}
        <MobileButton variant="ghost" size="sm" onClick={addBlankItem}>
          Add Blank Item
        </MobileButton>
      </div>

      {/* Running totals */}
      <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-800" aria-label="Invoice totals">
        <div className="flex flex-col gap-1 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Subtotal</span>
            <span className="text-gray-900 dark:text-gray-100">
              ${Number(totals.subtotal ?? 0).toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">Tax</span>
            <span className="text-gray-900 dark:text-gray-100">
              ${Number(totals.tax ?? 0).toFixed(2)}
            </span>
          </div>
          {onDiscountChange !== undefined && (
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-gray-400">Discount</span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={String(discount)}
                onChange={(e) =>
                  onDiscountChange?.(parseFloat(e.target.value) || 0)
                }
                className="w-24 rounded border border-gray-300 px-2 py-1 text-right text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
                aria-label="Discount amount"
              />
            </div>
          )}
          <div className="flex justify-between border-t border-gray-200 pt-1 dark:border-gray-600">
            <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
            <span className="font-semibold text-gray-900 dark:text-gray-100">
              ${Number(totals.total ?? 0).toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
