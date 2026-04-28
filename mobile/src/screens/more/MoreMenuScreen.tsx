import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { useAuth } from '@/contexts/AuthContext'
import type { UserRole } from '@shared/types/auth'

export interface MoreMenuItem {
  id: string
  label: string
  iconPath: string
  route: string
  moduleSlug: string
  tradeFamily?: string
  roles?: UserRole[]
  category: 'sales' | 'operations' | 'finance' | 'industry' | 'tools'
}

const SECTION_LABELS: Record<MoreMenuItem['category'], string> = {
  sales: 'Sales',
  operations: 'Operations',
  finance: 'Finance',
  industry: 'Industry',
  tools: 'Tools',
}

const SECTION_ORDER: MoreMenuItem['category'][] = [
  'sales',
  'operations',
  'finance',
  'industry',
  'tools',
]

export const MORE_MENU_ITEMS: MoreMenuItem[] = [
  {
    id: 'quotes',
    label: 'Quotes',
    iconPath: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
    route: '/quotes',
    moduleSlug: 'quotes',
    category: 'sales',
  },
  {
    id: 'recurring',
    label: 'Recurring',
    iconPath: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
    route: '/recurring',
    moduleSlug: 'recurring_invoices',
    category: 'sales',
  },
  {
    id: 'purchase-orders',
    label: 'Purchase Orders',
    iconPath: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
    route: '/purchase-orders',
    moduleSlug: 'purchase_orders',
    category: 'sales',
  },
  {
    id: 'pos',
    label: 'POS',
    iconPath: 'M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z',
    route: '/pos',
    moduleSlug: 'pos',
    category: 'sales',
  },
  {
    id: 'inventory',
    label: 'Inventory',
    iconPath: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
    route: '/inventory',
    moduleSlug: 'inventory',
    category: 'operations',
  },
  {
    id: 'expenses',
    label: 'Expenses',
    iconPath: 'M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z',
    route: '/expenses',
    moduleSlug: 'expenses',
    category: 'operations',
  },
  {
    id: 'staff',
    label: 'Staff',
    iconPath: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z',
    route: '/staff',
    moduleSlug: 'staff',
    category: 'operations',
  },
  {
    id: 'time-tracking',
    label: 'Time Tracking',
    iconPath: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
    route: '/time-tracking',
    moduleSlug: 'time_tracking',
    category: 'operations',
  },
  {
    id: 'bookings',
    label: 'Bookings',
    iconPath: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
    route: '/bookings',
    moduleSlug: 'bookings',
    category: 'operations',
  },
  {
    id: 'schedule',
    label: 'Schedule',
    iconPath: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
    route: '/schedule',
    moduleSlug: 'scheduling',
    category: 'operations',
  },
  {
    id: 'projects',
    label: 'Projects',
    iconPath: 'M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z',
    route: '/projects',
    moduleSlug: 'projects',
    category: 'operations',
  },
  {
    id: 'accounting',
    label: 'Accounting',
    iconPath: 'M9 7h6m0 10v-3m-3 3v-6m-3 6v-1m6-9a2 2 0 012 2v10a2 2 0 01-2 2H9a2 2 0 01-2-2V9a2 2 0 012-2',
    route: '/accounting',
    moduleSlug: 'accounting',
    category: 'finance',
  },
  {
    id: 'banking',
    label: 'Banking',
    iconPath: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z',
    route: '/banking',
    moduleSlug: 'accounting',
    category: 'finance',
  },
  {
    id: 'tax',
    label: 'Tax',
    iconPath: 'M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z',
    route: '/tax',
    moduleSlug: 'accounting',
    category: 'finance',
  },
  {
    id: 'reports',
    label: 'Reports',
    iconPath: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
    route: '/reports',
    moduleSlug: '*',
    category: 'finance',
  },
  {
    id: 'vehicles',
    label: 'Vehicles',
    iconPath: 'M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0zM13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10M13 16H3m10 0h2l3-6h-5',
    route: '/vehicles',
    moduleSlug: 'vehicles',
    tradeFamily: 'automotive-transport',
    category: 'industry',
  },
  {
    id: 'construction',
    label: 'Construction',
    iconPath: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4',
    route: '/construction/claims',
    moduleSlug: 'progress_claims',
    category: 'industry',
  },
  {
    id: 'franchise',
    label: 'Franchise',
    iconPath: 'M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z M15 11a3 3 0 11-6 0 3 3 0 016 0z',
    route: '/franchise',
    moduleSlug: 'franchise',
    category: 'industry',
  },
  {
    id: 'compliance',
    label: 'Compliance',
    iconPath: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
    route: '/compliance',
    moduleSlug: 'compliance_docs',
    category: 'industry',
  },
  {
    id: 'notifications',
    label: 'Notifications',
    iconPath: 'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9',
    route: '/notifications',
    moduleSlug: '*',
    category: 'tools',
  },
  {
    id: 'sms',
    label: 'SMS',
    iconPath: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
    route: '/sms',
    moduleSlug: 'sms',
    category: 'tools',
  },
  {
    id: 'settings',
    label: 'Settings',
    iconPath: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
    route: '/settings',
    moduleSlug: '*',
    roles: ['owner', 'admin'] as UserRole[],
    category: 'tools',
  },
  {
    id: 'kiosk',
    label: 'Kiosk',
    iconPath: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
    route: '/kiosk',
    moduleSlug: 'kiosk',
    roles: ['kiosk'] as UserRole[],
    category: 'tools',
  },
]

