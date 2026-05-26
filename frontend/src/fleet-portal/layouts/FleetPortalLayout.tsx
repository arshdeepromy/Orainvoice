/**
 * Fleet Portal main layout — sidebar + header + outlet.
 *
 * Renders the standalone shell that wraps every authenticated portal
 * route. Deliberately distinct from `OrgLayout` so portal users never
 * see staff admin chrome.
 *
 * Implements: B2B Fleet Portal task 14.1 — Requirements 2.2, 19.8.
 */
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'

import { fleetClient } from '../api/client'
import { useFleetSession } from '../contexts/FleetSessionContext'
import { useVersionCheck } from '../hooks/useVersionCheck'

interface NavItem {
  to: string
  label: string
  adminOnly?: boolean
  driverOnly?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/fleet/dashboard', label: 'Dashboard' },
  { to: '/fleet/vehicles', label: 'Vehicles' },
  { to: '/fleet/checklists', label: 'Checklists' },
  { to: '/fleet/drivers', label: 'Drivers', adminOnly: true },
  { to: '/fleet/admins', label: 'Admins', adminOnly: true },
  { to: '/fleet/bookings', label: 'Bookings' },
  { to: '/fleet/quotes', label: 'Quotes', adminOnly: true },
  { to: '/fleet/invoices', label: 'Invoices', adminOnly: true },
  { to: '/fleet/reminders', label: 'Reminders', adminOnly: true },
  { to: '/fleet/notifications', label: 'Notifications' },
  { to: '/fleet/profile', label: 'My Profile' },
  { to: '/fleet/security', label: 'Security' },
]

export function FleetPortalLayout() {
  const { user, logout } = useFleetSession()
  const isAdmin = user?.portal_user_role === 'fleet_admin'
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const visibleItems = NAV_ITEMS.filter(
    (item) => (!item.adminOnly || isAdmin) && (!item.driverOnly || !isAdmin),
  )

  return (
    <div
      className="flex min-h-screen bg-gray-50 dark:bg-gray-900"
      style={{
        paddingTop: 'env(safe-area-inset-top)',
        paddingBottom: 'env(safe-area-inset-bottom)',
        paddingLeft: 'env(safe-area-inset-left)',
        paddingRight: 'env(safe-area-inset-right)',
      }}
    >
      {/* Sidebar */}
      <aside className="hidden w-64 flex-shrink-0 border-r border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-950 md:flex md:flex-col">
        <div className="px-4 py-6">
          <Link to="/fleet/dashboard" className="text-lg font-semibold text-gray-900 dark:text-white">
            Fleet Portal
          </Link>
          {user?.fleet_account_name ? (
            <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              {user.fleet_account_name}
            </div>
          ) : null}
        </div>
        <nav className="flex-1 space-y-1 px-2 overflow-y-auto">
          {visibleItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                'block rounded-md px-3 py-2 text-sm font-medium min-h-[44px] flex items-center justify-between ' +
                (isActive
                  ? 'bg-brand-100 text-brand-900 dark:bg-brand-900/40 dark:text-brand-200'
                  : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800')
              }
            >
              <span>{item.label}</span>
              {item.to === '/fleet/notifications' ? <UnreadBadge /> : null}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-gray-200 dark:border-gray-800">
          <div className="text-xs text-gray-600 dark:text-gray-400 mb-1 truncate" title={user?.email ?? ''}>
            {user?.email}
          </div>
          <button
            type="button"
            className="w-full text-left text-sm text-red-600 hover:text-red-800 dark:text-red-400 min-h-[44px]"
            onClick={() => { void logout() }}
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-800 dark:bg-gray-950 md:hidden">
          <Link to="/fleet/dashboard" className="text-base font-semibold">
            Fleet Portal
          </Link>
          <button
            type="button"
            className="text-gray-600 dark:text-gray-400 min-h-[44px] min-w-[44px] flex items-center justify-center"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? (
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
            ) : (
              <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
            )}
          </button>
        </header>
        {mobileMenuOpen && (
          <nav className="border-b border-gray-200 bg-white px-4 py-2 md:hidden dark:border-gray-800 dark:bg-gray-950">
            {visibleItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) =>
                  'block rounded-md px-3 py-2 text-sm font-medium min-h-[44px] flex items-center ' +
                  (isActive ? 'bg-indigo-100 text-indigo-900 dark:bg-indigo-900/40 dark:text-indigo-200' : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800')
                }
              >
                {item.label}
              </NavLink>
            ))}
            <button
              type="button"
              className="w-full text-left rounded-md px-3 py-2 text-sm text-red-600 hover:bg-red-50 min-h-[44px] mt-1 dark:text-red-400 dark:hover:bg-red-950/20"
              onClick={() => { void logout() }}
            >
              Sign out
            </button>
          </nav>
        )}
        <main className="flex-1 px-4 py-6 md:px-8">
          <VersionToast />
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** Version update toast — shown when backend version differs from build. */
function VersionToast() {
  const { updateAvailable, dismiss } = useVersionCheck()
  if (!updateAvailable) return null
  return (
    <div className="mb-4 flex items-center justify-between rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm dark:border-blue-900 dark:bg-blue-950/30">
      <span className="text-blue-800 dark:text-blue-200">A new version is available.</span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => window.location.reload()}
          className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 min-h-[32px]"
        >
          Reload
        </button>
        <button
          onClick={dismiss}
          className="text-xs text-blue-600 hover:underline dark:text-blue-400 min-h-[32px]"
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

/** Small unread-count chip rendered next to the Notifications nav item. */
function UnreadBadge() {
  const [count, setCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      try {
        const res = await fleetClient.get<{ total: number }>('/notifications', {
          params: { limit: 1 },
        })
        if (!cancelled) setCount(res.data?.total ?? 0)
      } catch {
        // Silent — badge is best-effort
      }
    }
    void refresh()
    const handle = window.setInterval(refresh, 60_000)
    return () => {
      cancelled = true
      window.clearInterval(handle)
    }
  }, [])

  if (!count) return null
  return (
    <span className="ml-2 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">
      {count > 99 ? '99+' : count}
    </span>
  )
}
