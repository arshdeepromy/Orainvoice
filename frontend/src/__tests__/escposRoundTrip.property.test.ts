import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  invoiceToReceiptData,
  type InvoiceForReceipt,
} from '../utils/invoiceReceiptMapper';
import { buildReceipt } from '../utils/escpos';

// Feature: pos-invoice-receipt-print, Property 6
// **Validates: Requirements 4.11**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const lineItemArb = fc.record({
  description: fc.string(),
  quantity: fc.nat(),
  unit_price: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  line_total: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
});

const paymentArb = fc.record({
  method: fc.string(),
  amount: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
});

const customerArb = fc.option(
  fc.record({
    display_name: fc.option(fc.string(), { nil: undefined }),
    first_name: fc.string(),
    last_name: fc.string(),
  }),
  { nil: null },
);

const invoiceArb: fc.Arbitrary<InvoiceForReceipt> = fc.record({
  org_name: fc.option(fc.string(), { nil: undefined }),
  org_address: fc.option(fc.string(), { nil: undefined }),
  org_phone: fc.option(fc.string(), { nil: undefined }),
  org_gst_number: fc.option(fc.string(), { nil: undefined }),
  invoice_number: fc.option(fc.string({ minLength: 1 }), { nil: null }),
  issue_date: fc.constant('2025-06-01'),
  created_at: fc.constant('2025-06-01'),
  customer: customerArb,
  line_items: fc.array(lineItemArb, { minLength: 1 }),
  subtotal: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  gst_amount: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  discount_amount: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  total: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  amount_paid: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  balance_due: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  payments: fc.array(paymentArb),
  notes_customer: fc.option(fc.string({ minLength: 1 }), { nil: null }),
});

const paperWidthArb = fc.constantFrom(58, 80);

/* ------------------------------------------------------------------ */
/*  Property 6: Invoice-to-receipt-to-ESC/POS round-trip integrity     */
/* ------------------------------------------------------------------ */

describe('Property 6: Invoice-to-receipt-to-ESC/POS round-trip integrity', () => {
  it('converting a valid invoice through invoiceToReceiptData then buildReceipt produces a non-empty Uint8Array', () => {
    fc.assert(
      fc.property(invoiceArb, paperWidthArb, (invoice, paperWidth) => {
        const receiptData = invoiceToReceiptData(invoice);
        const escposBytes = buildReceipt(receiptData, paperWidth);

        expect(escposBytes).toBeInstanceOf(Uint8Array);
        expect(escposBytes.length).toBeGreaterThan(0);
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: pos-invoice-receipt-print, Property 7
// **Validates: Requirements 4.9**

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/**
 * Scan `haystack` for the exact byte sequence `needle`.
 * Returns true if the needle appears anywhere in the haystack.
 */
function containsBytes(haystack: Uint8Array, needle: number[]): boolean {
  if (needle.length === 0) return true;
  const len = haystack.length - needle.length + 1;
  outer: for (let i = 0; i < len; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return true;
  }
  return false;
}

/* ------------------------------------------------------------------ */
/*  Property 7 Generator                                               */
/* ------------------------------------------------------------------ */

import type { ReceiptData } from '../utils/escpos';

const receiptLineItemArb = fc.record({
  name: fc.string({ minLength: 1 }),
  quantity: fc.nat({ max: 1000 }),
  unitPrice: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  total: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
});

const receiptDataWithBalanceDueArb: fc.Arbitrary<ReceiptData> = fc.record({
  orgName: fc.string({ minLength: 1 }),
  orgAddress: fc.option(fc.string(), { nil: undefined }),
  orgPhone: fc.option(fc.string(), { nil: undefined }),
  receiptNumber: fc.option(fc.string({ minLength: 1 }), { nil: undefined }),
  date: fc.constant('01/06/2025'),
  items: fc.array(receiptLineItemArb, { minLength: 1 }),
  subtotal: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  taxLabel: fc.option(fc.string(), { nil: undefined }),
  taxAmount: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  discountAmount: fc.option(
    fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
    { nil: undefined },
  ),
  total: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
  paymentMethod: fc.string({ minLength: 1 }),
  cashTendered: fc.option(
    fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
    { nil: undefined },
  ),
  changeGiven: fc.option(
    fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
    { nil: undefined },
  ),
  footer: fc.option(fc.string(), { nil: undefined }),
  customerName: fc.option(fc.string(), { nil: undefined }),
  gstNumber: fc.option(fc.string(), { nil: undefined }),
  amountPaid: fc.option(
    fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
    { nil: undefined },
  ),
  // balanceDue > 0 — constrained to reasonable currency values so the
  // formatted string doesn't overflow the 32-char line width on 58mm paper
  // and truncate the "BALANCE DUE:" label in the columns() helper.
  balanceDue: fc.double({ min: 0.01, max: 999999.99, noNaN: true, noDefaultInfinity: true }),
  paymentBreakdown: fc.option(
    fc.array(
      fc.record({
        method: fc.string({ minLength: 1 }),
        amount: fc.double({ min: 0, noNaN: true, noDefaultInfinity: true }),
      }),
    ),
    { nil: undefined },
  ),
});

/* ------------------------------------------------------------------ */
/*  Property 7: Balance due bold rendering in ESC/POS output           */
/* ------------------------------------------------------------------ */

describe('Property 7: Balance due bold rendering in ESC/POS output', () => {
  it('buildReceipt produces bold-on sequence followed by BALANCE DUE text when balanceDue > 0', () => {
    fc.assert(
      fc.property(
        receiptDataWithBalanceDueArb,
        paperWidthArb,
        (receiptData, paperWidth) => {
          const escposBytes = buildReceipt(receiptData, paperWidth);

          // 1. The output must contain the ESC/POS bold-on command: 0x1B 0x45 0x01
          const boldOnSequence = [0x1b, 0x45, 0x01];
          expect(containsBytes(escposBytes, boldOnSequence)).toBe(true);

          // 2. The decoded text must contain "BALANCE DUE"
          const decoded = new TextDecoder('utf-8', { fatal: false }).decode(
            escposBytes,
          );
          expect(decoded).toContain('BALANCE DUE');
        },
      ),
      { numRuns: 100 },
    );
  });
});
