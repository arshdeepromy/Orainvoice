/**
 * Maps InvoiceDetail data to the ReceiptData structure consumed by buildReceipt().
 *
 * Pure mapping function — no side effects, no API calls.
 */

import type { ReceiptData, ReceiptLineItem } from './escpos';

export interface InvoiceForReceipt {
  org_name?: string;
  org_address?: string;
  org_phone?: string;
  org_gst_number?: string;
  invoice_number: string | null;
  issue_date: string | null;
  created_at: string;
  customer?: {
    display_name?: string;
    first_name: string;
    last_name: string;
  } | null;
  line_items: Array<{
    description: string;
    quantity: number;
    unit_price: number;
    line_total: number;
  }>;
  subtotal: number;
  gst_amount: number;
  discount_amount: number;
  total: number;
  amount_paid: number;
  balance_due: number;
  payments?: Array<{
    method: string;
    amount: number;
  }>;
  notes_customer: string | null;
}

export function invoiceToReceiptData(invoice: InvoiceForReceipt): ReceiptData {
  const items: ReceiptLineItem[] = (invoice.line_items ?? []).map((li) => ({
    name: li.description?.split('\n')[0] ?? '',
    quantity: Number(li.quantity ?? 0),
    unitPrice: Number(li.unit_price ?? 0),
    total: Number(li.line_total ?? 0),
  }));

  const customerName = invoice.customer
    ? (invoice.customer.display_name ||
       `${invoice.customer.first_name} ${invoice.customer.last_name}`.trim())
    : undefined;

  const dateStr = formatReceiptDate(invoice.issue_date ?? invoice.created_at);

  // Summarise payment methods — show unique methods only, exclude refunds
  const payments = invoice.payments ?? [];
  const nonRefundPayments = payments.filter((p) => !(p as any).is_refund);
  const refundPayments = payments.filter((p) => (p as any).is_refund);
  const totalRefunded = refundPayments.reduce((sum, p) => sum + Number(p.amount ?? 0), 0);
  const uniqueMethods = [...new Set(nonRefundPayments.map((p) => p.method))];
  const paymentMethod = uniqueMethods.length > 0
    ? uniqueMethods.join(', ')
    : 'unpaid';

  return {
    orgName: invoice.org_name ?? '',
    orgAddress: invoice.org_address,
    orgPhone: invoice.org_phone,
    receiptNumber: invoice.invoice_number ?? 'DRAFT',
    date: dateStr,
    customerName,
    gstNumber: invoice.org_gst_number,
    items,
    subtotal: Number(invoice.subtotal ?? 0),
    taxLabel: 'GST (15%)',
    taxAmount: Number(invoice.gst_amount ?? 0),
    discountAmount: Number(invoice.discount_amount ?? 0) > 0 ? Number(invoice.discount_amount) : undefined,
    total: Number(invoice.total ?? 0),
    amountPaid: Number(invoice.amount_paid ?? 0),
    balanceDue: Number(invoice.balance_due ?? 0),
    totalRefunded: totalRefunded > 0 ? totalRefunded : undefined,
    paymentMethod,
    paymentBreakdown: nonRefundPayments.length > 1
      ? nonRefundPayments.map((p) => ({ method: p.method, amount: Number(p.amount ?? 0) }))
      : undefined,
    footer: invoice.notes_customer || 'Thank you for your business!',
  };
}

export function formatReceiptDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    return `${day}/${month}/${year}`;
  } catch {
    return dateStr;
  }
}
