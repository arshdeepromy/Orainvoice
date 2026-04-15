import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  invoiceToReceiptData,
  type InvoiceForReceipt,
} from '../utils/invoiceReceiptMapper';

// Feature: pos-invoice-receipt-print, Property 1
// **Validates: Requirements 4.1, 4.2, 4.7, 4.10, 6.1, 6.2**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Arbitrary for a minimal valid InvoiceForReceipt focused on scalar/org fields */
const invoiceForFieldMappingArb = (): fc.Arbitrary<InvoiceForReceipt> =>
  fc.record({
    org_name: fc.option(fc.string({ minLength: 0, maxLength: 80 }), { nil: undefined }),
    org_address: fc.option(fc.string({ minLength: 0, maxLength: 120 }), { nil: undefined }),
    org_phone: fc.option(fc.string({ minLength: 0, maxLength: 30 }), { nil: undefined }),
    org_gst_number: fc.option(fc.string({ minLength: 1, maxLength: 30 }), { nil: undefined }),
    invoice_number: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
    issue_date: fc.constant('2025-06-01'),
    created_at: fc.constant('2025-05-30T10:00:00Z'),
    customer: fc.constant(null),
    line_items: fc.constant([]),
    subtotal: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
    gst_amount: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
    discount_amount: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
    total: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
    amount_paid: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
    balance_due: fc.double({ min: 0, max: 100000, noNaN: true, noDefaultInfinity: true }),
    payments: fc.constant([]),
    notes_customer: fc.option(fc.string({ minLength: 1, maxLength: 200 }), { nil: null }),
  });

/* ------------------------------------------------------------------ */
/*  Property 1: Invoice-to-receipt field mapping preservation          */
/* ------------------------------------------------------------------ */

