/**
 * Invoices barrel (Task 20 port of frontend/src/pages/invoices/index.ts).
 *
 * Exports the ported invoice pages. RecurringInvoices is intentionally omitted
 * here — it is owned by a later phase (recurring schedules) and has not been
 * ported into frontend-v2 yet; it will be added to this barrel when ported.
 */
export { default as InvoiceCreate } from './InvoiceCreate'
export { default as InvoiceDetail } from './InvoiceDetail'
export { default as InvoiceList } from './InvoiceList'
