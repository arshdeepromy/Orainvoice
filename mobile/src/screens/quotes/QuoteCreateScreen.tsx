import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Customer } from '@shared/types/customer'
import type { InventoryItem } from '@shared/types/inventory'
import type { InvoiceLineItemCreate } from '@shared/types/invoice'
import { MobileButton, MobileInput, MobileFormField } from '@/components/ui'
import { LineItemEditor } from '@/components/common/LineItemEditor'
import { CustomerPicker } from '@/components/common/CustomerPicker'
import { ItemPicker } from '@/components/common/ItemPicker'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Validation (exported for testing)                                   */
/* ------------------------------------------------------------------ */

export interface QuoteFormErrors {
  customer?: string
  valid_until?: string
  line_items?: string
}

export function validateQuoteForm(form: {
  customer_id: string
  valid_until: string
  line_items: InvoiceLineItemCreate[]
}): QuoteFormErrors {
  const errors: QuoteFormErrors = {}

  if (!form.customer_id) {
    errors.customer = 'Customer is required'
  }
  if (!form.valid_until) {
    errors.valid_until = 'Valid until date is required'
  }
  if (form.line_items.length === 0) {
    errors.line_items = 'At least one line item is required'
  }

  return errors
}

/**
 * Quote creation screen — form with customer picker, line item editor
 * (reuses LineItemEditor), tax, discount fields.
 *
 * Requirements: 9.3, 16.1, 16.2, 16.3
 */
export default function QuoteCreateScreen() {
  const navigate = useNavigate()

  // Form state
  const [customerId, setCustomerId] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [validUntil, setValidUntil] = useState('')
  const [notes, setNotes] = useState('')
  const [discount, setDiscount] = useState(0)
  const [lineItems, setLineItems] = useState<InvoiceLineItemCreate[]>([])

  // UI state
  const [showCustomerPicker, setShowCustomerPicker] = useState(false)
  const [showItemPicker, setShowItemPicker] = useState(false)
  const [errors, setErrors] = useState<QuoteFormErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleCustomerSelect = useCallback((customer: Customer) => {
    setCustomerId(customer.id)
    const name = [customer.first_name, customer.last_name].filter(Boolean).join(' ')
    setCustomerName(name || 'Unnamed')
    setErrors((prev) => ({ ...prev, customer: undefined }))
  }, [])

  const handleItemSelect = useCallback(
    (item: InventoryItem) => {
      const newLineItem: InvoiceLineItemCreate = {
        description: item.description ?? item.name ?? '',
        quantity: 1,
        unit_price: item.unit_price ?? 0,
        tax_rate: 0.15,
      }
      setLineItems((prev) => [...prev, newLineItem])
      setErrors((prev) => ({ ...prev, line_items: undefined }))
    },
    [],
  )

  const handleLineItemsChange = useCallback((items: InvoiceLineItemCreate[]) => {
    setLineItems(items)
    setErrors((prev) => ({ ...prev, line_items: undefined }))
  }, [])

  const handleSubmit = async () => {
    const formErrors = validateQuoteForm({
      customer_id: customerId,
      valid_until: validUntil,
      line_items: lineItems,
    })

    if (Object.keys(formErrors).length > 0) {
      setErrors(formErrors)
      return
    }

    setIsSubmitting(true)
    setApiError(null)

    try {
      const res = await apiClient.post('/api/v1/quotes', {
        customer_id: customerId,
        valid_until: validUntil,
        line_items: lineItems,
        discount_amount: discount > 0 ? discount : undefined,
        notes: notes.trim() || undefined,
      })
      const newId = res.data?.id ?? ''
      navigate(`/quotes/${newId}`, { replace: true })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? 'Failed to create quote'
      setApiError(detail)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          New Quote
        </h1>
        <MobileButton
          variant="ghost"
          size="sm"
          onClick={() => navigate(-1)}
        >
          Cancel
        </MobileButton>
      </div>

      {/* API error */}
      {apiError && (
        <div
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          role="alert"
        >
          {apiError}
        </div>
      )}

      {/* Customer selection */}
      <MobileFormField label="Customer" required error={errors.customer}>
        <button
          type="button"
          onClick={() => setShowCustomerPicker(true)}
          className="flex min-h-[44px] w-full items-center rounded-lg border border-gray-300 px-3 py-2 text-left text-base dark:border-gray-600 dark:bg-gray-800"
        >
          {customerName ? (
            <span className="text-gray-900 dark:text-gray-100">{customerName}</span>
          ) : (
            <span className="text-gray-400 dark:text-gray-500">Select customer…</span>
          )}
        </button>
      </MobileFormField>

      {/* Valid until date */}
      <MobileInput
        label="Valid Until"
        type="date"
        required
        value={validUntil}
        onChange={(e) => {
          setValidUntil(e.target.value)
          setErrors((prev) => ({ ...prev, valid_until: undefined }))
        }}
        error={errors.valid_until}
      />

      {/* Line items */}
      {errors.line_items && (
        <p className="text-sm text-red-600 dark:text-red-400" role="alert">
          {errors.line_items}
        </p>
      )}
      <LineItemEditor
        items={lineItems}
        onChange={handleLineItemsChange}
        discount={discount}
        onDiscountChange={setDiscount}
        onAddItem={() => setShowItemPicker(true)}
      />

      {/* Notes */}
      <MobileFormField label="Notes">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional notes…"
          rows={3}
          className="min-h-[44px] w-full rounded-lg border border-gray-300 px-3 py-2 text-base text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500"
        />
      </MobileFormField>

      {/* Submit */}
      <MobileButton
        variant="primary"
        fullWidth
        onClick={handleSubmit}
        isLoading={isSubmitting}
      >
        Create Quote
      </MobileButton>

      {/* Pickers */}
      <CustomerPicker
        isOpen={showCustomerPicker}
        onClose={() => setShowCustomerPicker(false)}
        onSelect={handleCustomerSelect}
      />
      <ItemPicker
        isOpen={showItemPicker}
        onClose={() => setShowItemPicker(false)}
        onSelect={handleItemSelect}
      />
    </div>
  )
}
