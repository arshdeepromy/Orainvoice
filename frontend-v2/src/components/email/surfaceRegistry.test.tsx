import { describe, it, expect } from 'vitest'
import { SURFACE_REGISTRY } from './surfaceRegistry'
import type { SurfaceConfig } from './types'

/**
 * surfaceRegistry unit tests (task 12.7, R21.4).
 *
 * The modal carries no per-surface branching — it reads
 * `SURFACE_REGISTRY[templateType]` for the Override_Send_Endpoint URL, HTTP
 * method, the v2-absolute-path flag, and the human-facing surface label. These
 * tests pin every one of the 10 template-type keys to its expected contract and
 * assert `buildSendUrl` produces the correct path (including the reminder types
 * that build from `opts.logId`).
 */

describe('SURFACE_REGISTRY — keys and contract', () => {
  it('declares exactly the 10 supported template types', () => {
    expect(Object.keys(SURFACE_REGISTRY).sort()).toEqual(
      [
        'cof_expiry_reminder',
        'customer_statement',
        'invoice_issued',
        'invoice_payment_link',
        'payment_received',
        'portal_link',
        'quote_sent',
        'registration_expiry_reminder',
        'service_due_reminder',
        'wof_expiry_reminder',
      ].sort(),
    )
  })

  it('is frozen so surfaces cannot be mutated at runtime', () => {
    expect(Object.isFrozen(SURFACE_REGISTRY)).toBe(true)
  })

  it('keys each row to its own templateType', () => {
    for (const [key, cfg] of Object.entries(SURFACE_REGISTRY)) {
      expect(cfg.templateType).toBe(key)
    }
  })

  // [templateType, entityType, method, apiV2, surfaceLabel, builtUrl]
  const cases: Array<
    [string, SurfaceConfig['entityType'], 'POST' | 'PUT', boolean, string, string]
  > = [
    ['invoice_issued', 'invoice', 'POST', false, 'Send Invoice', '/invoices/inv-1/email'],
    [
      'invoice_payment_link',
      'invoice',
      'POST',
      false,
      'Send Payment Link',
      '/payments/invoice/inv-1/send-payment-link',
    ],
    ['payment_received', 'invoice', 'POST', false, 'Send Receipt', '/invoices/inv-1/email-receipt'],
    ['quote_sent', 'quote', 'POST', false, 'Email Quote', '/quotes/inv-1/send'],
    [
      'customer_statement',
      'customer',
      'POST',
      true,
      'Send Statement',
      '/api/v2/reports/customer-statement/inv-1/email',
    ],
    [
      'portal_link',
      'customer',
      'POST',
      true,
      'Send Portal Link',
      '/api/v2/customers/inv-1/send-portal-link',
    ],
  ]

  it.each(cases)(
    '%s resolves to the expected URL / method / apiV2 / label',
    (templateType, entityType, method, apiV2, label, builtUrl) => {
      const cfg = SURFACE_REGISTRY[templateType]
      expect(cfg.entityType).toBe(entityType)
      expect(cfg.method).toBe(method)
      expect(cfg.apiV2).toBe(apiV2)
      expect(cfg.surfaceLabel).toBe(label)
      expect(cfg.buildSendUrl('inv-1')).toBe(builtUrl)
    },
  )
})

describe('SURFACE_REGISTRY — reminder resend surfaces', () => {
  const reminderKeys = [
    'wof_expiry_reminder',
    'cof_expiry_reminder',
    'registration_expiry_reminder',
    'service_due_reminder',
  ]

  it.each(reminderKeys)('%s is a v2 customer_vehicle resend surface', (key) => {
    const cfg = SURFACE_REGISTRY[key]
    expect(cfg.entityType).toBe('customer_vehicle')
    expect(cfg.method).toBe('POST')
    expect(cfg.apiV2).toBe(true)
    expect(cfg.surfaceLabel).toBe('Resend Reminder')
  })

  it.each(reminderKeys)('%s builds the resend URL from opts.logId, not the entity id', (key) => {
    const cfg = SURFACE_REGISTRY[key]
    expect(cfg.buildSendUrl('veh-9', { logId: 'log-42' })).toBe(
      '/api/v2/notifications/log/log-42/resend',
    )
  })
})
