import { describe, it, expect } from 'vitest';
import { buildReceipt, ReceiptData } from '../escpos';

/** Decode the ESC/POS byte buffer to extract printable text (ignoring control sequences). */
function extractText(bytes: Uint8Array): string {
  const decoder = new TextDecoder();
  return decoder.decode(bytes);
}

/** Check if a byte sequence appears in the buffer. */
function containsBytes(haystack: Uint8Array, needle: number[]): boolean {
  for (let i = 0; i <= haystack.length - needle.length; i++) {
    let match = true;
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) {
        match = false;
        break;
      }
    }
    if (match) return true;
  }
  return false;
}

const BOLD_ON = [0x1b, 0x45, 0x01];

function baseReceiptData(): ReceiptData {
  return {
    orgName: 'Test Org',
    orgAddress: '123 Main St',
    orgPhone: '555-1234',
    date: '01/01/2025',
    items: [{ name: 'Widget', quantity: 2, unitPrice: 10.0, total: 20.0 }],
    subtotal: 20.0,
    taxAmount: 3.0,
    total: 23.0,
    paymentMethod: 'cash',
  };
}

describe('buildReceipt — new optional fields', () => {
  it('renders GST number after org header when gstNumber is defined', () => {
    const data: ReceiptData = { ...baseReceiptData(), gstNumber: '123-456-789' };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).toContain('GST: 123-456-789');
  });

  it('does not render GST line when gstNumber is undefined', () => {
    const data: ReceiptData = { ...baseReceiptData() };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).not.toContain('GST:');
  });

  it('renders Customer line after date when customerName is defined', () => {
    const data: ReceiptData = { ...baseReceiptData(), customerName: 'Jane Doe' };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).toContain('Customer:');
    expect(text).toContain('Jane Doe');
  });

  it('does not render Customer line when customerName is undefined', () => {
    const data: ReceiptData = { ...baseReceiptData() };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).not.toContain('Customer:');
  });

  it('renders payment breakdown entries after payment method', () => {
    const data: ReceiptData = {
      ...baseReceiptData(),
      paymentBreakdown: [
        { method: 'Cash', amount: 15.0 },
        { method: 'Card', amount: 8.0 },
      ],
    };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).toContain('Cash:');
    expect(text).toContain('15.00');
    expect(text).toContain('Card:');
    expect(text).toContain('8.00');
  });

  it('does not render payment breakdown when paymentBreakdown is undefined', () => {
    const data: ReceiptData = { ...baseReceiptData() };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    // Only "Payment:" should appear, not individual method lines
    const paymentLines = text.split('\n').filter((l) => l.includes('Cash:'));
    expect(paymentLines).toHaveLength(0);
  });

  it('renders Amount Paid when amountPaid is defined', () => {
    const data: ReceiptData = { ...baseReceiptData(), amountPaid: 23.0 };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).toContain('Amount Paid:');
    expect(text).toContain('23.00');
  });

  it('does not render Amount Paid when amountPaid is undefined', () => {
    const data: ReceiptData = { ...baseReceiptData() };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).not.toContain('Amount Paid:');
  });

  it('renders bold BALANCE DUE when balanceDue > 0', () => {
    const data: ReceiptData = { ...baseReceiptData(), balanceDue: 5.5 };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).toContain('BALANCE DUE:');
    expect(text).toContain('5.50');
    // Verify bold-on command precedes BALANCE DUE text
    expect(containsBytes(bytes, BOLD_ON)).toBe(true);
  });

  it('does not render BALANCE DUE when balanceDue is 0', () => {
    const data: ReceiptData = { ...baseReceiptData(), balanceDue: 0 };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).not.toContain('BALANCE DUE:');
  });

  it('does not render BALANCE DUE when balanceDue is undefined', () => {
    const data: ReceiptData = { ...baseReceiptData() };
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);
    expect(text).not.toContain('BALANCE DUE:');
  });

  it('produces identical output when all new fields are undefined', () => {
    // Build with no new fields — should match the original behavior exactly
    const data: ReceiptData = baseReceiptData();
    const bytes = buildReceipt(data, 80);
    const text = extractText(bytes);

    // Should have the standard sections
    expect(text).toContain('Test Org');
    expect(text).toContain('123 Main St');
    expect(text).toContain('555-1234');
    expect(text).toContain('Date:');
    expect(text).toContain('Widget');
    expect(text).toContain('Subtotal:');
    expect(text).toContain('TOTAL:');
    expect(text).toContain('Payment:');
    expect(text).toContain('Thank you for your business!');

    // Should NOT have any new fields
    expect(text).not.toContain('GST:');
    expect(text).not.toContain('Customer:');
    expect(text).not.toContain('Amount Paid:');
    expect(text).not.toContain('BALANCE DUE:');
  });
});
