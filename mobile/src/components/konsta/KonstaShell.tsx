import { useState, useMemo } from 'react'
import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { KonstaTabbar } from '@/components/konsta/KonstaTabbar'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import { MoreDrawer } from '@/components/konsta/MoreDrawer'
import { useNetworkStatus } from '@/hooks/useNetworkStatus'

/**
 * Auth routes where the app shell (navbar + tabbar) should be hidden.
 * On these routes, only the children are rendered (no chrome).
 */
const AUTH_ROUTES = [
  '/login',
  '/login/mfa',
  '/forgot-password',
  '/signup',
  '/reset-password',
  '/verify-email',
  '/landing',
  '/pay',
]

/**
 * Route-to-title mapping for root-level screens.
 * Detail screens (with :id segments) are handled by the screens themselves
 * passing title/showBack props via context or direct rendering.
 */
const ROUTE_TITLES: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/invoices': 'Invoices',
  '/customers': 'Customers',
  '/quotes': 'Quotes',
  '/jobs': 'Active Jobs',
  '/job-cards': 'Job Cards',
  '/bookings': 'Bookings',
  '/vehicles': 'Vehicles',
  '/inventory': 'Inventory',
  '/items': 'Catalogue',
  '/staff': 'Staff',
  '/projects': 'Projects',
  '/expenses': 'Expenses',
  '/time-tracking': 'Time Tracking',
  '/schedule': 'Schedule',
  '/pos': 'POS',
  '/recurring': 'Recurring',
  '/purchase-orders': 'Purchase Orders',
  '/progress-claims': 'Progress Claims',
  '/variations': 'Variations',
  '/retentions': 'Retentions',
  '/floor-plan': 'Floor Plan',
  '/kitchen': 'Kitchen Display',
  '/assets': 'Assets',
  '/compliance': 'Compliance',
  '/sms': 'Messages',
  '/reports': 'Reports',
  '/notifications': 'Notifications',
  '/portal': 'Customer Portal',
  '/kiosk': 'Kiosk',
  '/settings': 'Settings',
}

/**
 * Resolves navbar metadata (title, showBack) from the current route path.
 * Root-level routes get their title from ROUTE_TITLES with no back button.
 * Nested/detail routes (containing an ID segment or deeper path) show a back button.
 */
export function resolveNavbarMeta(path: string): {
  title: string
  showBack: boolean
} {
  // Exact match on root routes
  if (ROUTE_TITLES[path]) {
    return { title: ROUTE_TITLES[path], showBack: false }
  }

  // Find the closest matching root route for nested paths
  const segments = path.split('/').filter(Boolean)
  if (segments.length >= 2) {
    const rootPath = '/' + segments[0]
    const rootTitle = ROUTE_TITLES[rootPath]
    if (rootTitle) {
      return { title: rootTitle, showBack: true }
    }
  }

  // Fallback
  return { title: '', showBack: segments.length > 1 }
}

/**
 * KonstaShell — layout shell that replaces MobileLayout.
 *
 * Conditionally renders KonstaNavbar + scrollable content + KonstaTabbar
 * based on auth state and the current route.
 *
 * Behaviour:
 * - Auth routes: render children only (no navbar, no tabbar)
 * - Authenticated routes: render KonstaNavbar + scrollable content + KonstaTabbar
 * - Kiosk role: render KonstaNavbar + scrollable content (no tabbar)
 * - Unauthenticated on non-auth routes: render children only (redirect handled elsewhere)
 *
 * Requirements: 6.1, 4.1, 4.8
 */
export function KonstaShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { isAuthenticated, user } = useAuth()
  const [_moreOpen, _setMoreOpen] = useState(false)
  const { isOnline } = useNetworkStatus()

  // Strip the /mobile prefix if present for route matching
  const path = location.pathname.replace(/^\/mobile/, '')

  const isAuthRoute = AUTH_ROUTES.some(
    (route) => path === route || path.startsWith(route + '/'),
  )

  const isKiosk = user?.role === 'kiosk'

  // Show the app shell (navbar + tabbar) only when authenticated and not on auth routes
  const showShell = isAuthenticated && !isAuthRoute

  // Resolve navbar title and back button from the current route
  const navbarMeta = useMemo(() => resolveNavbarMeta(path), [path])

  // Auth routes or unauthenticated: render children only
  if (!showShell) {
    return (
      <div className="flex min-h-[100dvh] w-full flex-col bg-white dark:bg-gray-900">
        {children}
      </div>
    )
  }

  // Authenticated app shell
  return (
    <div className="flex min-h-[100dvh] w-full flex-col bg-white dark:bg-gray-900">
      {/* Offline banner */}
      {!isOnline && (
        <div
          className="bg-red-600 px-4 py-1.5 text-center text-xs font-medium text-white"
          role="alert"
          data-testid="offline-banner"
        >
          You are offline
        </div>
      )}

      {/* KonstaNavbar — screen header with back button and branch selector */}
      <KonstaNavbar
        title={navbarMeta.title}
        showBack={navbarMeta.showBack}
      />

      {/* Scrollable content area */}
      <main
        id="main-scroll"
        className={`flex flex-1 flex-col overflow-y-auto ${
          !isKiosk ? 'pb-[calc(56px+env(safe-area-inset-bottom))]' : ''
        }`}
      >
        {children}
      </main>

      {/* KonstaTabbar — real Konsta UI Tabbar with dynamic 4th tab */}
      {!isKiosk && (
        <KonstaTabbar onMorePress={() => _setMoreOpen(true)} />
      )}

      {/* MoreDrawer — module-gated navigation sheet */}
      <MoreDrawer isOpen={_moreOpen} onClose={() => _setMoreOpen(false)} />
    </div>
  )
}