function isItemVisible(
  item: MoreMenuItem,
  isModuleEnabled: (slug: string) => boolean,
  tradeFamily: string | null,
  userRole: UserRole,
): boolean {
  if (item.moduleSlug !== '*' && !isModuleEnabled(item.moduleSlug)) return false
  if (item.tradeFamily && item.tradeFamily !== tradeFamily) return false
  if (item.roles?.length && !item.roles.includes(userRole)) return false
  return true
}

/**
 * MoreMenuScreen — module-gated navigation items grouped by category.
 * Sections only render when they contain at least one visible item.
 *
 * Requirements: 5.2, 5.3, 5.4, 5.5
 */
export default function MoreMenuScreen() {
  const navigate = useNavigate()
  const { isModuleEnabled, tradeFamily } = useModules()
  const { user } = useAuth()
  const userRole = (user?.role ?? 'salesperson') as UserRole

  const grouped = useMemo(() => {
    const visible = MORE_MENU_ITEMS.filter((item) =>
      isItemVisible(item, isModuleEnabled, tradeFamily, userRole),
    )
    const map = new Map<MoreMenuItem['category'], MoreMenuItem[]>()
    for (const item of visible) {
      const bucket = map.get(item.category) ?? []
      bucket.push(item)
      map.set(item.category, bucket)
    }
    return map
  }, [isModuleEnabled, tradeFamily, userRole])

  return (
    <div className="flex-1 overflow-y-auto px-4 pb-24 pt-4">
      <h1 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">
        More
      </h1>
      <div className="flex flex-col gap-6">
        {SECTION_ORDER.map((category) => {
          const items = grouped.get(category)
          if (!items?.length) return null
          return (
            <section key={category}>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                {SECTION_LABELS[category]}
              </h2>
              <div className="grid grid-cols-3 gap-3">
                {items.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => navigate(item.route)}
                    className="flex min-h-[44px] flex-col items-center justify-center gap-1.5 rounded-xl bg-gray-50 p-3 transition-colors active:bg-gray-100 dark:bg-gray-800 dark:active:bg-gray-700"
                    aria-label={item.label}
                  >
                    <svg
                      className="h-6 w-6 text-gray-600 dark:text-gray-300"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={1.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      aria-hidden="true"
                    >
                      <path d={item.iconPath} />
                    </svg>
                    <span className="text-center text-xs font-medium text-gray-700 dark:text-gray-300">
                      {item.label}
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}
