import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { AppHeader } from '@/components/layout/AppHeader'
import { TabNavigator } from '@/components/layout/TabNavigator'

/** Routes where the app shell (header + tabs) should be hidden. */
const AUTH_ROUTES = ['/login', '/mfa-verify', '/forgot-password', '/biometric-lock']

/**
 * MobileLayout — root layout wrapping AppHeader + scrollable content area + TabNavigator.
 *
 * - Responsive for 320px–430px screen widths
 * - Conditionally hides AppHeader and TabNavigator on auth screens
 * - Hides TabNavigator for kiosk users (requirement 40.2)
 * - Content area scrolls independently with bottom padding for the tab bar
 * - Safe area insets for notched devices
 *
 * Requirements: 1.4
 */
export function MobileLayout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { isAuthenticated, user } = useAuth()

  // Strip the /mobile prefix if present for route matching
  const path = location.pathname.replace(/^\/mobile/, '')

  const isAuthRoute = AUTH_ROUTES.some(
    (route) => path === route || path.startsWith(route + '/'),
  )

  const isKiosk = user?.role === 'kiosk'

  // Hide app shell on auth screens or when not authenticated
  const showAppShell = isAuthenticated && !isAuthRoute

  return (
    <div className="flex min-h-[100dvh] w-full flex-col bg-white dark:bg-gray-900">
      {showAppShell && <AppHeader />}

      {/* Scrollable content area */}
      <main
        className={`flex flex-1 flex-col overflow-y-auto ${
          showAppShell && !isKiosk ? 'pb-[calc(56px+env(safe-area-inset-bottom))]' : ''
        }`}
      >
        {children}
      </main>

      {showAppShell && !isKiosk && <TabNavigator />}
    </div>
  )
}
