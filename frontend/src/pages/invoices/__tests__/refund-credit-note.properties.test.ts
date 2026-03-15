import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  formatNZD,
  computeCreditableAmount,
  computePaymentSummary,
  validateAmount,
  validateReason,
  computeItemsTotal,
  hasItemAmountMismatch,
  isCreditNoteButtonVisible,
  isRefundButtonVisible,
  getPaymentBadgeType,
  shouldShowRefundNote,
  getInitialCreditNoteFormState,
  getInitialRefundFormState,
} from '@/components/invoices/refund-credit-note.utils'

describe('Refund & Credit Note — Property-Based Tests', () => {
  // Feature: refund-credit-note-ui, Property 1: Creditable amount computation
  // **Validates: Requirements 1.2, 7.2**
  it('Property 1: creditable amount equals max(0, total - sum of existing amounts)', () => {
    fc.assert(
      fc.property(
        fc.float({ min: 0, max: 1e6, noNaN: true }),
        fc.array(fc.float({ min: 0, max: 1e6, noNaN: true })),
        (invoiceTotal, amounts) => {
          const result = computeCreditableAmount(invoiceTotal, amounts)
          const sum = amounts.reduce((acc, a) => acc + a, 0)
          const expected = Math.max(0, invoiceTotal - sum)
          expect(result).toBeCloseTo(expected, 5)
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 2: Payment summary computation
  // **Validates: Requirements 3.2, 6.4, 10.3**
  it('Property 2: payment summary correctly splits paid vs refunded', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            amount: fc.float({ min: 0, max: 1e6, noNaN: true }),
            is_refund: fc.boolean(),
          }),
        ),
        (payments) => {
          const result = computePaymentSummary(payments)

          const expectedPaid = payments
            .filter((p) => !p.is_refund)
            .reduce((acc, p) => acc + p.amount, 0)
          const expectedRefunded = payments
            .filter((p) => p.is_refund)
            .reduce((acc, p) => acc + p.amount, 0)

          expect(result.totalPaid).toBeCloseTo(expectedPaid, 5)
          expect(result.totalRefunded).toBeCloseTo(expectedRefunded, 5)
          expect(result.netPaid).toBeCloseTo(expectedPaid - expectedRefunded, 5)
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 3: Amount validation bounds
  // **Validates: Requirements 1.7, 1.8, 3.7, 3.8**
  it('Property 3: validateAmount returns null iff 0 < amount <= max', () => {
    fc.assert(
      fc.property(
        fc.float({ noNaN: true, noDefaultInfinity: true }),
        fc.float({ min: Math.fround(0.01), max: 1e6, noNaN: true }),
        (amount, maximum) => {
          const result = validateAmount(amount, maximum)
          if (amount > 0 && amount <= maximum) {
            expect(result).toBeNull()
          } else {
            expect(result).not.toBeNull()
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 4: Empty reason rejection
  // **Validates: Requirements 1.6**
  it('Property 4: validateReason rejects whitespace-only strings', () => {
    fc.assert(
      fc.property(
        fc.array(fc.constantFrom(' ', '\t', '\n', '\r')).map((chars) => chars.join('')),
        (whitespaceStr: string) => {
          const result = validateReason(whitespaceStr)
          expect(result).toBe('Reason is required')
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 5: NZD currency formatting
  // **Validates: Requirements 1.10, 3.10**
  it('Property 5: formatNZD output starts with $ or -$ and has exactly 2 decimal digits', () => {
    fc.assert(
      fc.property(
        fc.float({ noNaN: true, noDefaultInfinity: true, min: -1e9, max: 1e9 }),
        (value) => {
          const result = formatNZD(value)
          // Should start with "$" or "-$"
          expect(result.startsWith('$') || result.startsWith('-$')).toBe(true)
          // Should have exactly 2 decimal digits at the end
          expect(result).toMatch(/\.\d{2}$/)
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 6: Credit note item running total
  // **Validates: Requirements 2.3**
  it('Property 6: computeItemsTotal equals manual sum of item amounts', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            amount: fc.float({ noNaN: true, noDefaultInfinity: true, min: -1e6, max: 1e6 }),
          }),
        ),
        (items) => {
          const result = computeItemsTotal(items)
          const expected = items.reduce((acc, item) => acc + item.amount, 0)
          expect(result).toBeCloseTo(expected, 5)
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 7: Item amount mismatch detection
  // **Validates: Requirements 2.4**
  it('Property 7: hasItemAmountMismatch returns true iff items non-empty and sum !== creditNoteAmount', () => {
    fc.assert(
      fc.property(
        fc.float({ noNaN: true, noDefaultInfinity: true, min: -1e6, max: 1e6 }),
        fc.array(
          fc.record({
            amount: fc.float({ noNaN: true, noDefaultInfinity: true, min: -1e6, max: 1e6 }),
          }),
        ),
        (creditNoteAmount, items) => {
          const result = hasItemAmountMismatch(creditNoteAmount, items)
          if (items.length === 0) {
            expect(result).toBe(false)
          } else {
            const sum = computeItemsTotal(items)
            expect(result).toBe(sum !== creditNoteAmount)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 8: Credit note button visibility by invoice status
  // **Validates: Requirements 5.1, 5.2**
  it('Property 8: isCreditNoteButtonVisible returns true iff status in allowed set', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(
          'draft',
          'issued',
          'partially_paid',
          'paid',
          'overdue',
          'voided',
          'cancelled',
          'unknown',
        ),
        (status) => {
          const result = isCreditNoteButtonVisible(status)
          const allowed = ['issued', 'partially_paid', 'paid']
          expect(result).toBe(allowed.includes(status))
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 9: Refund button visibility by amount paid
  // **Validates: Requirements 5.3, 5.4**
  it('Property 9: isRefundButtonVisible returns true iff amountPaid > 0', () => {
    fc.assert(
      fc.property(
        fc.float({ noNaN: true, noDefaultInfinity: true, min: -1e6, max: 1e6 }),
        (amountPaid) => {
          const result = isRefundButtonVisible(amountPaid)
          expect(result).toBe(amountPaid > 0)
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 10: Payment vs refund badge assignment
  // **Validates: Requirements 6.1, 6.2, 10.2**
  it('Property 10: getPaymentBadgeType returns correct label and color', () => {
    fc.assert(
      fc.property(fc.boolean(), (isRefund) => {
        const result = getPaymentBadgeType(isRefund)
        if (isRefund) {
          expect(result).toEqual({ label: 'Refund', color: 'red' })
        } else {
          expect(result).toEqual({ label: 'Payment', color: 'green' })
        }
      }),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 11: Refund note conditional display
  // **Validates: Requirements 6.3**
  it('Property 11: shouldShowRefundNote returns true iff isRefund and refundNote is non-empty string', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.oneof(
          fc.constant(null),
          fc.constant(undefined),
          fc.constant(''),
          fc.string({ minLength: 1 }),
        ),
        (isRefund, refundNote) => {
          const result = shouldShowRefundNote(isRefund, refundNote)
          const expected =
            isRefund &&
            typeof refundNote === 'string' &&
            refundNote.trim() !== ''
          expect(result).toBe(expected)
        },
      ),
      { numRuns: 100 },
    )
  })

  // Feature: refund-credit-note-ui, Property 12: Modal form reset on reopen
  // **Validates: Requirements 8.5, 8.6**
  it('Property 12: getInitialCreditNoteFormState and getInitialRefundFormState always return same defaults', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (_iteration) => {
          const cnState = getInitialCreditNoteFormState()
          expect(cnState).toEqual({
            amount: 0,
            reason: '',
            items: [],
            errors: {},
            apiError: '',
            submitting: false,
          })

          const refundState = getInitialRefundFormState()
          expect(refundState).toEqual({
            amount: 0,
            method: 'cash',
            notes: '',
            errors: {},
            apiError: '',
            submitting: false,
            showConfirm: false,
          })

          // Verify each call returns a new object (not shared reference)
          const cnState2 = getInitialCreditNoteFormState()
          expect(cnState).not.toBe(cnState2)
          expect(cnState).toEqual(cnState2)
        },
      ),
      { numRuns: 100 },
    )
  })
})
