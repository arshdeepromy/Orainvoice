import { useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { KonstaTabbar } from '@/components/konsta/KonstaTabbar'
import { MoreDrawer } from '@/components/konsta/MoreDrawer'
import { useNetworkStatus } from '@/hooks/useNetworkStatus'

/**
 * Auth routes where the app shell (tabbar) should be hidden.
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
 * KonstaShell — layout shell that replaces MobileLayout.
 *
 * Each screen owns its own Konsta `<Navbar>` inside its `<Page>` component.
 * The shell only provides: offline banner + scrollable content area + tabbar + more drawer.
 *
 * Behaviour:
 * - Auth routes: render children only (no tabbar)
 * - Authenticated routes: render offline banner + scrollable content + KonstaTabbar
 * - Kiosk role: render scrollable content (no tabbar)
 * - Unauthenticated on non-auth routes: render children only (redirect handled elsewhere)
 *
 * The MoreDrawer is rendered as a sibling OUTSIDE the main layout div
 * so it is not clipped by overflow:hidden on the content area.
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

  // Show the app shell (tabbar) only when authenticated and not on auth routes
  const showShell = isAuthenticated && !isAuthRoute

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
    <>
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

        {/* Scrollable content area — each screen provides its own Navbar via Konsta Page */}
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
      </div>

      {/* MoreDrawer — rendered OUTSIDE the layout div to avoid z-index clipping */}
      <MoreDrawer isOpen={_moreOpen} onClose={() => _setMoreOpen(false)} />
    </>
  )
}
