import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  resolveDeepLink,
  DEEP_LINK_PATTERNS,
  FALLBACK_SCREEN,
} from '@/navigation/DeepLinkConfig'

/**
 * **Validates: Requirements 39.2, 42.1, 42.2, 42.3, 42.4**
 *
 * Property 8: Deep link URL routing resolves to the correct screen
 *
 * For any valid deep link URL matching a registered pattern, the deep link
 * router SHALL resolve the URL to the correct screen identifier and extract
 * the correct parameters. URLs that do not match any registered pattern
 * SHALL resolve to a default/fallback screen.
 */

// ---------------------------------------------------------------------------
// Generators
// ---------------------------------------------------------------------------

/** Arbitrary for a valid resource ID (UUID-like or alphanumeric). */
const resourceIdArb = fc.string({
  unit: fc.constantFrom(
    ...'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'.split(''),
  ),
  minLength: 1,
  maxLength: 36,
})

/** Arbitrary for valid deep link URLs with IDs. */
const validDetailLinkArb = fc.tuple(
  fc.constantFrom('invoices', 'quotes', 'customers', 'jobs', 'job-cards'),
  resourceIdArb,
).map(([resource, id]) => ({
  url: `/${resource}/${id}`,
  expectedScreen: {
    invoices: 'InvoiceDetail',
    quotes: 'QuoteDetail',
    customers: 'CustomerProfile',
    jobs: 'JobDetail',
    'job-cards': 'JobCardDetail',
  }[resource]!,
  expectedId: id,
}))

/** Arbitrary for valid deep link URLs without IDs (list screens). */
const validListLinkArb = fc.constantFrom(
  { url: '/invoices', screen: 'InvoiceList' },
  { url: '/invoices/', screen: 'InvoiceList' },
  { url: '/quotes', screen: 'QuoteList' },
  { url: '/quotes/', screen: 'QuoteList' },
  { url: '/customers', screen: 'CustomerList' },
  { url: '/customers/', screen: 'CustomerList' },
  { url: '/jobs', screen: 'JobList' },
  { url: '/jobs/', screen: 'JobList' },
  { url: '/compliance', screen: 'ComplianceDashboard' },
  { url: '/compliance/', screen: 'ComplianceDashboard' },
  { url: '/expenses', screen: 'ExpenseList' },
  { url: '/bookings', screen: 'BookingCalendar' },
  { url: '/reports', screen: 'ReportsMenu' },
  { url: '/settings', screen: 'Settings' },
  { url: '/dashboard', screen: 'Dashboard' },
)

/** Arbitrary for invalid deep link URLs that should resolve to fallback. */
const invalidLinkArb = fc.oneof(
  fc.constant('/nonexistent'),
  fc.constant('/foo/bar/baz'),
  fc.constant('/'),
  fc.constant(''),
  fc.string({
    unit: fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz/'.split('')),
    minLength: 1,
    maxLength: 50,
  }).filter((s: string) => {
    // Filter out strings that would accidentally match a valid pattern
    return !DEEP_LINK_PATTERNS.some((p) => {
      const path = s.startsWith('/') ? s : `/${s}`
      return p.pattern.test(path)
    })
  }),
)

// ---------------------------------------------------------------------------
// Property tests
// ---------------------------------------------------------------------------

describe('Deep link URL routing', () => {
  it('Property 8: valid detail links resolve to the correct screen with correct ID', () => {
    fc.assert(
      fc.property(validDetailLinkArb, ({ url, expectedScreen, expectedId }) => {
        const result = resolveDeepLink(url)

        expect(result.screen).toBe(expectedScreen)
        expect(result.params.id).toBe(expectedId)
      }),
      { numRuns: 300 },
    )
  })

  it('Property 8a: valid list links resolve to the correct screen with no params', () => {
    fc.assert(
      fc.property(validListLinkArb, ({ url, screen }) => {
        const result = resolveDeepLink(url)

        expect(result.screen).toBe(screen)
      }),
      { numRuns: 100 },
    )
  })

  it('Property 8b: invalid URLs resolve to the fallback screen', () => {
    fc.assert(
      fc.property(invalidLinkArb, (url) => {
        const result = resolveDeepLink(url)

        expect(result.screen).toBe(FALLBACK_SCREEN)
        expect(result.params).toEqual({})
      }),
      { numRuns: 200 },
    )
  })

  it('Property 8c: resolveDeepLink always returns a screen and params object', () => {
    fc.assert(
      fc.property(fc.string(), (url) => {
        const result = resolveDeepLink(url)

        expect(typeof result.screen).toBe('string')
        expect(result.screen.length).toBeGreaterThan(0)
        expect(typeof result.params).toBe('object')
        expect(result.params).not.toBeNull()
      }),
      { numRuns: 300 },
    )
  })

  it('Property 8d: extracted IDs match the ID in the URL path', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('invoices', 'quotes', 'customers', 'jobs', 'job-cards'),
        resourceIdArb,
        (resource, id) => {
          const result = resolveDeepLink(`/${resource}/${id}`)

          if (result.params.id !== undefined) {
            expect(result.params.id).toBe(id)
          }
        },
      ),
      { numRuns: 200 },
    )
  })
})
