import type { UserRole } from '@shared/types/auth'

// ─── Types ──────────────────────────────────────────────────────────────────

export type MoreMenuCategory =
  | 'Sales'
  | 'Operations'
  | 'People'
  | 'Industry'
  | 'Assets & Compliance'
  | 'Communications'
  | 'Finance'
  | 'Other'
  | 'Account'

export interface MoreMenuItem {
  id: string
  label: string
  /** SVG path data for the icon (24×24 viewBox, stroke-based) */
  icon: string
  path: string
  /** Module slug required. Null = always visible. '*' = always visible (wildcard). */
  moduleSlug: string | null
  /** Trade family required. Null = all trade families. */
  tradeFamily: string | null
  /** Roles that can see this item. Empty array = all roles. */
  allowedRoles: UserRole[]
  /** If true, only owner/admin/org_admin can see this item. */
  adminOnly: boolean
  category: MoreMenuCategory
  badge?: number
}

// ─── Category ordering ──────────────────────────────────────────────────────

export const CATEGORY_ORDER: MoreMenuCategory[] = [
  'Sales',
  'Operations',
  'People',
  'Industry',
  'Assets & Compliance',
  'Communications',
  'Finance',
  'Other',
  'Account',
]

// ─── SVG icon paths (24×24 viewBox, stroke-based) ──────────────────────────

const ICON_QUOTES =
  'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01'
const ICON_RECURRING =
  'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15'
const ICON_PURCHASE_ORDERS =
  'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01'
const ICON_POS =
  'M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z'
const ICON_INVENTORY =
  'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4'
const ICON_CATALOGUE =
  'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10'
const ICON_EXPENSES =
  'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z'
const ICON_TIME_TRACKING =
  'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'
const ICON_BOOKINGS =
  'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z'
const ICON_SCHEDULE =
  'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z'
const ICON_PROJECTS =
  'M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z'
const ICON_STAFF =
  'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z'
const ICON_VEHICLES =
  'M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0zM13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10M13 16H3m10 0h2l3-6h-5'
const ICON_CONSTRUCTION =
  'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4'
const ICON_FLOOR_PLAN =
  'M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm10 0a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zm10 0a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z'
const ICON_KITCHEN =
  'M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4'
const ICON_FRANCHISE =
  'M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z M15 11a3 3 0 11-6 0 3 3 0 016 0z'
const ICON_ASSETS =
  'M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z'
const ICON_COMPLIANCE =
  'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z'
const ICON_SMS =
  'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z'
const ICON_ACCOUNTING =
  'M9 7h6m0 10v-3m-3 3v-6m-3 6v-1m6-9a2 2 0 012 2v10a2 2 0 01-2 2H9a2 2 0 01-2-2V9a2 2 0 012-2'
const ICON_BANKING =
  'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z'
const ICON_TAX =
  'M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z'
const ICON_REPORTS =
  'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'
const ICON_NOTIFICATIONS =
  'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9'
const ICON_SETTINGS =
  'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z'
const ICON_KIOSK =
  'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z'

// ─── All More menu items ────────────────────────────────────────────────────

