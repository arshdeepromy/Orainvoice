import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { useFeatureFlags } from '@/contexts/FeatureFlagContext'
import { GlobalSearchBar } from '@/components/search'

interface AdminNavItem {
  type?: 'section'
  to?: string
  label: string
  /** If set, this nav item is only shown when the feature flag is enabled */
  flagKey?: string
}

const adminNavItems: AdminNavItem[] = [
  { type: 'section', label: 'Core' },
  { to: '/admin/dashboard', label: 'Dashboard' },
  { to: '/admin/organisations', label: 'Organisations' },
  { to: '/admin/users', label: 'Users' },
  { type: 'section', label: 'Configuration' },
  { to: '/admin/plans', label: 'Subscription Management' },
  { to: '/admin/feature-flags', label: 'Feature Flags' },
  { to: '/admin/branding', label: 'Branding', flagKey: 'branding' },
  { to: '/admin/integrations', label: 'Integrations' },
  { to: '/admin/settings', label: 'Settings' },
  { type: 'section', label: 'Monitoring' },
  { to: '/admin/analytics', label: 'Analytics', flagKey: 'analytics' },
  { to: '/admin/reports', label: 'Reports', flagKey: 'reports' },
  { to: '/admin/audit-log', label: 'Audit Log' },
  { to: '/admin/errors', label: 'Error Log' },
  { to: '/admin/notifications', label: 'Notifications' },
  { type: 'section', label: 'Tools' },
  { to: '/admin/migration', label: 'Migration Tool', flagKey: 'migration_tool' },
  { to: '/admin/live-migration', label: 'Live Migration' },
  { to: '/admin/ha-replication', label: 'HA Replication' },
]

export function AdminLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { user, logout } = useAuth()
  const { flags } = useFeatureFlags()
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  /**
   * Filter nav items based on feature flags.
   * Section headers are kept only if they have at least one visible child item after them.
   */
  const visibleNavItems = (() => {
    // First pass: mark which link items are visible
    const filtered = adminNavItems.filter((item) => {
      if (item.type === 'section') return true // keep sections for now
      if (item.flagKey && !flags[item.flagKey]) return false
      return true
    })

    // Second pass: remove section headers that have no visible children after them
    return filtered.filter((item, idx) => {
      if (item.type !== 'section') return true
      // Check if there's at least one non-section item before the next section (or end)
      for (let i = idx + 1; i < filtered.length; i++) {
        if (filtered[i].type === 'section') return false
        return true // found a visible child
      }
      return false // section at end with no children
    })
  })()

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-gray-900 transition-transform duration-200 ease-in-out lg:static lg:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
        role="navigation"
        aria-label="Admin navigation"
      >
        {/* Admin branding */}
        <div className="flex h-16 items-center gap-3 border-b border-gray-700 px-4">
          <div className="h-8 w-8 rounded-md bg-indigo-500 flex items-center justify-center text-white text-sm font-bold">
            A
          </div>
          <span className="text-lg font-semibold text-white truncate">
            Admin Console
          </span>
          <button
            className="ml-auto min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-400 hover:text-white lg:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 overflow-y-auto py-4 px-3">
          <ul className="space-y-1">
            {visibleNavItems.map((item, idx) => {
              if (item.type === 'section') {
                return (
                  <li key={item.label} className={idx > 0 ? 'pt-4' : ''}>
                    <span className="px-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
                      {item.label}
                    </span>
                  </li>
                )
              }
              return (
                <li key={item.to}>
                  <NavLink
                    to={item.to!}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) =>
                      `flex items-center rounded-lg px-3 min-h-[44px] text-sm font-medium transition-colors ${
                        isActive
                          ? 'bg-gray-800 text-white'
                          : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              )
            })}
          </ul>
        </nav>

        {/* Logout */}
        <div className="border-t border-gray-700 p-3">
          <div className="mb-2 px-3 text-xs text-gray-400 truncate">
            {user?.email ?? 'admin'}
          </div>
          <button
            onClick={handleLogout}
            className="flex w-full items-center rounded-lg px-3 min-h-[44px] text-sm font-medium text-gray-300 hover:bg-gray-800 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content area */}
      <div className="flex flex-1 flex-col overflow-hidden min-h-0">
        {/* Header */}
        <header
          className="flex h-16 items-center gap-4 border-b border-gray-200 bg-white px-4"
          role="banner"
        >
          <button
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md text-gray-500 hover:text-gray-700 lg:hidden"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open sidebar"
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <h1 className="text-lg font-semibold text-gray-900">
            Global Admin
          </h1>

          <div className="flex-1" />

          <span className="text-sm text-gray-600 hidden sm:inline">
            {user?.email ?? 'Admin'}
          </span>
          <button
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-full bg-indigo-100 text-sm font-medium text-indigo-700 hover:bg-indigo-200"
            aria-label="Admin user menu"
            onClick={handleLogout}
            title="Sign out"
          >
            {(user?.name ?? 'A').charAt(0).toUpperCase()}
          </button>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6 min-h-0" role="main">
          <Outlet />
        </main>
      </div>

      {/* Global search overlay */}
      <GlobalSearchBar />
    </div>
  )
}
