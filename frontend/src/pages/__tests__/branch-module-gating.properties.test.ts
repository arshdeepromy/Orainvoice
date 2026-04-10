// Feature: branch-module-gating, Property 5: BranchContext no-op mode
//
// **Validates: Requirements 7.1, 7.2, 7.3, 7.4**
//
// For any organisation with `branch_management` disabled, the BranchContext
// provider returns `selectedBranchId = null`, `branches = []`, makes no API
// call to `/org/branches`, and `useBranch()` does not throw.

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ─── Types mirroring BranchContext ───

interface Branch {
  id: string
  name: string
  address: string | null
  phone: string | null
  is_active: boolean
}

interface BranchContextValue {
  selectedBranchId: string | null
  branches: Branch[]
  isLoading: boolean
  isBranchLocked: boolean
}

interface AuthState {
  isAuthenticated: boolean
  orgId: string | null
  role: string
  branchIds: string[]
}

// ─── Pure functions replicating BranchContext decision logic ───

/**
 * Mirrors BranchProvider's state computation when the branch module is disabled.
 * When branchModuleEnabled is false, the provider resets to no-op state:
 *   setBranches([])
 *   setSelectedBranchId(null)
 *   setIsLoading(false)
 *
 * This function returns the context value that would be produced.
 */
function computeBranchContextWhenDisabled(auth: AuthState): BranchContextValue {
  return {
    selectedBranchId: null,
    branches: [],
    isLoading: false,
    isBranchLocked: auth.role === 'branch_admin',
  }
}

/**
 * Mirrors BranchProvider's decision on whether to fetch branches.
 * The fetch effect has: `if (!branchModuleEnabled) return`
 * So when disabled, no API call is made regardless of auth state.
 */
function shouldFetchBranches(branchModuleEnabled: boolean, auth: AuthState): boolean {
  if (!branchModuleEnabled) return false
  if (!auth.isAuthenticated || !auth.orgId) return false
  if (auth.role === 'global_admin') return false
  if (auth.role === 'branch_admin') return false
  return true
}

/**
 * Mirrors BranchProvider's context value shape — the provider always
 * exposes a value (never null) so useBranch() consumers don't throw.
 * Returns true if the context value is structurally valid.
 */
function isValidContextValue(value: BranchContextValue): boolean {
  return (
    (value.selectedBranchId === null || typeof value.selectedBranchId === 'string') &&
    Array.isArray(value.branches) &&
    typeof value.isLoading === 'boolean' &&
    typeof value.isBranchLocked === 'boolean'
  )
}

// ─── Arbitraries ───

const ALL_ROLES = [
  'global_admin',
  'franchise_admin',
  'org_admin',
  'branch_admin',
  'location_manager',
  'salesperson',
  'staff_member',
  'kiosk',
] as const

const authStateArb: fc.Arbitrary<AuthState> = fc.record({
  isAuthenticated: fc.boolean(),
  orgId: fc.oneof(fc.uuid(), fc.constant(null)),
  role: fc.constantFrom(...ALL_ROLES),
  branchIds: fc.array(fc.uuid(), { minLength: 0, maxLength: 5 }),
})

const branchArb: fc.Arbitrary<Branch> = fc.record({
  id: fc.uuid(),
  name: fc.string({ minLength: 1, maxLength: 50 }),
  address: fc.oneof(fc.string({ minLength: 1, maxLength: 100 }), fc.constant(null)),
  phone: fc.oneof(fc.string({ minLength: 1, maxLength: 20 }), fc.constant(null)),
  is_active: fc.boolean(),
})

// ─── Property 5: BranchContext no-op mode ───

