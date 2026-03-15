// Shared validation and formatting utilities for Refund & Credit Note UI

export interface CreditNoteItem {
  description: string
  amount: number
}

export interface CreditNoteFormState {
  amount: number
  reason: string
  items: CreditNoteItem[]
  errors: Record<string, string>
  apiError: string
  submitting: boolean
}

export interface RefundFormState {
  amount: number
  method: string
  notes: string
  errors: Record<string, string>
  apiError: string
  submitting: boolean
  showConfirm: boolean
}

const nzdFormatter = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
})

export function formatNZD(value: number | string): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (num == null || isNaN(num)) return '$0.00'
  return nzdFormatter.format(num)
}

export function computeCreditableAmount(
  invoiceTotal: number,
  existingCreditNoteAmounts: number[],
): number {
  const sum = existingCreditNoteAmounts.reduce((acc, amt) => acc + amt, 0)
  return Math.max(0, invoiceTotal - sum)
}

export function computePaymentSummary(
  payments: Array<{ amount: number | string; is_refund?: boolean }>,
): { totalPaid: number; totalRefunded: number; netPaid: number } {
  let totalPaid = 0
  let totalRefunded = 0
  for (const p of payments) {
    const amt = typeof p.amount === 'string' ? parseFloat(p.amount) || 0 : (p.amount || 0)
    if (p.is_refund) {
      totalRefunded += amt
    } else {
      totalPaid += amt
    }
  }
  return { totalPaid, totalRefunded, netPaid: totalPaid - totalRefunded }
}

export function validateAmount(amount: number, maximum: number): string | null {
  if (amount <= 0) return 'Amount must be greater than zero'
  if (amount > maximum) return `Amount cannot exceed ${formatNZD(maximum)}`
  return null
}

export function validateReason(reason: string): string | null {
  if (reason.trim() === '') return 'Reason is required'
  return null
}

export function computeItemsTotal(items: Array<{ amount: number }>): number {
  return items.reduce((acc, item) => acc + item.amount, 0)
}

export function hasItemAmountMismatch(
  creditNoteAmount: number,
  items: Array<{ amount: number }>,
): boolean {
  if (items.length === 0) return false
  return computeItemsTotal(items) !== creditNoteAmount
}

export function isCreditNoteButtonVisible(status: string): boolean {
  return ['issued', 'partially_paid', 'paid'].includes(status)
}

export function isRefundButtonVisible(amountPaid: number, status?: string): boolean {
  if (status === 'voided' || status === 'draft') return false
  return amountPaid > 0
}

export function getPaymentBadgeType(
  isRefund: boolean,
): { label: string; color: 'green' | 'red' } {
  return isRefund
    ? { label: 'Refund', color: 'red' }
    : { label: 'Payment', color: 'green' }
}

export function shouldShowRefundNote(
  isRefund: boolean,
  refundNote: string | null | undefined,
): boolean {
  return isRefund && typeof refundNote === 'string' && refundNote.trim() !== ''
}

export function getInitialCreditNoteFormState(): CreditNoteFormState {
  return {
    amount: 0,
    reason: '',
    items: [],
    errors: {},
    apiError: '',
    submitting: false,
  }
}

export function getInitialRefundFormState(): RefundFormState {
  return {
    amount: 0,
    method: 'cash',
    notes: '',
    errors: {},
    apiError: '',
    submitting: false,
    showConfirm: false,
  }
}
