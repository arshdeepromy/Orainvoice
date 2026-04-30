// Feature: mobile-konsta-redesign, Property 1: Tab bar always shows core tabs and resolves dynamic 4th tab
// **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { buildTabs, resolveFourthTab } from '@/navigation/TabConfig'

/**
 * Property 1: Tab bar always shows core tabs and resolves dynamic 4th tab.
 *
 * For any set of enabled module slugs (including the empty set), the bottom
 * tab bar resolution function SHALL return exactly 5 tabs where:
 * (a) Home, Invoices, Customers, and More are always present, and
 * (b) the 4th tab is Jobs if `jobs` is enabled, else Quotes if `quotes` is
 *     enabled, else Bookings if `bookings` is enabled, else Reports as fallback.
 */
describe('Property 1: Tab bar resolution', () => {
  // Arbitrary for a random set of module slugs
  const moduleSlugArb = fc.subarray(
    [
      'jobs',
      'quotes',
      'bookings',
      'inventory',
      'staff',
      'expenses',
      'time_tracking',
      'scheduling',
      'pos',
      'recurring_invoices',
      'purchase_orders',
      'progress_claims',
      'variations',
      'retentions',
      'tables',
      'kitchen_display',
      'assets',
      'compliance_docs',
      'sms',
      'vehicles',
      'projects',
      'franchise',
    ],
    { minLength: 0 },
  )

  it('always returns exactly 5 tabs', () => {
    fc.assert(
      fc.property(moduleSlugArb, (enabledModules) => {
        const tabs = buildTabs(enabledModules)
        expect(tabs).toHaveLength(5)
      }),
      { numRuns: 200 },
    )
  })

  it('always includes Home, Invoices, Customers, and More tabs', () => {
    fc.assert(
      fc.property(moduleSlugArb, (enabledModules) => {
        const tabs = buildTabs(enabledModules)
        const ids = tabs.map((t) => t.id)

        expect(ids).toContain('home')
        expect(ids).toContain('invoices')
        expect(ids).toContain('customers')
        expect(ids).toContain('more')
      }),
      { numRuns: 200 },
    )
  })

  it('resolves 4th tab following priority: Jobs > Quotes > Bookings > Reports', () => {
    fc.assert(
      fc.property(moduleSlugArb, (enabledModules) => {
        const fourthTab = resolveFourthTab(enabledModules)

        if (enabledModules.includes('jobs')) {
          expect(fourthTab.id).toBe('jobs')
        } else if (enabledModules.includes('quotes')) {
          expect(fourthTab.id).toBe('quotes')
        } else if (enabledModules.includes('bookings')) {
          expect(fourthTab.id).toBe('bookings')
        } else {
          expect(fourthTab.id).toBe('reports')
        }
      }),
      { numRuns: 200 },
    )
  })

  it('4th tab in buildTabs matches resolveFourthTab', () => {
    fc.assert(
      fc.property(moduleSlugArb, (enabledModules) => {
        const tabs = buildTabs(enabledModules)
        const fourthTab = resolveFourthTab(enabledModules)

        // The 4th tab (index 3) should match the resolved tab
        expect(tabs[3].id).toBe(fourthTab.id)
      }),
      { numRuns: 200 },
    )
  })

  it('core tabs are always at fixed positions', () => {
    fc.assert(
      fc.property(moduleSlugArb, (enabledModules) => {
        const tabs = buildTabs(enabledModules)

        expect(tabs[0].id).toBe('home')
        expect(tabs[1].id).toBe('invoices')
        expect(tabs[2].id).toBe('customers')
        // tabs[3] is dynamic
        expect(tabs[4].id).toBe('more')
      }),
      { numRuns: 200 },
    )
  })
})
