import type { UserRole } from '@shared/types/auth'

/**
 * Configuration for a bottom tab in the TabNavigator.
 *
 * - `moduleSlug: null` means the tab is always visible (no module gate).
 * - `tradeFamily: null` means visible for all trade families.
 * - `allowedRoles: []` means visible for all roles.
 */
export interface TabConfig {
  id: string
  label: string
  /** SVG path data for the tab icon (24×24 viewBox) */
  iconPath: string
  /** Route path this tab navigates to */
  path: string
  /** Module slug required for this tab to be visible. Null = always visible. */
  moduleSlug: string | null
  /** Trade family required. Null = all trade families. */
  tradeFamily: string | null
  /** Roles that can see this tab. Empty array = all roles. */
  allowedRoles: UserRole[]
}

// SVG path data for tab icons (24×24 viewBox, stroke-based)
const ICON_DASHBOARD =
  'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1'
const ICON_INVOICES =
  'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z'
const ICON_CUSTOMERS =
  'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z'
const ICON_JOBS =
  'M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m8 0H8m8 0h2a2 2 0 012 2v6a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h2'
const ICON_MORE =
  'M4 6h16M4 12h16M4 18h16'

/**
 * Default tab definitions for the bottom TabNavigator.
 *
 * Dashboard, Invoices, Customers: always visible.
 * Jobs: gated by the 'jobs' module.
 * More: always visible.
 */
export const TAB_CONFIGS: TabConfig[] = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    iconPath: ICON_DASHBOARD,
    path: '/',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: [],
  },
  {
    id: 'invoices',
    label: 'Invoices',
    iconPath: ICON_INVOICES,
    path: '/invoices',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: [],
  },
  {
    id: 'customers',
    label: 'Customers',
    iconPath: ICON_CUSTOMERS,
    path: '/customers',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: [],
  },
  {
    id: 'jobs',
    label: 'Jobs',
    iconPath: ICON_JOBS,
    path: '/jobs',
    moduleSlug: 'jobs',
    tradeFamily: null,
    allowedRoles: [],
  },
  {
    id: 'more',
    label: 'More',
    iconPath: ICON_MORE,
    path: '/more',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: [],
  },
]

/**
 * Pure filtering function for navigation items.
 *
 * Determines whether a navigation item should be visible given the current
 * enabled modules, trade family, and user role.
 *
 * Rules:
 * - If `moduleSlug` is non-null, the module must be in `enabledModules`.
 * - If `tradeFamily` is non-null, it must match `currentTradeFamily`.
 * - If `allowedRoles` is non-empty, `userRole` must be in the list.
 * - Items with null/empty gates are always visible.
 */
export function isNavigationItemVisible(
  item: {
    moduleSlug: string | null
    tradeFamily: string | null
    allowedRoles: UserRole[]
  },
  enabledModules: string[],
  currentTradeFamily: string | null,
  userRole: UserRole,
): boolean {
  // Module gate: if a module is required, it must be enabled
  if (item.moduleSlug !== null && !enabledModules.includes(item.moduleSlug)) {
    return false
  }

  // Trade family gate: if a trade family is required, it must match
  if (item.tradeFamily !== null && item.tradeFamily !== currentTradeFamily) {
    return false
  }

  // Role gate: if roles are specified, the user must have one of them
  if (item.allowedRoles.length > 0 && !item.allowedRoles.includes(userRole)) {
    return false
  }

  return true
}

/**
 * Filter a list of navigation items based on the current context.
 */
export function filterNavigationItems<
  T extends {
    moduleSlug: string | null
    tradeFamily: string | null
    allowedRoles: UserRole[]
  },
>(
  items: T[],
  enabledModules: string[],
  currentTradeFamily: string | null,
  userRole: UserRole,
): T[] {
  return items.filter((item) =>
    isNavigationItemVisible(item, enabledModules, currentTradeFamily, userRole),
  )
}
