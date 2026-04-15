import { describe, it, expect } from 'vitest';
import {
  invoiceToReceiptData,
  formatReceiptDate,
  type InvoiceForReceipt,
} from '../utils/invoiceReceiptMapper';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function makeInvoice(overrides: Partial<InvoiceForReceipt> = {}): InvoiceForReceipt {
  return {
    org_name: 'Test Org',
    org_address: '123 Main St',
    org_phone: '09 123 4567',
    org_gst_number: '123-456-789',
    invoice_number: 'INV-001',
    issue_date: '2025-03-15',
    created_at: '2025-03-14T10:00:00Z',
    customer: {
      display_name: 'John Doe',
      first_name: 'John',
      last_name: 'Doe',
    },
    line_items: [
      { description: 'Widget A', quantity: 2, unit_price: 10.0, line_total: 20.0 },
      { description: 'Widget B', quantity: 1, unit_price: 5.5, line_total: 5.5 },
    ],
    subtotal: 25.5,
    gst_amount: 3.83,
    discount_amount: 0,
    total: 29.33,
    amount_paid: 29.33,
    balance_due: 0,
    payments: [{ method: 'Cash', amount: 29.33 }],
    notes_customer: 'Thanks for shopping!',
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('invoiceToReceiptData', () => {
  it('maps org fields to receipt header', () => {
    const result = invoiceToReceiptData(makeInvoice());
    expect(result.orgName).toBe('Test Org');
    expect(result.orgAddress).toBe('123 Main St');
    expect(result.orgPhone).toBe('09 123 4567');
    expect(result.gstNumber).toBe('123-456-789');
  });

  it('defaults orgName to empty string when undefined', () => {
    const result = invoiceToReceiptData(makeInvoice({ org_name: undefined }));
    expect(result.orgName).toBe('');
  });

  it('maps invoice_number to receiptNumber', () => {
    const result = invoiceToReceiptData(makeInvoice({ invoice_number: 'INV-042' }));
    expect(result.receiptNumber).toBe('INV-042');
  });

  it('uses DRAFT when invoice_number is null', () => {
    const result = invoiceToReceiptData(makeInvoice({ invoice_number: null }));
    expect(result.receiptNumber).toBe('DRAFT');
  });

  it('formats issue_date as DD/MM/YYYY', () => {
    const result = invoiceToReceiptData(makeInvoice({ issue_date: '2025-03-15' }));
    expect(result.date).toBe('15/03/2025');
  });

  it('falls back to created_at when issue_date is null', () => {
    const result = invoiceToReceiptData(
      makeInvoice({ issue_date: null, created_at: '2025-01-20T08:00:00Z' }),
    );
    // Date will be formatted based on local timezone, just check DD/MM/YYYY pattern
    expect(result.date).toMatch(/^\d{2}\/\d{2}\/\d{4}$/);
  });

  it('uses display_name for customerName', () => {
    const result = invoiceToReceiptData(makeInvoice());
    expect(result.customerName).toBe('John Doe');
  });

  it('falls back to first_name + last_name when display_name is empty', () => {
    const result = invoiceToReceiptData(
      makeInvoice({
        customer: { display_name: '', first_name: 'Jane', last_name: 'Smith' },
      }),
    );
    expect(result.customerName).toBe('Jane Smith');
  });

  it('trims combined first_name + last_name', () => {
    const result = invoiceToReceiptData(
      makeInvoice({
        customer: { display_name: '', first_name: 'Jane', last_name: '' },
      }),
    );
    expect(result.customerName).toBe('Jane');
  });

  it('sets customerName to undefined when customer is null', () => {
    const result = invoiceToReceiptData(makeInvoice({ customer: null }));
    expect(result.customerName).toBeUndefined();
  });

  it('maps line items with first line of description only', () => {
    const result = invoiceToReceiptData(
      makeInvoice({
        line_items: [
          { description: 'Line one\nLine two', quantity: 3, unit_price: 7.0, line_total: 21.0 },
        ],
      }),
    );
    expect(result.items).toHaveLength(1);
    expect(result.items[0].name).toBe('Line one');
    expect(result.items[0].quantity).toBe(3);
    expect(result.items[0].unitPrice).toBe(7.0);
    expect(result.items[0].total).toBe(21.0);
  });

  it('maps financial totals', () => {
    const result = invoiceToReceiptData(makeInvoice());
    expect(result.subtotal).toBe(25.5);
    expect(result.taxAmount).toBe(3.83);
    expect(result.total).toBe(29.33);
    expect(result.amountPaid).toBe(29.33);
    expect(result.balanceDue).toBe(0);
    expect(result.taxLabel).toBe('GST (15%)');
  });

  it('sets discountAmount only when > 0', () => {
    const noDiscount = invoiceToReceiptData(makeInvoice({ discount_amount: 0 }));
    expect(noDiscount.discountAmount).toBeUndefined();

    const withDiscount = invoiceToReceiptData(makeInvoice({ discount_amount: 5.0 }));
    expect(withDiscount.discountAmount).toBe(5.0);
  });

  it('maps payments to paymentBreakdown and paymentMethod', () => {
    const result = invoiceToReceiptData(
      makeInvoice({
        payments: [
          { method: 'Cash', amount: 20.0 },
          { method: 'Card', amount: 9.33 },
        ],
      }),
    );
    expect(result.paymentMethod).toBe('Cash, Card');
    expect(result.paymentBreakdown).toEqual([
      { method: 'Cash', amount: 20.0 },
      { method: 'Card', amount: 9.33 },
    ]);
  });

  it('sets paymentMethod to "unpaid" when no payments', () => {
    const result = invoiceToReceiptData(makeInvoice({ payments: [] }));
    expect(result.paymentMethod).toBe('unpaid');
    expect(result.paymentBreakdown).toBeUndefined();
  });

  it('handles undefined payments array', () => {
    const result = invoiceToReceiptData(makeInvoice({ payments: undefined }));
    expect(result.paymentMethod).toBe('unpaid');
    expect(result.paymentBreakdown).toBeUndefined();
  });

  it('uses notes_customer as footer', () => {
    const result = invoiceToReceiptData(makeInvoice({ notes_customer: 'Custom footer' }));
    expect(result.footer).toBe('Custom footer');
  });

  it('defaults footer when notes_customer is null', () => {
    const result = invoiceToReceiptData(makeInvoice({ notes_customer: null }));
    expect(result.footer).toBe('Thank you for your business!');
  });

  it('defaults footer when notes_customer is empty string', () => {
    const result = invoiceToReceiptData(makeInvoice({ notes_customer: '' as any }));
    expect(result.footer).toBe('Thank you for your business!');
  });
});

describe('formatReceiptDate', () => {
  it('formats ISO date string as DD/MM/YYYY', () => {
    expect(formatReceiptDate('2025-12-25')).toBe('25/12/2025');
  });

  it('returns original string for invalid date', () => {
    expect(formatReceiptDate('not-a-date')).toBe('not-a-date');
  });
});
