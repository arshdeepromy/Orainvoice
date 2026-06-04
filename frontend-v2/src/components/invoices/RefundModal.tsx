import { useState, useEffect } from 'react'
import apiClient from '@/api/client'
import { Modal, Button, FormField, useToast, ToastContainer } from '@/components/ui'
import {
  formatNZD,
  validateAmount,
  getInitialRefundFormState,
} from './refund-credit-note.utils'

/**
 * RefundModal — Task 19 port of frontend/src/components/invoices/RefundModal.
 *
 * All logic (validation, confirm step, submit → POST /payments/refund with
 * method:'cash', toast feedback, state reset on open) is copied VERBATIM —
 * including the ISSUE-072 Stripe-disabled option. Styling is remapped onto the
 * design-system tokens + the v2 Button API (`secondary` → `ghost`). Shared with
 * Task 22.
 */

interface RefundModalProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  invoiceId: string
  refundableAmount: number
}

const inputClassName =
  'h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text shadow-sm placeholder:text-muted-2 focus-visible:outline-none focus-visible:border-accent focus-visible:shadow-[0_0_0_3px_var(--accent-soft)]'

const selectClassName =
  'h-[42px] w-full rounded-ctl border border-border bg-card px-[13px] text-[13.5px] text-text shadow-sm focus-visible:outline-none focus-visible:border-accent focus-visible:shadow-[0_0_0_3px_var(--accent-soft)]'

const textareaClassName =
  'w-full rounded-ctl border border-border bg-card px-[13px] py-2 text-[13.5px] text-text shadow-sm placeholder:text-muted-2 focus-visible:outline-none focus-visible:border-accent focus-visible:shadow-[0_0_0_3px_var(--accent-soft)]'

export function RefundModal({
  open,
  onClose,
  onSuccess,
  invoiceId,
  refundableAmount,
}: RefundModalProps) {
  const { toasts, addToast, dismissToast } = useToast()

  const [amount, setAmount] = useState(0)
  const [method, setMethod] = useState('cash')
  const [notes, setNotes] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  // Reset all state when modal opens/closes
  useEffect(() => {
    const initial = getInitialRefundFormState()
    setAmount(initial.amount)
    setMethod(initial.method)
    setNotes(initial.notes)
    setErrors(initial.errors)
    setApiError(initial.apiError)
    setSubmitting(initial.submitting)
    setShowConfirm(initial.showConfirm)
  }, [open])

  function validateField(field: 'amount') {
    const err = validateAmount(amount, refundableAmount)
    setErrors((prev) => {
      if (err) return { ...prev, [field]: err }
      const next = { ...prev }
      delete next[field]
      return next
    })
  }

  function handleProcessRefund() {
    const amountError = validateAmount(amount, refundableAmount)
    const newErrors: Record<string, string> = {}
    if (amountError) newErrors.amount = amountError
    setErrors(newErrors)

    if (Object.keys(newErrors).length > 0) return

    setShowConfirm(true)
  }

  async function handleConfirmRefund() {
    setSubmitting(true)
    setApiError('')

    try {
      await apiClient.post('/payments/refund', {
        invoice_id: invoiceId,
        amount,
        method: 'cash',
        notes,
      })
      addToast('success', 'Refund processed successfully')
      onClose()
      onSuccess()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setApiError(
        axiosErr?.response?.data?.detail || 'Something went wrong. Please try again.',
      )
      setShowConfirm(false)
    } finally {
      setSubmitting(false)
    }
  }

  function handleCancelConfirm() {
    setShowConfirm(false)
  }

  return (
    <>
      <Modal open={open} onClose={onClose} title="Process Refund">
        <div className="space-y-4">
          {apiError && (
            <div className="rounded-ctl bg-danger-soft p-3 text-sm text-danger" role="alert">
              {apiError}
            </div>
          )}

          {!showConfirm ? (
            <>
              <FormField
                label="Amount"
                error={errors.amount}
                helperText={`Maximum: ${formatNZD(refundableAmount)}`}
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

              <FormField label="Refund Method" required>
                {(props) => (
                  <select
                    {...props}
                    className={selectClassName}
                    value={method}
                    onChange={(e) => setMethod(e.target.value)}
                  >
                    <option value="cash">Cash</option>
                    <option value="stripe" disabled>
                      Stripe (Disabled — ISSUE-072)
                    </option>
                  </select>
                )}
              </FormField>

              <FormField label="Notes">
                {(props) => (
                  <textarea
                    {...props}
                    className={textareaClassName}
                    rows={3}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Optional notes about this refund"
                  />
                )}
              </FormField>

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" size="sm" onClick={onClose} type="button">
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleProcessRefund}
                  type="button"
                >
                  Process Refund
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-text">Confirm Refund</h3>
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-muted">Amount</dt>
                    <dd className="font-medium text-text">{formatNZD(amount)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted">Method</dt>
                    <dd className="font-medium text-text">
                      {method.charAt(0).toUpperCase() + method.slice(1)}
                    </dd>
                  </div>
                  {notes && (
                    <div className="flex justify-between">
                      <dt className="text-muted">Notes</dt>
                      <dd className="font-medium text-text">{notes}</dd>
                    </div>
                  )}
                </dl>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleCancelConfirm}
                  disabled={submitting}
                  type="button"
                >
                  Back
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleConfirmRefund}
                  loading={submitting}
                  disabled={submitting}
                  type="button"
                >
                  {submitting ? 'Processing…' : 'Confirm Refund'}
                </Button>
              </div>
            </>
          )}
        </div>
      </Modal>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </>
  )
}

export default RefundModal
