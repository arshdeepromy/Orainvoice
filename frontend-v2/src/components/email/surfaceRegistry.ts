/**
 * Send Email Modal — surface registry.
 *
 * A frozen record keyed by `template_type`. The modal contains no per-surface
 * branching (R1.4); it reads `SURFACE_REGISTRY[templateType]` to learn the
 * Override_Send_Endpoint URL, HTTP method, whether the endpoint is a v2
 * absolute path, and the human-facing surface label.
 *
 * Adding a new surface in the future is limited to adding a row here, backend
 * support for the `template_type` in the preview endpoint, and override-field
 * acceptance on the send endpoint — no changes to the modal itself (R1.5).
 *
 * The four vehicle-reminder template types share the single notification-log
 * resend endpoint, built from `opts.logId` (R2.7).
 */

import type { SurfaceConfig } from './types'

export const SURFACE_REGISTRY: Readonly<Record<string, SurfaceConfig>> = Object.freeze({
  invoice_issued: {
    templateType: 'invoice_issued',
    entityType: 'invoice',
    buildSendUrl: (id) => `/invoices/${id}/email`,
    method: 'POST',
    apiV2: false,
    surfaceLabel: 'Send Invoice',
  },
  invoice_payment_link: {
    templateType: 'invoice_payment_link',
    entityType: 'invoice',
    buildSendUrl: (id) => `/payments/invoice/${id}/send-payment-link`,
    method: 'POST',
    apiV2: false,
    surfaceLabel: 'Send Payment Link',
  },
  payment_received: {
    templateType: 'payment_received',
    entityType: 'invoice',
    buildSendUrl: (id) => `/invoices/${id}/email-receipt`,
    method: 'POST',
    apiV2: false,
    surfaceLabel: 'Send Receipt',
  },
  quote_sent: {
    templateType: 'quote_sent',
    entityType: 'quote',
    buildSendUrl: (id) => `/quotes/${id}/send`,
    method: 'POST',
    apiV2: false,
    surfaceLabel: 'Email Quote',
  },
  customer_statement: {
    templateType: 'customer_statement',
    entityType: 'customer',
    buildSendUrl: (id) => `/api/v2/reports/customer-statement/${id}/email`,
    method: 'POST',
    apiV2: true,
    surfaceLabel: 'Send Statement',
  },
  portal_link: {
    templateType: 'portal_link',
    entityType: 'customer',
    buildSendUrl: (id) => `/api/v2/customers/${id}/send-portal-link`,
    method: 'POST',
    apiV2: true,
    surfaceLabel: 'Send Portal Link',
  },
  // wof/cof/registration/service reminders share the resend endpoint:
  wof_expiry_reminder: {
    templateType: 'wof_expiry_reminder',
    entityType: 'customer_vehicle',
    buildSendUrl: (_id, opts) => `/api/v2/notifications/log/${opts?.logId}/resend`,
    method: 'POST',
    apiV2: true,
    surfaceLabel: 'Resend Reminder',
  },
  cof_expiry_reminder: {
    templateType: 'cof_expiry_reminder',
    entityType: 'customer_vehicle',
    buildSendUrl: (_id, opts) => `/api/v2/notifications/log/${opts?.logId}/resend`,
    method: 'POST',
    apiV2: true,
    surfaceLabel: 'Resend Reminder',
  },
  registration_expiry_reminder: {
    templateType: 'registration_expiry_reminder',
    entityType: 'customer_vehicle',
    buildSendUrl: (_id, opts) => `/api/v2/notifications/log/${opts?.logId}/resend`,
    method: 'POST',
    apiV2: true,
    surfaceLabel: 'Resend Reminder',
  },
  service_due_reminder: {
    templateType: 'service_due_reminder',
    entityType: 'customer_vehicle',
    buildSendUrl: (_id, opts) => `/api/v2/notifications/log/${opts?.logId}/resend`,
    method: 'POST',
    apiV2: true,
    surfaceLabel: 'Resend Reminder',
  },
})
