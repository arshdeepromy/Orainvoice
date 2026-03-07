import { useState } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { GlobalSearchBar } from '@/components/search'

const adminNavItems = [
  { to: '/admin/dashboard', label: 'Dashboard' },
  { to: '/admin/organisations', label: 'Organisations' },
  { to: '/admin/integrations', label: 'Integrations' },
  { to: '/admin/errors', label: 'Error Log' },
  { to: '/admin/settings', label: 'Settings' },
  { to: '/admin/reports', label: 'Reports' },
  { to: '/admin/audit-log', label: 'Audit Log' },
]

export function AdminLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

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
            {adminNavItems.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
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
            ))}
          </ul>
        </nav>
      </aside>

      {/* Main content area */}
      <div className="flex flex-1 flex-col overflow-hidden">
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

          <button
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-full bg-indigo-100 text-sm font-medium text-indigo-700 hover:bg-indigo-200"
            aria-label="Admin user menu"
          >
            A
          </button>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6" role="main">
          <Outlet />
        </main>
      </div>

      {/* Global search overlay */}
      <GlobalSearchBar />
    </div>
  )
}
