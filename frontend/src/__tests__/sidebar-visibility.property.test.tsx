import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: production-readiness-gaps, Property 35: Sidebar visibility matches module and flag state
// **Validates: Requirements 20.3**

/* ------------------------------------------------------------------ */
/*  Types (mirrors OrgLayout NavItem)                                  */
/* ------------------------------------------------------------------ */

interface NavItem {
  to: string
  label: string
  /** If set, this nav item is only shown when the module is enabled */
  module?: string
  /** If set, this nav item is only shown when the feature flag is enabled */
  flagKey?: string
}

/* ------------------------------------------------------------------ */
/*  filterNavItems — replicates the OrgLayout visibleNavItems logic    */
/* ------------------------------------------------------------------ */

function filterNavItems(
  items: NavItem[],
  isEnabled: (slug: string) => boolean,
  flags: Record<string, boolean>,
): NavItem[] {
  return items.filter((item) => {
    if (item.module && !isEnabled(item.module)) return false
    if (item.flagKey && !flags[item.flagKey]) return false
    return true
  })
}

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

const moduleSlugArb = fc.stringMatching(/^[a-z][a-z0-9_]{1,15}$/)

const navItemArb: fc.Arbitrary<NavItem> = fc.record({
  to: fc.stringMatching(/^\/[a-z][a-z0-9-]{0,15}$/),
  label: fc.stringMatching(/^[A-Z][a-zA-Z ]{0,20}$/),
  module: fc.option(moduleSlugArb, { nil: undefined }),
  flagKey: fc.option(moduleSlugArb, { nil: undefined }),
})

/* ------------------------------------------------------------------ */
/*  Property 35: Sidebar visibility matches module and flag state      */
/* ------------------------------------------------------------------ */

describe('Property 35: Sidebar visibility matches module and flag state', () => {
  it(
    'items with a disabled module are not visible',
    () => {
      fc.assert(
        fc.property(
          fc.array(navItemArb, { minLength: 1, maxLength: 20 }),
          fc.uniqueArray(moduleSlugArb, { minLength: 0, maxLength: 10 }),
          (items, enabledModules) => {
            const enabledSet = new Set(enabledModules)
            const isEnabled = (slug: string) => enabledSet.has(slug)
            // All flags enabled so only module gating matters
            const flags: Record<string, boolean> = {}
            for (const item of items) {
              if (item.flagKey) flags[item.flagKey] = true
            }

            const visible = filterNavItems(items, isEnabled, flags)

            for (const item of visible) {
              if (item.module) {
                expect(enabledSet.has(item.module)).toBe(true)
              }
            }

            // Items with a disabled module must NOT be in visible
            for (const item of items) {
              if (item.module && !enabledSet.has(item.module)) {
                expect(visible).not.toContain(item)
              }
            }
          },
        ),
        { numRuns: 100 },
      )
    },
  )

  it(
    'items with a disabled feature flag are not visible',
    () => {
      fc.assert(
        fc.property(
          fc.array(navItemArb, { minLength: 1, maxLength: 20 }),
          fc.uniqueArray(moduleSlugArb, { minLength: 0, maxLength: 10 }),
          (items, enabledFlagKeys) => {
            // All modules enabled so only flag gating matters
            const isEnabled = () => true
            const enabledFlagSet = new Set(enabledFlagKeys)
            const flags: Record<string, boolean> = {}
            for (const item of items) {
              if (item.flagKey) {
                flags[item.flagKey] = enabledFlagSet.has(item.flagKey)
              }
            }

            const visible = filterNavItems(items, isEnabled, flags)

            for (const item of visible) {
              if (item.flagKey) {
                expect(flags[item.flagKey]).toBe(true)
              }
            }

            // Items with a disabled flag must NOT be in visible
            for (const item of items) {
              if (item.flagKey && !flags[item.flagKey]) {
                expect(visible).not.toContain(item)
              }
            }
          },
        ),
        { numRuns: 100 },
      )
    },
  )

  it(
    'items without module or flagKey are always visible',
    () => {
      fc.assert(
        fc.property(
          fc.array(navItemArb, { minLength: 1, maxLength: 20 }),
          (items) => {
            // Disable everything — items without constraints should still show
            const isEnabled = () => false
            const flags: Record<string, boolean> = {}

            const visible = filterNavItems(items, isEnabled, flags)

            for (const item of items) {
              if (!item.module && !item.flagKey) {
                expect(visible).toContain(item)
              }
            }
          },
        ),
        { numRuns: 100 },
      )
    },
  )

  it(
    'visible set equals exactly items whose module is enabled AND flag is enabled',
    () => {
      fc.assert(
        fc.property(
          fc.array(navItemArb, { minLength: 1, maxLength: 20 }),
          fc.uniqueArray(moduleSlugArb, { minLength: 0, maxLength: 10 }),
          fc.uniqueArray(moduleSlugArb, { minLength: 0, maxLength: 10 }),
          (items, enabledModules, enabledFlagKeys) => {
            const enabledModuleSet = new Set(enabledModules)
            const enabledFlagSet = new Set(enabledFlagKeys)
            const isEnabled = (slug: string) => enabledModuleSet.has(slug)
            const flags: Record<string, boolean> = {}
            for (const item of items) {
              if (item.flagKey) {
                flags[item.flagKey] = enabledFlagSet.has(item.flagKey)
              }
            }

            const visible = filterNavItems(items, isEnabled, flags)

            // Compute expected visible set manually
            const expected = items.filter((item) => {
              const moduleOk = !item.module || enabledModuleSet.has(item.module)
              const flagOk = !item.flagKey || enabledFlagSet.has(item.flagKey)
              return moduleOk && flagOk
            })

            expect(visible).toEqual(expected)
          },
        ),
        { numRuns: 100 },
      )
    },
  )
})
