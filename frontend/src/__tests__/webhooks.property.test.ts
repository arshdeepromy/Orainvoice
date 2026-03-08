import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  isValidWebhookUrl,
  getWebhookHealthStatus,
  type WebhookHealthStatus,
} from '../utils/webhookUtils'

// Feature: production-readiness-gaps, Property 10: Webhook URL must be HTTPS
// Feature: production-readiness-gaps, Property 11: Webhook health status indicator is deterministic
// **Validates: Requirements 6.3, 6.6, 6.7**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Arbitrary domain-like string */
const domainArb = fc
  .tuple(
    fc.string({ minLength: 1, maxLength: 20 }),
    fc.constantFrom('.com', '.org', '.net', '.io', '.co.nz'),
  )
  .map(([name, tld]) => name.replace(/\s/g, 'x') + tld)

/** Arbitrary path segment */
const pathArb = fc.string({ minLength: 1, maxLength: 30 }).map((s) => s.replace(/\s/g, ''))

/** Non-HTTPS scheme prefixes */
const nonHttpsSchemeArb = fc.constantFrom(
  'http://',
  'ftp://',
  'ws://',
  'wss://',
  'file://',
  'mailto:',
  '',
)

/** Non-negative integer for failure counts */
const failureCountArb = fc.nat({ max: 1000 })

/* ------------------------------------------------------------------ */
/*  Property 10: Webhook URL must be HTTPS                             */
/* ------------------------------------------------------------------ */

describe('Property 10: Webhook URL must be HTTPS', () => {
  it('URLs starting with https:// are valid', () => {
    fc.assert(
      fc.property(domainArb, pathArb, (domain, path) => {
        const url = `https://${domain}/${path}`
        expect(isValidWebhookUrl(url)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('URLs with non-HTTPS schemes are invalid', () => {
    fc.assert(
      fc.property(nonHttpsSchemeArb, domainArb, pathArb, (scheme, domain, path) => {
        const url = `${scheme}${domain}/${path}`
        expect(isValidWebhookUrl(url)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('random strings without https:// prefix are invalid', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 0, maxLength: 200 }).filter((s) => !s.startsWith('https://')),
        (url) => {
          expect(isValidWebhookUrl(url)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('empty string is invalid', () => {
    expect(isValidWebhookUrl('')).toBe(false)
  })

  it('https:// alone (no host) is accepted by startsWith check', () => {
    expect(isValidWebhookUrl('https://')).toBe(true)
  })
})

/* ------------------------------------------------------------------ */
/*  Property 11: Webhook health status indicator is deterministic      */
/* ------------------------------------------------------------------ */

describe('Property 11: Webhook health status indicator is deterministic', () => {
  it('disabled webhooks always return disabled regardless of failure count', () => {
    fc.assert(
      fc.property(failureCountArb, (failures) => {
        expect(getWebhookHealthStatus(failures, false)).toBe('disabled')
      }),
      { numRuns: 100 },
    )
  })

  it('enabled webhook with 0 failures is healthy', () => {
    expect(getWebhookHealthStatus(0, true)).toBe('healthy')
  })

  it('enabled webhook with 1-4 failures is degraded', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 4 }), (failures) => {
        expect(getWebhookHealthStatus(failures, true)).toBe('degraded')
      }),
      { numRuns: 100 },
    )
  })

  it('enabled webhook with 5+ failures is failing', () => {
    fc.assert(
      fc.property(fc.integer({ min: 5, max: 1000 }), (failures) => {
        expect(getWebhookHealthStatus(failures, true)).toBe('failing')
      }),
      { numRuns: 100 },
    )
  })

  it('same inputs always produce the same output (determinism)', () => {
    fc.assert(
      fc.property(failureCountArb, fc.boolean(), (failures, isEnabled) => {
        const result1 = getWebhookHealthStatus(failures, isEnabled)
        const result2 = getWebhookHealthStatus(failures, isEnabled)
        expect(result1).toBe(result2)
      }),
      { numRuns: 100 },
    )
  })

  it('result is always one of the four valid statuses', () => {
    const validStatuses: WebhookHealthStatus[] = ['healthy', 'degraded', 'failing', 'disabled']
    fc.assert(
      fc.property(failureCountArb, fc.boolean(), (failures, isEnabled) => {
        const result = getWebhookHealthStatus(failures, isEnabled)
        expect(validStatuses).toContain(result)
      }),
      { numRuns: 100 },
    )
  })
})