describe('Property 1: Invoice-to-receipt field mapping preservation', () => {
  it('orgName equals org_name or empty string when undefined', () => {
    fc.assert(
      fc.property(invoiceForFieldMappingArb(), (invoice) => {
        const receipt = invoiceToReceiptData(invoice);
        expect(receipt.orgName).toBe(invoice.org_name ?? '');
      }),
      { numRuns: 100 },
    );
  });

  it('orgAddress equals org_address', () => {
    fc.assert(
      fc.property(invoiceForFieldMappingArb(), (invoice) => {
        const receipt = invoiceToReceiptData(invoice);
        expect(receipt.orgAddress).toBe(invoice.org_address);
      }),
      { numRuns: 100 },
    );
  });

  it('orgPhone equals org_phone', () => {
    fc.assert(
      fc.property(invoiceForFieldMappingArb(), (invoice) => {
        const receipt = invoiceToReceiptData(invoice);
        expect(receipt.orgPhone).toBe(invoice.org_phone);
      }),
      { numRuns: 100 },
    );
  });

  it('subtotal, taxAmount, total, amountPaid, balanceDue equal their invoice counterparts', () => {
    fc.assert(
      fc.property(invoiceForFieldMappingArb(), (invoice) => {
        const receipt = invoiceToReceiptData(invoice);
        expect(receipt.subtotal).toBe(invoice.subtotal);
        expect(receipt.taxAmount).toBe(invoice.gst_amount);
        expect(receipt.total).toBe(invoice.total);
        expect(receipt.amountPaid).toBe(invoice.amount_paid);
        expect(receipt.balanceDue).toBe(invoice.balance_due);
      }),
      { numRuns: 100 },
    );
  });

  it('gstNumber equals org_gst_number when present', () => {
    fc.assert(
      fc.property(invoiceForFieldMappingArb(), (invoice) => {
        const receipt = invoiceToReceiptData(invoice);
        expect(receipt.gstNumber).toBe(invoice.org_gst_number);
      }),
      { numRuns: 100 },
    );
  });

  it('footer equals notes_customer when non-null, or default message when null', () => {
    fc.assert(
      fc.property(invoiceForFieldMappingArb(), (invoice) => {
        const receipt = invoiceToReceiptData(invoice);
        if (invoice.notes_customer) {
          expect(receipt.footer).toBe(invoice.notes_customer);
        } else {
          expect(receipt.footer).toBe('Thank you for your business!');
        }
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: pos-invoice-receipt-print, Property 2
// **Validates: Requirements 4.3**

/* ------------------------------------------------------------------ */
/*  Property 2: Invoice number maps to receipt number with DRAFT       */
/*              fallback                                                */
/* ------------------------------------------------------------------ */

describe('Property 2: Invoice number maps to receipt number with DRAFT fallback', () => {
  it('receiptNumber equals invoice_number when non-null, or "DRAFT" when null', () => {
    const invoiceNumberArb = fc.option(fc.string({ minLength: 1 }), { nil: null });

    fc.assert(
      fc.property(invoiceNumberArb, (invoiceNumber) => {
        const invoice: InvoiceForReceipt = {
          invoice_number: invoiceNumber,
          issue_date: '2025-06-01',
          created_at: '2025-05-30T10:00:00Z',
          customer: null,
          line_items: [],
          subtotal: 0,
          gst_amount: 0,
          discount_amount: 0,
          total: 0,
          amount_paid: 0,
          balance_due: 0,
          notes_customer: null,
        };

        const receipt = invoiceToReceiptData(invoice);

        if (invoiceNumber !== null) {
          expect(receipt.receiptNumber).toBe(invoiceNumber);
        } else {
          expect(receipt.receiptNumber).toBe('DRAFT');
        }
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: pos-invoice-receipt-print, Property 3
// **Validates: Requirements 4.4**

/* ------------------------------------------------------------------ */
/*  Property 3: Date formatting with issue_date fallback               */
/* ------------------------------------------------------------------ */

describe('Property 3: Date formatting with issue_date fallback', () => {
  /** Helper: format a Date as YYYY-MM-DD (ISO date-only string) */
  const toISODateStr = (d: Date): string => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };

  /** Helper: format a Date as DD/MM/YYYY (expected receipt format) */
  const toDDMMYYYY = (d: Date): string => {
    const day = String(d.getDate()).padStart(2, '0');
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const y = d.getFullYear();
    return `${day}/${m}/${y}`;
  };

  const dateArb = fc.date({ min: new Date(2000, 0, 1), max: new Date(2030, 0, 1) })
    .filter((d) => !isNaN(d.getTime()));

  it('uses issue_date when non-null and formats as DD/MM/YYYY', () => {
    fc.assert(
      fc.property(dateArb, dateArb, (issueDate, createdAt) => {
        const issueDateStr = toISODateStr(issueDate);
        const createdAtStr = toISODateStr(createdAt);

        const invoice: InvoiceForReceipt = {
          invoice_number: 'INV-001',
          issue_date: issueDateStr,
          created_at: createdAtStr,
          customer: null,
          line_items: [],
          subtotal: 0,
          gst_amount: 0,
          discount_amount: 0,
          total: 0,
          amount_paid: 0,
          balance_due: 0,
          notes_customer: null,
        };

        const receipt = invoiceToReceiptData(invoice);

        // Should use issue_date, formatted as DD/MM/YYYY
        expect(receipt.date).toBe(toDDMMYYYY(issueDate));
      }),
      { numRuns: 100 },
    );
  });

  it('falls back to created_at when issue_date is null and formats as DD/MM/YYYY', () => {
    fc.assert(
      fc.property(dateArb, (createdAt) => {
        const createdAtStr = toISODateStr(createdAt);

        const invoice: InvoiceForReceipt = {
          invoice_number: 'INV-001',
          issue_date: null,
          created_at: createdAtStr,
          customer: null,
          line_items: [],
          subtotal: 0,
          gst_amount: 0,
          discount_amount: 0,
          total: 0,
          amount_paid: 0,
          balance_due: 0,
          notes_customer: null,
        };

        const receipt = invoiceToReceiptData(invoice);

        // Should fall back to created_at, formatted as DD/MM/YYYY
        expect(receipt.date).toBe(toDDMMYYYY(createdAt));
      }),
      { numRuns: 100 },
    );
  });

  it('output always matches DD/MM/YYYY format', () => {
    const issueDateArb = fc.option(dateArb, { nil: null });

    fc.assert(
      fc.property(issueDateArb, dateArb, (issueDate, createdAt) => {
        const invoice: InvoiceForReceipt = {
          invoice_number: 'INV-001',
          issue_date: issueDate ? toISODateStr(issueDate) : null,
          created_at: toISODateStr(createdAt),
          customer: null,
          line_items: [],
          subtotal: 0,
          gst_amount: 0,
          discount_amount: 0,
          total: 0,
          amount_paid: 0,
          balance_due: 0,
          notes_customer: null,
        };

        const receipt = invoiceToReceiptData(invoice);

        // Must match DD/MM/YYYY pattern
        expect(receipt.date).toMatch(/^\d{2}\/\d{2}\/\d{4}$/);
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: pos-invoice-receipt-print, Property 4
// **Validates: Requirements 4.5**

/* ------------------------------------------------------------------ */
/*  Property 4: Customer name resolution                               */
/* ------------------------------------------------------------------ */

describe('Property 4: Customer name resolution', () => {
  const customerArb = fc.option(
    fc.record({
      display_name: fc.option(fc.string(), { nil: undefined }),
      first_name: fc.string(),
      last_name: fc.string(),
    }),
    { nil: null },
  );

  /** Build a minimal InvoiceForReceipt with the generated customer */
  const buildInvoice = (
    customer: { display_name?: string; first_name: string; last_name: string } | null,
  ): InvoiceForReceipt => ({
    invoice_number: 'INV-001',
    issue_date: '2025-06-01',
    created_at: '2025-05-30T10:00:00Z',
    customer,
    line_items: [],
    subtotal: 0,
    gst_amount: 0,
    discount_amount: 0,
    total: 0,
    amount_paid: 0,
    balance_due: 0,
    notes_customer: null,
  });

  it('customerName equals display_name when non-empty, or first+last trimmed, or undefined when null', () => {
    fc.assert(
      fc.property(customerArb, (customer) => {
        const invoice = buildInvoice(customer);
        const receipt = invoiceToReceiptData(invoice);

        if (customer === null) {
          // No customer → customerName should be undefined
          expect(receipt.customerName).toBeUndefined();
        } else if (customer.display_name && customer.display_name.length > 0) {
          // Non-empty display_name takes priority
          expect(receipt.customerName).toBe(customer.display_name);
        } else {
          // Fallback to first_name + " " + last_name, trimmed
          const expected = `${customer.first_name} ${customer.last_name}`.trim();
          expect(receipt.customerName).toBe(expected);
        }
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: pos-invoice-receipt-print, Property 5
// **Validates: Requirements 4.6, 4.8**

/* ------------------------------------------------------------------ */
/*  Property 5: Line items and payments array mapping                  */
/* ------------------------------------------------------------------ */

describe('Property 5: Line items and payments array mapping', () => {
  const lineItemArb = fc.record({
    description: fc.string(),
    quantity: fc.nat(),
    unit_price: fc.double({ noNaN: true, noDefaultInfinity: true, min: 0 }),
    line_total: fc.double({ noNaN: true, noDefaultInfinity: true, min: 0 }),
  });

  const paymentArb = fc.record({
    method: fc.string(),
    amount: fc.double({ noNaN: true, noDefaultInfinity: true, min: 0 }),
  });

  /** Build a minimal InvoiceForReceipt with the generated arrays */
  const buildInvoice = (
    lineItems: Array<{ description: string; quantity: number; unit_price: number; line_total: number }>,
    payments: Array<{ method: string; amount: number }>,
  ): InvoiceForReceipt => ({
    invoice_number: 'INV-001',
    issue_date: '2025-06-01',
    created_at: '2025-05-30T10:00:00Z',
    customer: null,
    line_items: lineItems,
    subtotal: 0,
    gst_amount: 0,
    discount_amount: 0,
    total: 0,
    amount_paid: 0,
    balance_due: 0,
    payments,
    notes_customer: null,
  });

  it('items array has the same length as input line_items and preserves quantity, unitPrice, and total', () => {
    fc.assert(
      fc.property(fc.array(lineItemArb), (lineItems) => {
        const invoice = buildInvoice(lineItems, []);
        const receipt = invoiceToReceiptData(invoice);

        expect(receipt.items).toHaveLength(lineItems.length);

        for (let i = 0; i < lineItems.length; i++) {
          expect(receipt.items[i].quantity).toBe(lineItems[i].quantity);
          expect(receipt.items[i].unitPrice).toBe(lineItems[i].unit_price);
          expect(receipt.items[i].total).toBe(lineItems[i].line_total);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('paymentBreakdown has the same length as input payments and preserves method and amount when non-empty', () => {
    fc.assert(
      fc.property(
        fc.array(lineItemArb),
        fc.array(paymentArb, { minLength: 1 }),
        (lineItems, payments) => {
          const invoice = buildInvoice(lineItems, payments);
          const receipt = invoiceToReceiptData(invoice);

          expect(receipt.paymentBreakdown).toBeDefined();
          expect(receipt.paymentBreakdown).toHaveLength(payments.length);

          for (let i = 0; i < payments.length; i++) {
            expect(receipt.paymentBreakdown![i].method).toBe(payments[i].method);
            expect(receipt.paymentBreakdown![i].amount).toBe(payments[i].amount);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it('paymentBreakdown is undefined when payments array is empty', () => {
    fc.assert(
      fc.property(fc.array(lineItemArb), (lineItems) => {
        const invoice = buildInvoice(lineItems, []);
        const receipt = invoiceToReceiptData(invoice);

        expect(receipt.paymentBreakdown).toBeUndefined();
      }),
      { numRuns: 100 },
    );
  });
});