export const MORE_MENU_ITEMS: MoreMenuItem[] = [
  // ── Sales ─────────────────────────────────────────────────────────────
  {
    id: 'quotes',
    label: 'Quotes',
    icon: ICON_QUOTES,
    path: '/quotes',
    moduleSlug: 'quotes',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Sales',
  },
  {
    id: 'recurring',
    label: 'Recurring',
    icon: ICON_RECURRING,
    path: '/recurring',
    moduleSlug: 'recurring_invoices',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Sales',
  },
  {
    id: 'purchase-orders',
    label: 'Purchase Orders',
    icon: ICON_PURCHASE_ORDERS,
    path: '/purchase-orders',
    moduleSlug: 'purchase_orders',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Sales',
  },
  {
    id: 'pos',
    label: 'POS',
    icon: ICON_POS,
    path: '/pos',
    moduleSlug: 'pos',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Sales',
  },

  // ── Operations ────────────────────────────────────────────────────────
  {
    id: 'inventory',
    label: 'Inventory',
    icon: ICON_INVENTORY,
    path: '/inventory',
    moduleSlug: 'inventory',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Operations',
  },
  {
    id: 'catalogue',
    label: 'Catalogue',
    icon: ICON_CATALOGUE,
    path: '/items',
    moduleSlug: 'inventory',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Operations',
  },
  {
    id: 'expenses',
    label: 'Expenses',
    icon: ICON_EXPENSES,
    path: '/expenses',
    moduleSlug: 'expenses',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Operations',
  },
  {
    id: 'time-tracking',
    label: 'Time Tracking',
    icon: ICON_TIME_TRACKING,
    path: '/time-tracking',
    moduleSlug: 'time_tracking',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Operations',
  },
  {
    id: 'bookings',
    label: 'Bookings',
    icon: ICON_BOOKINGS,
    path: '/bookings',
    moduleSlug: 'bookings',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Operations',
  },
  {
    id: 'schedule',
    label: 'Schedule',
    icon: ICON_SCHEDULE,
    path: '/schedule',
    moduleSlug: 'scheduling',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Operations',
  },
  {
    id: 'projects',
    label: 'Projects',
    icon: ICON_PROJECTS,
    path: '/projects',
    moduleSlug: 'projects',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Operations',
  },

  // ── People ────────────────────────────────────────────────────────────
  {
    id: 'staff',
    label: 'Staff',
    icon: ICON_STAFF,
    path: '/staff',
    moduleSlug: 'staff',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'People',
  },

  // ── Industry ──────────────────────────────────────────────────────────
  {
    id: 'vehicles',
    label: 'Vehicles',
    icon: ICON_VEHICLES,
    path: '/vehicles',
    moduleSlug: 'vehicles',
    tradeFamily: 'automotive-transport',
    allowedRoles: [],
    adminOnly: false,
    category: 'Industry',
  },
  {
    id: 'construction',
    label: 'Construction',
    icon: ICON_CONSTRUCTION,
    path: '/construction/claims',
    moduleSlug: 'progress_claims',
    tradeFamily: 'building-construction',
    allowedRoles: [],
    adminOnly: false,
    category: 'Industry',
  },
  {
    id: 'floor-plan',
    label: 'Floor Plan',
    icon: ICON_FLOOR_PLAN,
    path: '/floor-plan',
    moduleSlug: 'tables',
    tradeFamily: 'food-hospitality',
    allowedRoles: [],
    adminOnly: false,
    category: 'Industry',
  },
  {
    id: 'kitchen',
    label: 'Kitchen Display',
    icon: ICON_KITCHEN,
    path: '/kitchen',
    moduleSlug: 'kitchen_display',
    tradeFamily: 'food-hospitality',
    allowedRoles: [],
    adminOnly: false,
    category: 'Industry',
  },
  {
    id: 'franchise',
    label: 'Franchise',
    icon: ICON_FRANCHISE,
    path: '/franchise',
    moduleSlug: 'franchise',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Industry',
  },

  // ── Assets & Compliance ───────────────────────────────────────────────
  {
    id: 'assets',
    label: 'Assets',
    icon: ICON_ASSETS,
    path: '/assets',
    moduleSlug: 'assets',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Assets & Compliance',
  },
  {
    id: 'compliance',
    label: 'Compliance',
    icon: ICON_COMPLIANCE,
    path: '/compliance',
    moduleSlug: 'compliance_docs',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Assets & Compliance',
  },

  // ── Communications ────────────────────────────────────────────────────
  {
    id: 'sms',
    label: 'SMS',
    icon: ICON_SMS,
    path: '/sms',
    moduleSlug: 'sms',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Communications',
  },
  {
    id: 'notifications',
    label: 'Notifications',
    icon: ICON_NOTIFICATIONS,
    path: '/notifications',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Other',
  },

  // ── Finance ───────────────────────────────────────────────────────────
  {
    id: 'accounting',
    label: 'Accounting',
    icon: ICON_ACCOUNTING,
    path: '/accounting',
    moduleSlug: 'accounting',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Finance',
  },
  {
    id: 'banking',
    label: 'Banking',
    icon: ICON_BANKING,
    path: '/banking',
    moduleSlug: 'accounting',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Finance',
  },
  {
    id: 'tax',
    label: 'Tax',
    icon: ICON_TAX,
    path: '/tax',
    moduleSlug: 'accounting',
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Finance',
  },
  {
    id: 'reports',
    label: 'Reports',
    icon: ICON_REPORTS,
    path: '/reports',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Finance',
  },

  // ── Account ───────────────────────────────────────────────────────────
  {
    id: 'settings',
    label: 'Settings',
    icon: ICON_SETTINGS,
    path: '/settings',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: ['owner', 'admin', 'org_admin'],
    adminOnly: true,
    category: 'Account',
  },
  {
    id: 'kiosk',
    label: 'Kiosk',
    icon: ICON_KIOSK,
    path: '/kiosk',
    moduleSlug: 'kiosk',
    tradeFamily: null,
    allowedRoles: ['kiosk'],
    adminOnly: false,
    category: 'Account',
  },
]