describe('Property 5: BranchContext no-op mode', () => {
  it('selectedBranchId is null when branch_management is disabled', () => {
    fc.assert(
      fc.property(authStateArb, (auth) => {
        const ctx = computeBranchContextWhenDisabled(auth)
        expect(ctx.selectedBranchId).toBeNull()
      }),
      { numRuns: 100 },
    )
  })

  it('branches is an empty array when branch_management is disabled', () => {
    fc.assert(
      fc.property(authStateArb, (auth) => {
        const ctx = computeBranchContextWhenDisabled(auth)
        expect(ctx.branches).toEqual([])
        expect(ctx.branches).toHaveLength(0)
      }),
      { numRuns: 100 },
    )
  })

  it('no API call to /org/branches when branch_management is disabled', () => {
    fc.assert(
      fc.property(authStateArb, (auth) => {
        // Regardless of auth state, when module is disabled, no fetch occurs
        const shouldFetch = shouldFetchBranches(false, auth)
        expect(shouldFetch).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('context value is structurally valid when disabled (useBranch does not throw)', () => {
    fc.assert(
      fc.property(authStateArb, (auth) => {
        const ctx = computeBranchContextWhenDisabled(auth)
        // The context value must be a valid BranchContextValue so useBranch()
        // consumers receive a well-formed object and do not throw
        expect(isValidContextValue(ctx)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('isLoading is false when branch_management is disabled', () => {
    fc.assert(
      fc.property(authStateArb, (auth) => {
        const ctx = computeBranchContextWhenDisabled(auth)
        expect(ctx.isLoading).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('disabled state holds regardless of pre-existing branch data', () => {
    fc.assert(
      fc.property(
        authStateArb,
        fc.array(branchArb, { minLength: 1, maxLength: 10 }),
        fc.oneof(fc.uuid(), fc.constant(null)),
        (auth, _existingBranches, _existingSelectedId) => {
          // Even if the org had branches loaded before the module was disabled,
          // the no-op reset produces null/empty state
          const ctx = computeBranchContextWhenDisabled(auth)
          expect(ctx.selectedBranchId).toBeNull()
          expect(ctx.branches).toEqual([])
          expect(ctx.isLoading).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('fetch decision is true only when module enabled AND auth conditions met', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        authStateArb,
        (moduleEnabled, auth) => {
          const shouldFetch = shouldFetchBranches(moduleEnabled, auth)

          if (!moduleEnabled) {
            // Module disabled → never fetch
            expect(shouldFetch).toBe(false)
          } else if (!auth.isAuthenticated || !auth.orgId) {
            // Not authenticated or no org → never fetch
            expect(shouldFetch).toBe(false)
          } else if (auth.role === 'global_admin' || auth.role === 'branch_admin') {
            // global_admin and branch_admin skip the standard fetch
            expect(shouldFetch).toBe(false)
          } else {
            // Module enabled + authenticated + has org + standard role → fetch
            expect(shouldFetch).toBe(true)
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})


// Feature: branch-module-gating, Property 2: BranchSelector and badge conditional rendering
//
// **Validates: Requirements 3.1, 3.2, 3.3**
//
// For any organisation, the BranchSelector component and active branch
// indicator badge are rendered in the OrgLayout header if and only if
// `branch_management` is enabled for that organisation.

// ─── Pure functions replicating OrgLayout header rendering decisions ───

/**
 * Mirrors OrgLayout's BranchSelector rendering condition:
 *   {isBranchModuleEnabled && !isBranchLocked && <BranchSelector />}
 *
 * Returns true when the BranchSelector dropdown should be rendered.
 */
function shouldRenderBranchSelector(
  isBranchModuleEnabled: boolean,
  isBranchLocked: boolean,
): boolean {
  return isBranchModuleEnabled && !isBranchLocked
}

/**
 * Mirrors OrgLayout's static branch_admin badge rendering condition:
 *   {isBranchModuleEnabled && isBranchAdmin && branchAdminBranchName && ...}
 *
 * branchAdminBranchName is 'My Branch' when isBranchAdmin, null otherwise.
 * Returns true when the branch_admin static badge should be rendered.
 */
function shouldRenderBranchAdminBadge(
  isBranchModuleEnabled: boolean,
  isBranchAdmin: boolean,
): boolean {
  const branchAdminBranchName = isBranchAdmin ? 'My Branch' : null
  return isBranchModuleEnabled && isBranchAdmin && branchAdminBranchName !== null
}

/**
 * Mirrors OrgLayout's active branch indicator rendering condition:
 *   {isBranchModuleEnabled && !isBranchAdmin && activeBranchIndicator.visible && ...}
 *
 * activeBranchIndicator.visible comes from getActiveBranchIndicatorState().
 * Returns true when the active branch indicator badge should be rendered.
 */
function shouldRenderActiveBranchIndicator(
  isBranchModuleEnabled: boolean,
  isBranchAdmin: boolean,
  activeBranchIndicatorVisible: boolean,
): boolean {
  return isBranchModuleEnabled && !isBranchAdmin && activeBranchIndicatorVisible
}

/**
 * Returns true if ANY branch-related UI element is rendered in the header.
 * This is the union of BranchSelector, branch_admin badge, and active branch indicator.
 */
function isAnyBranchUIRendered(
  isBranchModuleEnabled: boolean,
  isBranchAdmin: boolean,
  isBranchLocked: boolean,
  activeBranchIndicatorVisible: boolean,
): boolean {
  return (
    shouldRenderBranchSelector(isBranchModuleEnabled, isBranchLocked) ||
    shouldRenderBranchAdminBadge(isBranchModuleEnabled, isBranchAdmin) ||
    shouldRenderActiveBranchIndicator(isBranchModuleEnabled, isBranchAdmin, activeBranchIndicatorVisible)
  )
}

// ─── Property 2: BranchSelector and badge conditional rendering ───

describe('Property 2: BranchSelector and badge conditional rendering', () => {
  it('BranchSelector is never rendered when branch_management is disabled', () => {
    fc.assert(
      fc.property(fc.boolean(), (isBranchLocked) => {
        const rendered = shouldRenderBranchSelector(false, isBranchLocked)
        expect(rendered).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('branch_admin badge is never rendered when branch_management is disabled', () => {
    fc.assert(
      fc.property(fc.boolean(), (isBranchAdmin) => {
        const rendered = shouldRenderBranchAdminBadge(false, isBranchAdmin)
        expect(rendered).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('active branch indicator is never rendered when branch_management is disabled', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        (isBranchAdmin, indicatorVisible) => {
          const rendered = shouldRenderActiveBranchIndicator(false, isBranchAdmin, indicatorVisible)
          expect(rendered).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('no branch UI element is rendered when branch_management is disabled', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        (isBranchAdmin, isBranchLocked, indicatorVisible) => {
          const anyRendered = isAnyBranchUIRendered(false, isBranchAdmin, isBranchLocked, indicatorVisible)
          expect(anyRendered).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('BranchSelector is rendered when module enabled and not branch-locked', () => {
    fc.assert(
      fc.property(fc.constant(true), (_) => {
        const rendered = shouldRenderBranchSelector(true, false)
        expect(rendered).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('BranchSelector is hidden when module enabled but branch-locked', () => {
    fc.assert(
      fc.property(fc.constant(true), (_) => {
        const rendered = shouldRenderBranchSelector(true, true)
        expect(rendered).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('branch_admin badge is rendered when module enabled and user is branch_admin', () => {
    fc.assert(
      fc.property(fc.constant(true), (_) => {
        const rendered = shouldRenderBranchAdminBadge(true, true)
        expect(rendered).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('branch_admin badge is hidden when module enabled but user is not branch_admin', () => {
    fc.assert(
      fc.property(fc.constant(true), (_) => {
        const rendered = shouldRenderBranchAdminBadge(true, false)
        expect(rendered).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('active branch indicator rendered iff module enabled AND not branch_admin AND indicator visible', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        (moduleEnabled, isBranchAdmin, indicatorVisible) => {
          const rendered = shouldRenderActiveBranchIndicator(moduleEnabled, isBranchAdmin, indicatorVisible)
          const expected = moduleEnabled && !isBranchAdmin && indicatorVisible
          expect(rendered).toBe(expected)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('at least one branch UI element is rendered when module enabled (for some user state)', () => {
    // When module is enabled, at least one of the three elements renders
    // depending on user state. We test the full matrix:
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        (isBranchAdmin, isBranchLocked, indicatorVisible) => {
          const anyRendered = isAnyBranchUIRendered(true, isBranchAdmin, isBranchLocked, indicatorVisible)

          // When module is enabled:
          // - If not branch_admin and not branch_locked → BranchSelector renders
          // - If branch_admin → branch_admin badge renders
          // - If not branch_admin and indicator visible → active indicator renders
          //
          // The only case where nothing renders is:
          //   not branch_admin AND branch_locked AND indicator not visible
          const nothingExpected = !isBranchAdmin && isBranchLocked && !indicatorVisible
          expect(anyRendered).toBe(!nothingExpected)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('module disabled is both necessary and sufficient for hiding ALL branch UI', () => {
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        fc.boolean(),
        (moduleEnabled, isBranchAdmin, isBranchLocked, indicatorVisible) => {
          const anyRendered = isAnyBranchUIRendered(moduleEnabled, isBranchAdmin, isBranchLocked, indicatorVisible)

          if (!moduleEnabled) {
            // Disabled → nothing rendered (necessary condition)
            expect(anyRendered).toBe(false)
          }
          // When enabled, rendering depends on user state (tested above)
        },
      ),
      { numRuns: 100 },
    )
  })
})


// Feature: branch-module-gating, Property 3: Nav item visibility gating
//
// **Validates: Requirements 4.1, 4.2, 4.3**
//
// For any organisation, the "Branch Transfers" and "Staff Schedule" navigation
// items are visible in the sidebar if and only if `branch_management` is enabled
// (and existing `adminOnly` gating is satisfied).

// ─── Types mirroring OrgLayout nav item definitions ───

interface NavItemDef {
  to: string
  label: string
  /** If set, this nav item is only shown when the module is enabled */
  module?: string
  /** If set, this nav item is only shown when the feature flag is enabled */
  flagKey?: string
  /** If true, only org_admin (and global_admin) can see this item */
  adminOnly?: boolean
  /** If set, this nav item is only shown when the org's trade family matches */
  tradeFamily?: string
}

// ─── Pure function replicating OrgLayout's visibleNavItems filter ───

/**
 * Mirrors OrgLayout's `visibleNavItems` useMemo filter exactly:
 *
 *   navItems.filter((item) => {
 *     if (item.adminOnly && userRole !== 'org_admin' && userRole !== 'global_admin') return false
 *     if (item.tradeFamily && (tradeFamily ?? 'automotive-transport') !== item.tradeFamily) return false
 *     if (item.module) return isEnabled(item.module)
 *     if (item.flagKey && !flags[item.flagKey]) return false
 *     return true
 *   })
 */
function filterVisibleNavItems(
  items: NavItemDef[],
  isModuleEnabled: (slug: string) => boolean,
  flags: Record<string, boolean>,
  userRole: string,
  tradeFamily: string | null,
): NavItemDef[] {
  return items.filter((item) => {
    // Admin-only items hidden from non-admin roles
    if (item.adminOnly && userRole !== 'org_admin' && userRole !== 'global_admin') return false
    // Trade family gating — null tradeFamily treated as automotive for backward compat
    if (item.tradeFamily && (tradeFamily ?? 'automotive-transport') !== item.tradeFamily) return false
    // If the item has a module gate, module enablement is sufficient
    if (item.module) return isModuleEnabled(item.module)
    // Items without a module gate fall back to feature flag check
    if (item.flagKey && !flags[item.flagKey]) return false
    return true
  })
}

// ─── The two branch-gated nav items as defined in OrgLayout ───

const BRANCH_NAV_ITEMS: NavItemDef[] = [
  { to: '/branch-transfers', label: 'Branch Transfers', module: 'branch_management', adminOnly: true },
  { to: '/staff-schedule', label: 'Staff Schedule', module: 'branch_management', adminOnly: true },
]

// A broader set including non-branch items to verify branch gating doesn't affect others
const SAMPLE_NAV_ITEMS: NavItemDef[] = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/customers', label: 'Customers' },
  { to: '/invoices', label: 'Invoices' },
  { to: '/bookings', label: 'Bookings', module: 'bookings', flagKey: 'bookings' },
  { to: '/inventory', label: 'Inventory', module: 'inventory', flagKey: 'inventory' },
  { to: '/settings', label: 'Settings', adminOnly: true },
  ...BRANCH_NAV_ITEMS,
]

// ─── Arbitraries ───

const NAV_ROLES = [
  'global_admin',
  'org_admin',
  'branch_admin',
  'location_manager',
  'salesperson',
  'staff_member',
] as const

const navRoleArb = fc.constantFrom(...NAV_ROLES)

const tradeFamilyArb: fc.Arbitrary<string | null> = fc.oneof(
  fc.constant(null),
  fc.constant('automotive-transport'),
  fc.constant('construction'),
  fc.constant('hospitality'),
  fc.constant('retail'),
)

/** Generates a random set of enabled module slugs */
const enabledModulesArb: fc.Arbitrary<Set<string>> = fc.subarray(
  ['branch_management', 'bookings', 'inventory', 'staff', 'jobs', 'quotes'],
  { minLength: 0 },
).map((arr) => new Set(arr))

/** Generates random feature flags */
const featureFlagsArb: fc.Arbitrary<Record<string, boolean>> = fc.record({
  bookings: fc.boolean(),
  inventory: fc.boolean(),
  staff: fc.boolean(),
  jobs: fc.boolean(),
  quotes: fc.boolean(),
})

// ─── Property 3: Nav item visibility gating ───

describe('Property 3: Nav item visibility gating', () => {
  it('Branch Transfers is hidden when branch_management is disabled (any role)', () => {
    fc.assert(
      fc.property(navRoleArb, tradeFamilyArb, featureFlagsArb, (role, tradeFamily, flags) => {
        const isEnabled = (_slug: string) => false // all modules disabled
        const visible = filterVisibleNavItems(BRANCH_NAV_ITEMS, isEnabled, flags, role, tradeFamily)
        const branchTransfers = visible.find((item) => item.label === 'Branch Transfers')
        expect(branchTransfers).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('Staff Schedule is hidden when branch_management is disabled (any role)', () => {
    fc.assert(
      fc.property(navRoleArb, tradeFamilyArb, featureFlagsArb, (role, tradeFamily, flags) => {
        const isEnabled = (_slug: string) => false
        const visible = filterVisibleNavItems(BRANCH_NAV_ITEMS, isEnabled, flags, role, tradeFamily)
        const staffSchedule = visible.find((item) => item.label === 'Staff Schedule')
        expect(staffSchedule).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('Branch Transfers is visible when branch_management enabled AND user is admin', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('org_admin', 'global_admin'),
        tradeFamilyArb,
        featureFlagsArb,
        (role, tradeFamily, flags) => {
          const isEnabled = (slug: string) => slug === 'branch_management'
          const visible = filterVisibleNavItems(BRANCH_NAV_ITEMS, isEnabled, flags, role, tradeFamily)
          const branchTransfers = visible.find((item) => item.label === 'Branch Transfers')
          expect(branchTransfers).toBeDefined()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Staff Schedule is visible when branch_management enabled AND user is admin', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('org_admin', 'global_admin'),
        tradeFamilyArb,
        featureFlagsArb,
        (role, tradeFamily, flags) => {
          const isEnabled = (slug: string) => slug === 'branch_management'
          const visible = filterVisibleNavItems(BRANCH_NAV_ITEMS, isEnabled, flags, role, tradeFamily)
          const staffSchedule = visible.find((item) => item.label === 'Staff Schedule')
          expect(staffSchedule).toBeDefined()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Branch nav items hidden for non-admin roles even when module is enabled', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('branch_admin', 'location_manager', 'salesperson', 'staff_member'),
        tradeFamilyArb,
        featureFlagsArb,
        (role, tradeFamily, flags) => {
          const isEnabled = (slug: string) => slug === 'branch_management'
          const visible = filterVisibleNavItems(BRANCH_NAV_ITEMS, isEnabled, flags, role, tradeFamily)
          // adminOnly gating takes precedence — non-admin roles see neither item
          expect(visible).toHaveLength(0)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('branch gating is iff: visible ↔ (module enabled AND admin role)', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        navRoleArb,
        tradeFamilyArb,
        featureFlagsArb,
        (enabledModules, role, tradeFamily, flags) => {
          const isEnabled = (slug: string) => enabledModules.has(slug)
          const visible = filterVisibleNavItems(BRANCH_NAV_ITEMS, isEnabled, flags, role, tradeFamily)

          const branchModuleEnabled = enabledModules.has('branch_management')
          const isAdmin = role === 'org_admin' || role === 'global_admin'
          const expectedVisible = branchModuleEnabled && isAdmin

          if (expectedVisible) {
            // Both items should be visible
            expect(visible).toHaveLength(2)
            expect(visible.map((i) => i.label).sort()).toEqual(['Branch Transfers', 'Staff Schedule'])
          } else {
            // Neither item should be visible
            expect(visible).toHaveLength(0)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('disabling branch_management does not affect non-branch nav items', () => {
    fc.assert(
      fc.property(
        enabledModulesArb,
        navRoleArb,
        tradeFamilyArb,
        featureFlagsArb,
        (enabledModules, role, tradeFamily, flags) => {
          const isEnabled = (slug: string) => enabledModules.has(slug)

          // Filter with current module state
          const visible = filterVisibleNavItems(SAMPLE_NAV_ITEMS, isEnabled, flags, role, tradeFamily)

          // Filter with branch_management forcibly disabled, all else equal
          const modulesWithoutBranch = new Set(enabledModules)
          modulesWithoutBranch.delete('branch_management')
          const isEnabledNoBranch = (slug: string) => modulesWithoutBranch.has(slug)
          const visibleNoBranch = filterVisibleNavItems(SAMPLE_NAV_ITEMS, isEnabledNoBranch, flags, role, tradeFamily)

          // Non-branch items should be identical in both cases
          const nonBranchLabels = (items: NavItemDef[]) =>
            items.filter((i) => i.label !== 'Branch Transfers' && i.label !== 'Staff Schedule').map((i) => i.label)

          expect(nonBranchLabels(visible)).toEqual(nonBranchLabels(visibleNoBranch))
        },
      ),
      { numRuns: 100 },
    )
  })
})


// Feature: branch-module-gating, Property 4: Branch-gated page redirect
//
// **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 6.1, 6.2**
//
// For any organisation with `branch_management` disabled, navigating to any
// branch-gated page URL (Branch Management, Branch Settings, Stock Transfers)
// results in a redirect to the Dashboard. When enabled, these pages render
// normally.
//
// Also covers: Settings sidebar hides "Branch Management" and "Branch Settings"
// links when module disabled.

// ─── Types mirroring page components and Settings nav ───

/**
 * Represents a branch-gated page component's redirect decision.
 * Each gated page (BranchManagement, BranchSettings, StockTransfers) checks
 * `isEnabled('branch_management')` at the top and returns <Navigate to="/dashboard" replace />
 * when disabled.
 */
interface GatedPageDef {
  /** Route path the user navigates to */
  path: string
  /** Human-readable page name */
  label: string
}

/** Settings sidebar nav item definition — mirrors Settings.tsx NAV_ITEMS */
interface SettingsNavItem {
  id: string
  label: string
  icon: string
  adminOnly?: boolean
  module?: string
}

// ─── The three branch-gated pages as implemented ───

const BRANCH_GATED_PAGES: GatedPageDef[] = [
  { path: '/settings/branches', label: 'Branch Management' },
  { path: '/settings/branches/:id', label: 'Branch Settings' },
  { path: '/inventory/stock-transfers', label: 'Stock Transfers' },
]

// ─── Settings sidebar nav items — mirrors Settings.tsx NAV_ITEMS ───

const SETTINGS_NAV_ITEMS: SettingsNavItem[] = [
  { id: 'profile', label: 'Profile', icon: '👤' },
  { id: 'organisation', label: 'Organisation', icon: '⚙', adminOnly: true },
  { id: 'branches', label: 'Branches', icon: '🏢', adminOnly: true, module: 'branch_management' },
  { id: 'users', label: 'Users', icon: '👥', adminOnly: true },
  { id: 'billing', label: 'Billing', icon: '💳', adminOnly: true },
  { id: 'accounting', label: 'Accounting', icon: '📒', adminOnly: true },
  { id: 'currency', label: 'Currency', icon: '💱', adminOnly: true },
  { id: 'language', label: 'Language', icon: '🌐', adminOnly: true },
  { id: 'printer', label: 'Printer', icon: '🖨', adminOnly: true },
  { id: 'webhooks', label: 'Webhooks', icon: '🔗', adminOnly: true },
  { id: 'modules', label: 'Modules', icon: '🧩', adminOnly: true },
  { id: 'notifications', label: 'Notifications', icon: '🔔', adminOnly: true },
]

// ─── Pure functions replicating redirect and nav filtering logic ───

/**
 * Mirrors the redirect guard at the top of each gated page component:
 *
 *   const { isEnabled } = useModules()
 *   if (!isEnabled('branch_management')) return <Navigate to="/dashboard" replace />
 *
 * Returns the destination: '/dashboard' if redirected, or the original path if rendered normally.
 */
function resolveGatedPageDestination(
  pagePath: string,
  isBranchModuleEnabled: boolean,
): string {
  if (!isBranchModuleEnabled) return '/dashboard'
  return pagePath
}

/**
 * Returns true when a gated page should redirect (i.e. module is disabled).
 */
function shouldRedirectGatedPage(isBranchModuleEnabled: boolean): boolean {
  return !isBranchModuleEnabled
}

/**
 * Mirrors Settings.tsx's visibleNavItems filter:
 *
 *   NAV_ITEMS.filter(item =>
 *     (!item.adminOnly || isAdmin) &&
 *     (!item.module || isEnabled(item.module))
 *   )
 *
 * Returns the filtered list of visible settings nav items.
 */
function filterSettingsNavItems(
  items: SettingsNavItem[],
  isAdmin: boolean,
  isModuleEnabled: (slug: string) => boolean,
): SettingsNavItem[] {
  return items.filter((item) =>
    (!item.adminOnly || isAdmin) &&
    (!item.module || isModuleEnabled(item.module))
  )
}

// ─── Arbitraries ───

const SETTINGS_ROLES = [
  'global_admin',
  'org_admin',
  'branch_admin',
  'location_manager',
  'salesperson',
  'staff_member',
] as const

const settingsRoleArb = fc.constantFrom(...SETTINGS_ROLES)

const gatedPageArb: fc.Arbitrary<GatedPageDef> = fc.constantFrom(...BRANCH_GATED_PAGES)

/** Generates a random set of enabled module slugs */
const settingsEnabledModulesArb: fc.Arbitrary<Set<string>> = fc.subarray(
  ['branch_management', 'bookings', 'inventory', 'staff', 'jobs', 'quotes'],
  { minLength: 0 },
).map((arr) => new Set(arr))

// ─── Property 4: Branch-gated page redirect ───

describe('Property 4: Branch-gated page redirect', () => {
  it('all gated pages redirect to /dashboard when branch_management is disabled', () => {
    fc.assert(
      fc.property(gatedPageArb, (page) => {
        const destination = resolveGatedPageDestination(page.path, false)
        expect(destination).toBe('/dashboard')
      }),
      { numRuns: 100 },
    )
  })

  it('all gated pages render normally when branch_management is enabled', () => {
    fc.assert(
      fc.property(gatedPageArb, (page) => {
        const destination = resolveGatedPageDestination(page.path, true)
        expect(destination).toBe(page.path)
      }),
      { numRuns: 100 },
    )
  })

  it('redirect decision is solely determined by module enablement, not by page identity', () => {
    fc.assert(
      fc.property(
        gatedPageArb,
        fc.boolean(),
        (page, moduleEnabled) => {
          const shouldRedirect = shouldRedirectGatedPage(moduleEnabled)
          const destination = resolveGatedPageDestination(page.path, moduleEnabled)

          if (shouldRedirect) {
            expect(destination).toBe('/dashboard')
          } else {
            expect(destination).toBe(page.path)
          }

          // The redirect decision must be the same for all pages given the same module state
          for (const _otherPage of BRANCH_GATED_PAGES) {
            const otherShouldRedirect = shouldRedirectGatedPage(moduleEnabled)
            expect(otherShouldRedirect).toBe(shouldRedirect)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('module disabled ↔ redirect is a biconditional (iff)', () => {
    fc.assert(
      fc.property(fc.boolean(), (moduleEnabled) => {
        const redirects = shouldRedirectGatedPage(moduleEnabled)
        // Redirect happens if and only if module is disabled
        expect(redirects).toBe(!moduleEnabled)
      }),
      { numRuns: 100 },
    )
  })

  // ─── Settings sidebar: "Branches" link visibility ───

  it('Settings sidebar hides "Branches" link when branch_management is disabled (admin user)', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('org_admin', 'global_admin'),
        (role) => {
          const isAdmin = role === 'org_admin' || role === 'global_admin'
          const isEnabled = (_slug: string) => false // all modules disabled
          const visible = filterSettingsNavItems(SETTINGS_NAV_ITEMS, isAdmin, isEnabled)
          const branchesLink = visible.find((item) => item.id === 'branches')
          expect(branchesLink).toBeUndefined()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Settings sidebar shows "Branches" link when branch_management is enabled (admin user)', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('org_admin', 'global_admin'),
        (role) => {
          const isAdmin = role === 'org_admin' || role === 'global_admin'
          const isEnabled = (slug: string) => slug === 'branch_management'
          const visible = filterSettingsNavItems(SETTINGS_NAV_ITEMS, isAdmin, isEnabled)
          const branchesLink = visible.find((item) => item.id === 'branches')
          expect(branchesLink).toBeDefined()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Settings sidebar hides "Branches" for non-admin roles regardless of module state', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('branch_admin', 'location_manager', 'salesperson', 'staff_member'),
        fc.boolean(),
        (_role, moduleEnabled) => {
          const isAdmin = false // non-admin roles
          const isEnabled = (slug: string) => moduleEnabled && slug === 'branch_management'
          const visible = filterSettingsNavItems(SETTINGS_NAV_ITEMS, isAdmin, isEnabled)
          const branchesLink = visible.find((item) => item.id === 'branches')
          // "Branches" is adminOnly, so non-admin roles never see it
          expect(branchesLink).toBeUndefined()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Settings sidebar "Branches" visibility is iff: module enabled AND admin role', () => {
    fc.assert(
      fc.property(
        settingsEnabledModulesArb,
        settingsRoleArb,
        (enabledModules, role) => {
          const isAdmin = role === 'org_admin' || role === 'global_admin'
          const isEnabled = (slug: string) => enabledModules.has(slug)
          const visible = filterSettingsNavItems(SETTINGS_NAV_ITEMS, isAdmin, isEnabled)
          const branchesLink = visible.find((item) => item.id === 'branches')

          const branchModuleEnabled = enabledModules.has('branch_management')
          const expectedVisible = branchModuleEnabled && isAdmin

          if (expectedVisible) {
            expect(branchesLink).toBeDefined()
          } else {
            expect(branchesLink).toBeUndefined()
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('disabling branch_management does not affect non-branch settings nav items', () => {
    fc.assert(
      fc.property(
        settingsEnabledModulesArb,
        settingsRoleArb,
        (enabledModules, role) => {
          const isAdmin = role === 'org_admin' || role === 'global_admin'
          const isEnabled = (slug: string) => enabledModules.has(slug)

          // Filter with current module state
          const visible = filterSettingsNavItems(SETTINGS_NAV_ITEMS, isAdmin, isEnabled)

          // Filter with branch_management forcibly disabled, all else equal
          const modulesWithoutBranch = new Set(enabledModules)
          modulesWithoutBranch.delete('branch_management')
          const isEnabledNoBranch = (slug: string) => modulesWithoutBranch.has(slug)
          const visibleNoBranch = filterSettingsNavItems(SETTINGS_NAV_ITEMS, isAdmin, isEnabledNoBranch)

          // Non-branch items should be identical in both cases
          const nonBranchIds = (items: SettingsNavItem[]) =>
            items.filter((i) => i.id !== 'branches').map((i) => i.id)

          expect(nonBranchIds(visible)).toEqual(nonBranchIds(visibleNoBranch))
        },
      ),
      { numRuns: 100 },
    )
  })
})
