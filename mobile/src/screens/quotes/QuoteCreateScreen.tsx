import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Block,
  BlockTitle,
  List,
  ListInput,
  Card,
  Button,
  Progressbar,
} from 'konsta/react'
import type { Customer } from '@shared/types/customer'
import type { InventoryItem } from '@shared/types/inventory'
import type { InvoiceLineItemCreate } from '@shared/types/invoice'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import HapticButton from '@/components/konsta/HapticButton'
import { CustomerPicker } from '@/components/common/CustomerPicker'
import { ItemPicker } from '@/components/common/ItemPicker'
import { ModuleGate } from '@/components/common/ModuleGate'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const TOTAL_STEPS = 4
const STEP_LABELS = ['Customer', 'Line Items', 'Details', 'Review & Save']

/* ------------------------------------------------------------------ */
/* Currency formatting — matches project convention (Requirement 56.4) */
/* ------------------------------------------------------------------ */

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

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

/* ------------------------------------------------------------------ */
/* Step indicator                                                      */
/* ------------------------------------------------------------------ */

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="px-4 pt-2 pb-1">
      <Progressbar progress={(current / total) * 100} />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs font-medium text-primary">
          Step {current} of {total}
        </span>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {STEP_LABELS[current - 1]}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Trash icon                                                          */
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
/* Main component                                                      */
/* ------------------------------------------------------------------ */

/**
 * Quote creation screen — multi-step form with Konsta UI components.
 *
 * Steps:
 * 1. Customer selection
 * 2. Line items
 * 3. Discount, terms, notes, expiry date
 * 4. Review & Save/Send
 *
 * Requirements: 24.2, 24.5
 */
