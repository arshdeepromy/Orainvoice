import { useState, useEffect } from 'react'
import apiClient from '../../api/client'
import { Modal, Button, FormField } from '../ui'
import { useToast, ToastContainer } from '../ui/Toast'
import {
  formatNZD,
  validateAmount,
  validateReason,
  computeItemsTotal,
  hasItemAmountMismatch,
  getInitialCreditNoteFormState,
  type CreditNoteItem,
} from './refund-credit-note.utils'

interface CreditNoteModalProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  invoiceId: string
  creditableAmount: number
}

const inputClassName =
  'h-[42px] w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500'

const textareaClassName =
  'w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:border-blue-500'

export function CreditNoteModal({
  open,
  onClose,
  onSuccess,
  invoiceId,
  creditableAmount,
}: CreditNoteModalProps) {
  const { toasts, addToast, dismissToast } = useToast()

  const [amount, setAmount] = useState(0)
  const [reason, setReason] = useState('')
  const [items, setItems] = useState<CreditNoteItem[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Reset all state when modal opens/closes
  useEffect(() => {
    const initial = getInitialCreditNoteFormState()
    setAmount(initial.amount)
    setReason(initial.reason)
    setItems(initial.items)
    setErrors(initial.errors)
    setApiError(initial.apiError)
    setSubmitting(initial.submitting)
  }, [open])

  function validateField(field: 'amount' | 'reason') {
    const err =
      field === 'amount'
        ? validateAmount(amount, creditableAmount)
        : validateReason(reason)
    setErrors((prev) => {
      if (err) return { ...prev, [field]: err }
      const next = { ...prev }
      delete next[field]
      return next
    })
  }

  function addItem() {
    setItems((prev) => [...prev, { description: '', amount: 0 }])
  }

  function removeItem(index: number) {
    setItems((prev) => prev.filter((_, i) => i !== index))
  }

  function updateItem(index: number, field: keyof CreditNoteItem, value: string | number) {
    setItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [field]: value } : item)),
    )
  }

  async function handleSubmit() {
    // Validate all fields
    const amountError = validateAmount(amount, creditableAmount)
    const reasonError = validateReason(reason)
    const newErrors: Record<string, string> = {}
    if (amountError) newErrors.amount = amountError
    if (reasonError) newErrors.reason = reasonError
    setErrors(newErrors)

    if (Object.keys(newErrors).length > 0) return

    setSubmitting(true)
    setApiError('')

    try {
      await apiClient.post(`/invoices/${invoiceId}/credit-note`, {
        amount,
        reason,
        items,
        process_stripe_refund: false,
      })
      addToast('success', 'Credit note created successfully')
      onClose()
      onSuccess()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setApiError(
        axiosErr?.response?.data?.detail || 'Something went wrong. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const itemsTotal = computeItemsTotal(items)
  const showMismatch = hasItemAmountMismatch(amount, items)

  return (
    <>
      <Modal open={open} onClose={onClose} title="Create Credit Note">
        <div className="space-y-4">
          {apiError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
              {apiError}
            </div>
          )}

          <FormField
            label="Amount"
            error={errors.amount}
            helperText={`Maximum: ${formatNZD(creditableAmount)}`}
            required
          >
            {(props) => (
              <input
                {...props}
                type="number"
                min={0}
                step="0.01"
                className={inputClassName}
                value={amount || ''}
                onChange={(e) => setAmount(parseFloat(e.target.value) || 0)}
                onBlur={() => validateField('amount')}
                placeholder="0.00"
              />
            )}
          </FormField>

          <FormField label="Reason" error={errors.reason} required>
            {(props) => (
              <textarea
                {...props}
                className={textareaClassName}
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                onBlur={() => validateField('reason')}
                placeholder="Enter reason for credit note"
              />
            )}
          </FormField>

          {/* Items section */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700">Items</span>
              <Button variant="secondary" size="sm" onClick={addItem} type="button">
                Add Item
              </Button>
            </div>

            {items.map((item, index) => (
              <div key={index} className="flex items-start gap-2 mb-2">
                <input
                  type="text"
                  className={inputClassName}
                  placeholder="Description"
                  value={item.description}
                  onChange={(e) => updateItem(index, 'description', e.target.value)}
                  aria-label={`Item ${index + 1} description`}
                />
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  className={`${inputClassName} max-w-[140px]`}
                  placeholder="0.00"
                  value={item.amount || ''}
                  onChange={(e) =>
                    updateItem(index, 'amount', parseFloat(e.target.value) || 0)
                  }
                  aria-label={`Item ${index + 1} amount`}
                />
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => removeItem(index)}
                  type="button"
                  aria-label={`Remove item ${index + 1}`}
                >
                  Remove
                </Button>
              </div>
            ))}

            {items.length > 0 && (
              <div className="mt-2 text-sm text-gray-600">
                Items total: {formatNZD(itemsTotal)}
              </div>
            )}

            {showMismatch && (
              <div className="mt-1 text-sm text-amber-600" role="alert">
                Item amounts do not match the credit note amount
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" size="sm" onClick={onClose} type="button">
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSubmit}
              loading={submitting}
              disabled={submitting}
              type="button"
            >
              {submitting ? 'Creating…' : 'Create Credit Note'}
            </Button>
          </div>
        </div>
      </Modal>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}
