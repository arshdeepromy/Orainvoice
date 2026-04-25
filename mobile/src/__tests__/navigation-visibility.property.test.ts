import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  isNavigationItemVisible,
  filterNavigationItems,
  TAB_CONFIGS,
} from '@/navigation/TabConfig'
import { MORE_MENU_ITEMS } from '@/screens/more/MoreMenuScreen'
import type { UserRole } from '@shared/types/auth'

/**
 * **Validates: Requirements 5.2, 5.3, 5.4, 5.5, 6.3, 28.2**
 *
 * Property 1: Navigation visibility respects module, trade family, and role filters
 *
 * For any combination of enabled modules, trade family, and user role, the set
 * of visible navigation items SHALL be exactly those items whose required module
 * is in the enabled set (or has no module requirement), whose required trade
 * family matches the current trade family (or has no trade family requirement),
 * and whose allowed roles include the current user role (or has no role restriction).
 */

// ---------------------------------------------------------------------------
// Generators
// ---------------------------------------------------------------------------

const ALL_ROLES: UserRole[] = ['owner', 'admin', 'manager', 'salesperson', 'technician', 'kiosk']

/** Collect all unique module slugs referenced by tabs and More menu items. */
const ALL_MODULE_SLUGS: string[] = [
  ...new Set(
    [...TAB_CONFIGS, ...MORE_MENU_ITEMS]
      .map((item) => item.moduleSlug)
      .filter((slug): slug is string => slug !== null && slug !== '*'),
  ),
]

/** Collect all unique trade families referenced by navigation items. */
const ALL_TRADE_FAMILIES: string[] = [
  ...new Set(
    [...TAB_CONFIGS, ...MORE_MENU_ITEMS]
      .map((item) => ('tradeFamily' in item ? item.tradeFamily : null))
      .filter((tf): tf is string => tf !== null),
  ),
  'electrical',
  'plumbing',
  'construction',
  'hospitality',
]

/** Arbitrary for a random subset of enabled modules. */
const enabledModulesArb = fc.subarray(ALL_MODULE_SLUGS, { minLength: 0 })

/** Arbitrary for a random trade family (including null for no trade family). */
const tradeFamilyArb = fc.oneof(
  fc.constant(null as string | null),
  fc.constantFrom(...ALL_TRADE_FAMILIES),
)

/** Arbitrary for a random user role. */
const userRoleArb = fc.constantFrom(...ALL_ROLES)

// ---------------------------------------------------------------------------
// Combine all navigation items for testing
// ---------------------------------------------------------------------------

interface NavItem {
  id: string
  moduleSlug: string | null
  tradeFamily: string | null
  allowedRoles: UserRole[]
}

const ALL_NAV_ITEMS: NavItem[] = [
  ...TAB_CONFIGS.map((t) => ({
    id: t.id,
    moduleSlug: t.moduleSlug,
    tradeFamily: t.tradeFamily,
    allowedRoles: t.allowedRoles,
  })),
  ...MORE_MENU_ITEMS.map((m) => ({
    id: m.id,
    moduleSlug: m.moduleSlug === '*' ? null : m.moduleSlug,
    tradeFamily: m.tradeFamily ?? null,
    allowedRoles: m.roles ?? [],
  })),
]

// ---------------------------------------------------------------------------
// Property tests
// ---------------------------------------------------------------------------

describe('Navigation visibility filtering', () => {
  it('Property 1: visible items match exactly the expected set for any module/tradeFamily/role combination', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        tradeFamilyArb,
        userRoleArb,
        (enabledModules, currentTradeFamily, userRole) => {
          // Compute the expected visible set manually
          const expectedVisible = ALL_NAV_ITEMS.filter((item) => {
            // Module gate
            if (item.moduleSlug !== null && !enabledModules.includes(item.moduleSlug)) {
              return false
            }
            // Trade family gate
            if (item.tradeFamily !== null && item.tradeFamily !== currentTradeFamily) {
              return false
            }
            // Role gate
            if (item.allowedRoles.length > 0 && !item.allowedRoles.includes(userRole)) {
              return false
            }
            return true
          })

          // Compute the actual visible set using the production function
          const actualVisible = ALL_NAV_ITEMS.filter((item) =>
            isNavigationItemVisible(item, enabledModules, currentTradeFamily, userRole),
          )

          // The sets must be exactly equal
          const expectedIds = expectedVisible.map((i) => i.id).sort()
          const actualIds = actualVisible.map((i) => i.id).sort()

          expect(actualIds).toEqual(expectedIds)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 1a: filterNavigationItems returns the same set as individual isNavigationItemVisible calls', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        tradeFamilyArb,
        userRoleArb,
        (enabledModules, currentTradeFamily, userRole) => {
          // Use filterNavigationItems (batch)
          const batchResult = filterNavigationItems(
            ALL_NAV_ITEMS,
            enabledModules,
            currentTradeFamily,
            userRole,
          )

          // Use isNavigationItemVisible (individual)
          const individualResult = ALL_NAV_ITEMS.filter((item) =>
            isNavigationItemVisible(item, enabledModules, currentTradeFamily, userRole),
          )

          expect(batchResult).toEqual(individualResult)
        },
      ),
      { numRuns: 200 },
    )
  })

  it('Property 1b: items with no gates (null module, null tradeFamily, empty roles) are always visible', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        tradeFamilyArb,
        userRoleArb,
        (enabledModules, currentTradeFamily, userRole) => {
          const ungatedItems = ALL_NAV_ITEMS.filter(
            (item) =>
              item.moduleSlug === null &&
              item.tradeFamily === null &&
              item.allowedRoles.length === 0,
          )

          for (const item of ungatedItems) {
            expect(
              isNavigationItemVisible(item, enabledModules, currentTradeFamily, userRole),
            ).toBe(true)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 1c: disabling a required module hides the item', () => {
    fc.assert(
      fc.property(
        tradeFamilyArb,
        userRoleArb,
        (currentTradeFamily, userRole) => {
          const moduleGatedItems = ALL_NAV_ITEMS.filter(
            (item) => item.moduleSlug !== null,
          )

          for (const item of moduleGatedItems) {
            // Provide an empty enabled modules list — module-gated items should be hidden
            const visible = isNavigationItemVisible(
              item,
              [],
              currentTradeFamily,
              userRole,
            )
            expect(visible).toBe(false)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 1d: trade family mismatch hides the item', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        userRoleArb,
        (enabledModules, userRole) => {
          const tradeFamilyGatedItems = ALL_NAV_ITEMS.filter(
            (item) => item.tradeFamily !== null,
          )

          for (const item of tradeFamilyGatedItems) {
            // Use a trade family that doesn't match
            const mismatchedFamily = item.tradeFamily === 'electrical' ? 'plumbing' : 'electrical'
            const visible = isNavigationItemVisible(
              item,
              enabledModules,
              mismatchedFamily,
              userRole,
            )
            expect(visible).toBe(false)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 1e: role restriction hides item from non-allowed roles', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        tradeFamilyArb,
        (enabledModules, currentTradeFamily) => {
          const roleGatedItems = ALL_NAV_ITEMS.filter(
            (item) => item.allowedRoles.length > 0,
          )

          for (const item of roleGatedItems) {
            // Find a role NOT in the allowed list
            const disallowedRole = ALL_ROLES.find(
              (r) => !item.allowedRoles.includes(r),
            )
            if (disallowedRole) {
              const visible = isNavigationItemVisible(
                item,
                enabledModules,
                currentTradeFamily,
                disallowedRole,
              )
              expect(visible).toBe(false)
            }
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