export default function QuoteCreateScreen() {
  const navigate = useNavigate()

  // ---- Step state ----
  const [step, setStep] = useState(1)

  // ---- Step 1: Customer ----
  const [customerId, setCustomerId] = useState('')
  const [customerName, setCustomerName] = useState('')
  const [showCustomerPicker, setShowCustomerPicker] = useState(false)

  // ---- Step 2: Line Items ----
  const [lineItems, setLineItems] = useState<
    (InvoiceLineItemCreate & { tax_mode?: string })[]
  >([])
  const [showItemPicker, setShowItemPicker] = useState(false)

  // ---- Step 3: Details ----
  const [validUntil, setValidUntil] = useState('')
  const [discount, setDiscount] = useState(0)
  const [terms, setTerms] = useState('')
  const [notes, setNotes] = useState('')

  // ---- UI state ----
  const [errors, setErrors] = useState<QuoteFormErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // ---- Computed totals ----
  const subtotal = lineItems.reduce((sum, li) => {
    const qty = li.quantity ?? 0
    const price = li.unit_price ?? 0
    return sum + qty * price
  }, 0)
  const discountAmount = discount > 0 ? Math.round(discount * 100) / 100 : 0
  const taxAmount = lineItems.reduce((sum, li) => {
    const qty = li.quantity ?? 0
    const price = li.unit_price ?? 0
    const rate = li.tax_rate ?? 0
    return sum + Math.round(qty * price * rate * 100) / 100
  }, 0)
  const total = Math.round((subtotal - discountAmount + taxAmount) * 100) / 100

  // ---- Handlers ----
  const handleCustomerSelect = useCallback((customer: Customer) => {
    setCustomerId(customer.id)
    const name = [customer.first_name, customer.last_name].filter(Boolean).join(' ')
    setCustomerName(name || 'Unnamed')
    setErrors((prev) => ({ ...prev, customer: undefined }))
  }, [])

  const handleItemSelect = useCallback((item: InventoryItem) => {
    const newLineItem: InvoiceLineItemCreate & { tax_mode?: string } = {
      description: item.description ?? item.name ?? '',
      quantity: 1,
      unit_price: item.unit_price ?? 0,
      tax_rate: 0.15,
      tax_mode: 'exclusive',
    }
    setLineItems((prev) => [...prev, newLineItem])
    setErrors((prev) => ({ ...prev, line_items: undefined }))
  }, [])

  const updateLineItem = useCallback(
    (index: number, field: string, value: string | number) => {
      setLineItems((prev) => {
        const updated = [...prev]
        updated[index] = { ...updated[index], [field]: value }
        return updated
      })
    },
    [],
  )

  const removeLineItem = useCallback((index: number) => {
    setLineItems((prev) => prev.filter((_, i) => i !== index))
  }, [])

  const addEmptyLine = useCallback(() => {
    setLineItems((prev) => [
      ...prev,
      {
        description: '',
        quantity: 1,
        unit_price: 0,
        tax_rate: 0.15,
        tax_mode: 'exclusive',
      },
    ])
  }, [])

  // ---- Navigation ----
  const goNext = useCallback(() => {
    if (step === 1 && !customerId) {
      setErrors({ customer: 'Customer is required' })
      return
    }
    if (step === 2 && lineItems.length === 0) {
      setErrors({ line_items: 'At least one line item is required' })
      return
    }
    setErrors({})
    setStep((s) => Math.min(s + 1, TOTAL_STEPS))
  }, [step, customerId, lineItems.length])

  const goBack = useCallback(() => {
    setStep((s) => Math.max(s - 1, 1))
  }, [])

  // ---- Submit ----
  const handleSubmit = async (action: 'draft' | 'send') => {
    const formErrors = validateQuoteForm({
      customer_id: customerId,
      valid_until: validUntil,
      line_items: lineItems,
    })

    if (Object.keys(formErrors).length > 0) {
      setErrors(formErrors)
      if (formErrors.customer) setStep(1)
      else if (formErrors.line_items) setStep(2)
      else if (formErrors.valid_until) setStep(3)
      return
    }

    setIsSubmitting(true)
    setApiError(null)

    try {
      const res = await apiClient.post('/api/v1/quotes', {
        customer_id: customerId,
        valid_until: validUntil,
        line_items: lineItems.map((li) => ({
          description: li.description,
          quantity: li.quantity,
          unit_price: li.unit_price,
          tax_rate: li.tax_rate,
        })),
        discount_amount: discount > 0 ? discount : undefined,
        notes: notes.trim() || undefined,
        terms: terms.trim() || undefined,
        status: action === 'draft' ? 'draft' : 'sent',
        send_email: action === 'send',
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
    <ModuleGate moduleSlug="quotes">
      <Page data-testid="quote-create-page">
        <KonstaNavbar
          title="New Quote"
          showBack
          onBack={() => {
            if (step > 1) {
              goBack()
            } else {
              navigate(-1)
            }
          }}
          rightActions={
            <Button
              onClick={() => navigate(-1)}
              clear
              small
              className="text-gray-500"
            >
              Cancel
            </Button>
          }
        />

        <StepIndicator current={step} total={TOTAL_STEPS} />

        {/* API error banner */}
        {apiError && (
          <Block>
            <div
              className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
              role="alert"
            >
              {apiError}
              <button
                type="button"
                className="ml-2 text-xs underline"
                onClick={() => setApiError(null)}
              >
                Dismiss
              </button>
            </div>
          </Block>
        )}

        {/* ============================================================ */}
        {/* Step 1: Customer                                              */}
        {/* ============================================================ */}
        {step === 1 && (
          <>
            <BlockTitle>Customer</BlockTitle>
            <Block>
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
              {errors.customer && (
                <p className="mt-1 text-sm text-red-600 dark:text-red-400" role="alert">
                  {errors.customer}
                </p>
              )}
            </Block>
          </>
        )}

        {/* ============================================================ */}
        {/* Step 2: Line Items                                            */}
        {/* ============================================================ */}
        {step === 2 && (
          <>
            <BlockTitle>Line Items ({lineItems.length})</BlockTitle>

            {errors.line_items && (
              <Block>
                <p className="text-sm text-red-600 dark:text-red-400" role="alert">
                  {errors.line_items}
                </p>
              </Block>
            )}

            {lineItems.map((li, idx) => {
              const lineAmount = (li.quantity ?? 0) * (li.unit_price ?? 0)
              return (
                <Card key={idx} className="mx-4 mb-3">
                  <div className="flex items-start justify-between">
                    <span className="text-xs font-medium text-gray-400">
                      Item {idx + 1}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeLineItem(idx)}
                      className="flex h-8 w-8 items-center justify-center text-red-500"
                      aria-label={`Remove item ${idx + 1}`}
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </div>
                  <List strongIos outlineIos className="-mx-4 -mb-4 mt-1">
                    <ListInput
                      label="Description"
                      type="text"
                      value={li.description}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                        updateLineItem(idx, 'description', e.target.value)
                      }
                      placeholder="Item description"
                    />
                    <ListInput
                      label="Quantity"
                      type="number"
                      value={String(li.quantity)}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                        updateLineItem(idx, 'quantity', Number(e.target.value) || 0)
                      }
                    />
                    <ListInput
                      label="Unit Price"
                      type="number"
                      value={String(li.unit_price)}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                        updateLineItem(idx, 'unit_price', Number(e.target.value) || 0)
                      }
                    />
                    <ListInput
                      label="Tax Rate (%)"
                      type="number"
                      value={String((li.tax_rate ?? 0) * 100)}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                        updateLineItem(idx, 'tax_rate', (Number(e.target.value) || 0) / 100)
                      }
                    />
                  </List>
                  <div className="mt-2 text-right text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {formatNZD(lineAmount)}
                  </div>
                </Card>
              )
            })}

            <Block>
              <div className="flex gap-2">
                <Button
                  onClick={addEmptyLine}
                  outline
                  small
                  className="flex-1"
                >
                  + Add Empty Line
                </Button>
                <Button
                  onClick={() => setShowItemPicker(true)}
                  outline
                  small
                  className="flex-1"
                >
                  + From Catalogue
                </Button>
              </div>
            </Block>
          </>
        )}

        {/* ============================================================ */}
        {/* Step 3: Details (Discount, terms, notes, expiry)              */}
        {/* ============================================================ */}
        {step === 3 && (
          <>
            <BlockTitle>Quote Details</BlockTitle>
            <List strongIos outlineIos>
              <ListInput
                label="Valid Until"
                type="date"
                value={validUntil}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setValidUntil(e.target.value)
                  setErrors((prev) => ({ ...prev, valid_until: undefined }))
                }}
                info={errors.valid_until}
                error={Boolean(errors.valid_until)}
              />
              <ListInput
                label="Discount (NZD)"
                type="number"
                value={String(discount)}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                  setDiscount(Number(e.target.value) || 0)
                }
                placeholder="0.00"
              />
            </List>

            <BlockTitle>Terms & Notes</BlockTitle>
            <List strongIos outlineIos>
              <ListInput
                label="Terms"
                type="textarea"
                value={terms}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  setTerms(e.target.value)
                }
                placeholder="Payment terms…"
              />
              <ListInput
                label="Notes"
                type="textarea"
                value={notes}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
                  setNotes(e.target.value)
                }
                placeholder="Optional notes…"
              />
            </List>
          </>
        )}

        {/* ============================================================ */}
        {/* Step 4: Review & Save                                         */}
        {/* ============================================================ */}
        {step === 4 && (
          <>
            <BlockTitle>Review Quote</BlockTitle>
            <Card className="mx-4">
              <div className="flex flex-col gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Customer</span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {customerName}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Valid Until</span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {validUntil || '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Items</span>
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {lineItems.length}
                  </span>
                </div>
              </div>
            </Card>

            <Card className="mx-4 mt-3">
              <div className="flex flex-col gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Subtotal</span>
                  <span className="text-gray-900 dark:text-gray-100">
                    {formatNZD(subtotal)}
                  </span>
                </div>
                {discountAmount > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Discount</span>
                    <span className="text-red-600 dark:text-red-400">
                      -{formatNZD(discountAmount)}
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Tax</span>
                  <span className="text-gray-900 dark:text-gray-100">
                    {formatNZD(taxAmount)}
                  </span>
                </div>
                <div className="flex justify-between border-t border-gray-200 pt-2 dark:border-gray-600">
                  <span className="font-semibold text-gray-900 dark:text-gray-100">Total</span>
                  <span className="font-semibold text-gray-900 dark:text-gray-100">
                    {formatNZD(total)}
                  </span>
                </div>
              </div>
            </Card>

            <Block>
              <div className="flex flex-col gap-3">
                <HapticButton
                  large
                  onClick={() => handleSubmit('draft')}
                  disabled={isSubmitting}
                  className="w-full"
                >
                  {isSubmitting ? 'Saving…' : 'Save as Draft'}
                </HapticButton>
                <HapticButton
                  large
                  onClick={() => handleSubmit('send')}
                  disabled={isSubmitting}
                  colors={{
                    fillBgIos: 'bg-green-600',
                    fillBgMaterial: 'bg-green-600',
                    fillTextIos: 'text-white',
                    fillTextMaterial: 'text-white',
                  }}
                  className="w-full"
                >
                  {isSubmitting ? 'Sending…' : 'Save & Send'}
                </HapticButton>
              </div>
            </Block>
          </>
        )}

        {/* ============================================================ */}
        {/* Step navigation footer                                        */}
        {/* ============================================================ */}
        {step < TOTAL_STEPS && (
          <Block>
            <div className="flex gap-3">
              {step > 1 && (
                <Button onClick={goBack} outline className="flex-1">
                  Back
                </Button>
              )}
              <HapticButton onClick={goNext} large className="flex-1">
                Next
              </HapticButton>
            </div>
          </Block>
        )}

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
      </Page>
    </ModuleGate>
  )
}
