import { useCallback, useMemo } from 'react'
import { Tabbar, TabbarLink } from 'konsta/react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useModules } from '@/contexts/ModuleContext'
import {
  buildTabs,
  JOBS_TAB,
  QUOTES_TAB,
  BOOKINGS_TAB,
  REPORTS_TAB,
  HOME_TAB,
  INVOICES_TAB,
  CUSTOMERS_TAB,
  MORE_TAB,
} from '@/navigation/TabConfig'
import type { TabConfig } from '@/navigation/TabConfig'

// ─── Tab icon component ─────────────────────────────────────────────────────

function TabIcon({ d }: { d: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.5}
      stroke="currentColor"
      className="h-6 w-6"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  )
}

// Re-export tab configs for backward compatibility with existing tests/imports
export { HOME_TAB, INVOICES_TAB, CUSTOMERS_TAB, JOBS_TAB, QUOTES_TAB, BOOKINGS_TAB, REPORTS_TAB, MORE_TAB }
export { buildTabs, resolveFourthTab } from '@/navigation/TabConfig'

// ─── KonstaTabbar component ─────────────────────────────────────────────────

/**
 * KonstaTabbar — bottom tab bar using Konsta UI Tabbar and TabbarLink.
 *
 * Renders 5 tabs: Home, Invoices, Customers, dynamic 4th tab, More.
 * The 4th tab is resolved dynamically based on enabled modules.
 * The active tab is determined by the current route.
 * Safe area insets are handled by the parent KonstaApp `safeAreas` prop.
 *
 * The `onMorePress` callback is invoked when the More tab is tapped,
 * allowing the parent to open the MoreDrawer (task 3.4).
 *
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
 */
export function KonstaTabbar({ onMorePress }: { onMorePress?: () => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { enabledModules } = useModules()

  const tabs = useMemo(() => buildTabs(enabledModules), [enabledModules])

  // Determine which tab is active based on the current path
  const isTabActive = useCallback(
    (tab: TabConfig): boolean => {
      const path = location.pathname.replace(/^\/mobile/, '')
      // Home tab matches both '/' and '/dashboard'
      if (tab.id === 'home') {
        return path === '/' || path === '/dashboard' || path.startsWith('/dashboard/')
      }
      return path === tab.path || path.startsWith(tab.path + '/')
    },
    [location.pathname],
  )

  const handleTabPress = useCallback(
    (tab: TabConfig) => {
      if (tab.id === 'more') {
        onMorePress?.()
        return
      }
      navigate(tab.path)
    },
    [navigate, onMorePress],
  )

  return (
    <Tabbar labels icons data-testid="konsta-tabbar" className="konsta-tabbar-fixed">
      {tabs.map((tab) => (
        <TabbarLink
          key={tab.id}
          active={isTabActive(tab)}
          icon={<TabIcon d={tab.iconPath} />}
          label={tab.label}
          onClick={() => handleTabPress(tab)}
          data-testid={`tab-${tab.id}`}
        />
      ))}
    </Tabbar>
  )
}
