import { useCallback, useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import { useAuth } from '@/contexts/AuthContext'
import { TAB_CONFIGS, filterNavigationItems } from '@/navigation/TabConfig'
import type { TabConfig } from '@/navigation/TabConfig'
import type { UserRole } from '@shared/types/auth'

/**
 * Bottom tab navigation bar with 5 tabs: Dashboard, Invoices, Customers, Jobs, More.
 *
 * - 44px minimum touch targets (Apple HIG / WCAG 2.5.8)
 * - Active tab highlighted with primary colour
 * - Tabs filtered by module gating, trade family, and user role
 *
 * Requirements: 1.1, 1.2, 1.3, 5.2
 */
export function TabNavigator() {
  const navigate = useNavigate()
  const location = useLocation()
  const { enabledModules, tradeFamily } = useModules()
  const { user } = useAuth()

  const userRole = (user?.role ?? 'salesperson') as UserRole

  const visibleTabs = useMemo(
    () => filterNavigationItems(TAB_CONFIGS, enabledModules, tradeFamily, userRole),
    [enabledModules, tradeFamily, userRole],
  )

  const activeTabId = useMemo(() => {
    const path = location.pathname.replace(/^\/mobile/, '')
    // Match the most specific tab path first
    for (const tab of [...TAB_CONFIGS].reverse()) {
      if (tab.path === '/' && (path === '/' || path === '')) continue
      if (tab.path !== '/' && path.startsWith(tab.path)) return tab.id
    }
    // Default to dashboard for root path
    return 'dashboard'
  }, [location.pathname])

  const handleTabPress = useCallback(
    (tab: TabConfig) => {
      if (tab.id === activeTabId) {
        document.getElementById('main-scroll')?.scrollTo({ top: 0, behavior: 'smooth' })
        return
      }
      navigate(tab.path)
    },
    [navigate, activeTabId],
  )

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-gray-200 bg-white pb-[env(safe-area-inset-bottom)] dark:border-gray-700 dark:bg-gray-900"
      role="tablist"
      aria-label="Main navigation"
    >
      <div className="flex items-stretch justify-around">
        {visibleTabs.map((tab) => {
          const isActive = tab.id === activeTabId
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-label={tab.label}
              onClick={() => handleTabPress(tab)}
              className={`flex min-h-[44px] min-w-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2 transition-colors ${
                isActive
                  ? 'text-blue-600 dark:text-blue-400'
                  : 'text-gray-500 dark:text-gray-400'
              }`}
            >
              <svg
                className="h-6 w-6"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={isActive ? 2 : 1.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d={tab.iconPath} />
              </svg>
              <span
                className={`text-[10px] leading-tight ${
                  isActive ? 'font-semibold' : 'font-normal'
                }`}
              >
                {tab.label}
              </span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
