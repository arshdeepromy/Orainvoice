// Feature: mobile-konsta-redesign, Property 2: Navigation item filtering matches sidebar logic
// **Validates: Requirements 5.2, 5.4, 5.5, 5.6, 55.2, 55.4, 55.5**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  filterNavigationItems,
  isNavigationItemVisible,
} from '@/navigation/TabConfig'
import type { UserRole } from '@shared/types/auth'

/**
 * Property 2: Navigation item filtering matches sidebar logic.
 *
 * For any combination of enabled module slugs, trade family (including null),
 * user role, and set of navigation items (each with moduleSlug, tradeFamily,
 * and allowedRoles), the filterNavigationItems function SHALL return only items
 * where:
 * (a) the item's moduleSlug is null OR is in the enabled set, AND
 * (b) the item's tradeFamily is null OR matches the current trade family, AND
 * (c) the item's allowedRoles is empty OR contains the user's role.
 * No other items shall be included or excluded.
 */
describe('Property 2: Navigation item filtering', () => {
  // Arbitraries
  const allModuleSlugs = [
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
  ]

  const allTradeFamilies = [
    'automotive-transport',
    'building-construction',
    'food-hospitality',
    'general-trade',
  ]

  const allRoles: UserRole[] = ['owner', 'admin', 'manager', 'salesperson', 'technician', 'kiosk']

  const enabledModulesArb = fc.subarray(allModuleSlugs, { minLength: 0 })

  const tradeFamilyArb = fc.oneof(
    fc.constant(null as string | null),
    fc.constantFrom(...allTradeFamilies),
  )

  const userRoleArb = fc.constantFrom(...allRoles)

  const navItemArb = fc.record({
    id: fc.uuid(),
    label: fc.string({ minLength: 1, maxLength: 20 }),
    moduleSlug: fc.oneof(
      fc.constant(null as string | null),
      fc.constantFrom(...allModuleSlugs),
    ),
    tradeFamily: fc.oneof(
      fc.constant(null as string | null),
      fc.constantFrom(...allTradeFamilies),
    ),
    allowedRoles: fc.subarray(allRoles, { minLength: 0 }),
  })

  const navItemsArb = fc.array(navItemArb, { minLength: 0, maxLength: 20 })

  it('only includes items that pass all three gates', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        tradeFamilyArb,
        userRoleArb,
        navItemsArb,
        (enabledModules, tradeFamily, userRole, items) => {
          const result = filterNavigationItems(
            items,
            enabledModules,
            tradeFamily,
            userRole,
          )

          for (const item of result) {
            // Module gate
            if (item.moduleSlug !== null) {
              expect(enabledModules).toContain(item.moduleSlug)
            }
            // Trade family gate
            if (item.tradeFamily !== null) {
              expect(item.tradeFamily).toBe(tradeFamily)
            }
            // Role gate
            if (item.allowedRoles.length > 0) {
              expect(item.allowedRoles).toContain(userRole)
            }
          }
        },
      ),
      { numRuns: 200 },
    )
  })

  it('does not exclude items that should pass all gates', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        tradeFamilyArb,
        userRoleArb,
        navItemsArb,
        (enabledModules, tradeFamily, userRole, items) => {
          const result = filterNavigationItems(
            items,
            enabledModules,
            tradeFamily,
            userRole,
          )

          const resultIds = new Set(result.map((r) => r.id))

          for (const item of items) {
            const moduleOk =
              item.moduleSlug === null ||
              enabledModules.includes(item.moduleSlug)
            const tradeOk =
              item.tradeFamily === null || item.tradeFamily === tradeFamily
            const roleOk =
              item.allowedRoles.length === 0 ||
              item.allowedRoles.includes(userRole)

            if (moduleOk && tradeOk && roleOk) {
              expect(resultIds.has(item.id)).toBe(true)
            }
          }
        },
      ),
      { numRuns: 200 },
    )
  })

  it('isNavigationItemVisible is consistent with filterNavigationItems', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        tradeFamilyArb,
        userRoleArb,
        navItemsArb,
        (enabledModules, tradeFamily, userRole, items) => {
          const filtered = filterNavigationItems(
            items,
            enabledModules,
            tradeFamily,
            userRole,
          )

          for (const item of items) {
            const visible = isNavigationItemVisible(
              item,
              enabledModules,
              tradeFamily,
              userRole,
            )
            const inFiltered = filtered.some((f) => f.id === item.id)
            expect(visible).toBe(inFiltered)
          }
        },
      ),
      { numRuns: 200 },
    )
  })
})