// ─── Filtering logic ────────────────────────────────────────────────────────

/**
 * Admin roles that can see adminOnly items.
 */
const ADMIN_ROLES: UserRole[] = ['owner', 'admin', 'org_admin']

/**
 * Determines whether a single MoreMenuItem should be visible given the
 * current enabled modules, trade family, and user role.
 *
 * Rules (identical to existing sidebar logic):
 * - If `moduleSlug` is non-null, the module must be in `enabledModules`.
 * - If `tradeFamily` is non-null, it must match `currentTradeFamily`.
 * - If `allowedRoles` is non-empty, `userRole` must be in the list.
 * - If `adminOnly` is true, `userRole` must be an admin role (owner, admin, org_admin).
 * - Items with null/empty gates are always visible.
 */
export function isMoreMenuItemVisible(
  item: MoreMenuItem,
  enabledModules: string[],
  currentTradeFamily: string | null,
  userRole: UserRole,
): boolean {
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

  // Admin-only gate
  if (item.adminOnly && !ADMIN_ROLES.includes(userRole)) {
    return false
  }

  return true
}

/**
 * Filters a list of MoreMenuItems based on the current context.
 *
 * This is the primary filtering function exported for use by the MoreDrawer
 * component and for property-based testing.
 *
 * The logic is identical to the existing sidebar filtering:
 * - moduleSlug must be enabled (or null for always-visible)
 * - tradeFamily must match (or null for all)
 * - allowedRoles must include userRole (or empty for all)
 * - adminOnly items require an admin role
 */
export function filterMoreMenuItems(
  items: MoreMenuItem[],
  enabledModules: string[],
  currentTradeFamily: string | null,
  userRole: UserRole,
): MoreMenuItem[] {
  return items.filter((item) =>
    isMoreMenuItemVisible(item, enabledModules, currentTradeFamily, userRole),
  )
}

/**
 * Groups filtered items by category in the defined CATEGORY_ORDER.
 * Returns an array of [category, items[]] tuples, omitting empty categories.
 */
export function groupByCategory(
  items: MoreMenuItem[],
): [MoreMenuCategory, MoreMenuItem[]][] {
  const map = new Map<MoreMenuCategory, MoreMenuItem[]>()
  for (const item of items) {
    const bucket = map.get(item.category) ?? []
    bucket.push(item)
    map.set(item.category, bucket)
  }

  const result: [MoreMenuCategory, MoreMenuItem[]][] = []
  for (const category of CATEGORY_ORDER) {
    const items = map.get(category)
    if (items?.length) {
      result.push([category, items])
    }
  }
  return result
}
