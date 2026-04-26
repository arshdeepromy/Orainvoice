import { useState, useMemo, useRef, useEffect } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useTenant } from '@/contexts/TenantContext'
import { useModules } from '@/contexts/ModuleContext'
import { useAuth } from '@/contexts/AuthContext'
import { useFeatureFlags } from '@/contexts/FeatureFlagContext'
import { GlobalSearchBar } from '@/components/search'
import { BranchSelector } from '@/components/branch/BranchSelector'
import { useBranch } from '@/contexts/BranchContext'
import { getActiveBranchIndicatorState } from '@/pages/settings/branch-staff-helpers'
import { usePaymentMethodEnforcement } from '@/hooks/usePaymentMethodEnforcement'
import { BlockingPaymentModal } from '@/components/billing/BlockingPaymentModal'
import { ExpiringPaymentWarningModal } from '@/components/billing/ExpiringPaymentWarningModal'
import NotificationBadge from '@/pages/compliance/NotificationBadge'

interface QuickAction {
  label: string
  path: string
  icon: string
  module?: string
  flagKey?: string
  state?: Record<string, unknown>
}

interface NavItem {
  to: string
  label: string
  icon: React.ComponentType
  /** If set, this nav item is only shown when the module is enabled */
  module?: string
  /** If set, this nav item is only shown when the feature flag is enabled */
  flagKey?: string
  /** If true, only org_admin (and global_admin) can see this item */
  adminOnly?: boolean
  /** If set, this nav item is only shown when the org's trade family matches (null treated as automotive for backward compat) */
  tradeFamily?: string
}

const navItems: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: DashboardIcon },
  { to: '/customers', label: 'Customers', icon: CustomersIcon },
  { to: '/vehicles', label: 'Vehicles', icon: VehiclesIcon, module: 'vehicles', flagKey: 'vehicles', tradeFamily: 'automotive-transport' },
  { to: '/invoices', label: 'Invoices', icon: InvoicesIcon },
  { to: '/quotes', label: 'Quotes', icon: QuotesIcon, module: 'quotes', flagKey: 'quotes' },
  { to: '/job-cards', label: 'Job Cards', icon: JobCardsIcon, module: 'jobs', flagKey: 'jobs' },
  { to: '/jobs', label: 'Jobs', icon: JobCardsIcon, module: 'jobs', flagKey: 'jobs' },
  { to: '/bookings', label: 'Bookings', icon: BookingsIcon, module: 'bookings', flagKey: 'bookings' },
  { to: '/inventory', label: 'Inventory', icon: InventoryIcon, module: 'inventory', flagKey: 'inventory' },
  { to: '/items', label: 'Items', icon: CatalogueIcon, module: 'inventory' },
  { to: '/catalogue', label: 'Catalogue', icon: CatalogueIcon, module: 'inventory' },
  { to: '/staff', label: 'Staff', icon: StaffIcon, module: 'staff', flagKey: 'staff' },
  { to: '/projects', label: 'Projects', icon: ProjectsIcon, module: 'projects', flagKey: 'projects' },
  { to: '/expenses', label: 'Expenses', icon: ExpensesIcon, module: 'expenses', flagKey: 'expenses' },
  { to: '/time-tracking', label: 'Time Tracking', icon: TimeTrackingIcon, module: 'time_tracking', flagKey: 'time_tracking' },
  { to: '/schedule', label: 'Schedule', icon: ScheduleIcon, module: 'scheduling', flagKey: 'scheduling' },
  { to: '/pos', label: 'POS', icon: POSIcon, module: 'pos', flagKey: 'pos' },
  { to: '/recurring', label: 'Recurring', icon: RecurringIcon, module: 'recurring_invoices', flagKey: 'recurring' },
  { to: '/purchase-orders', label: 'Purchase Orders', icon: PurchaseOrderIcon, module: 'purchase_orders', flagKey: 'purchase_orders' },
  { to: '/progress-claims', label: 'Progress Claims', icon: ConstructionIcon, module: 'progress_claims', flagKey: 'progress_claims' },
  { to: '/variations', label: 'Variations', icon: ConstructionIcon, module: 'variations', flagKey: 'variations' },
  { to: '/retentions', label: 'Retentions', icon: ConstructionIcon, module: 'retentions', flagKey: 'retentions' },
  { to: '/floor-plan', label: 'Floor Plan', icon: FloorPlanIcon, module: 'tables', flagKey: 'tables' },
  { to: '/kitchen', label: 'Kitchen Display', icon: KitchenIcon, module: 'kitchen_display', flagKey: 'kitchen_display' },
  { to: '/franchise', label: 'Franchise', icon: FranchiseIcon, module: 'franchise', flagKey: 'franchise' },
  { to: '/branch-transfers', label: 'Branch Transfers', icon: InventoryIcon, module: 'branch_management', adminOnly: true },
  { to: '/staff-schedule', label: 'Staff Schedule', icon: ScheduleIcon, module: 'branch_management', adminOnly: true },
  { to: '/assets', label: 'Assets', icon: AssetsIcon, module: 'assets', flagKey: 'assets' },
  { to: '/compliance', label: 'Compliance', icon: ComplianceIcon, module: 'compliance_docs', flagKey: 'compliance_docs' },
  { to: '/loyalty', label: 'Loyalty', icon: LoyaltyIcon, module: 'loyalty', flagKey: 'loyalty' },
  { to: '/ecommerce', label: 'Ecommerce', icon: EcommerceIcon, module: 'ecommerce', flagKey: 'ecommerce' },
  { to: '/sms', label: 'SMS', icon: SmsIcon, module: 'sms', flagKey: 'sms' },
  { to: '/claims', label: 'Claims', icon: ClaimsIcon, module: 'customer_claims' },
  { to: '/accounting', label: 'Accounting', icon: AccountingIcon, module: 'accounting' },
  { to: '/banking/accounts', label: 'Banking', icon: BankingIcon, module: 'accounting' },
  { to: '/tax/gst-periods', label: 'Tax', icon: TaxIcon, module: 'accounting' },
  { to: '/notifications', label: 'Notifications', icon: NotificationsIcon },
  { to: '/data', label: 'Data', icon: DataIcon },
  { to: '/reports', label: 'Reports', icon: ReportsIcon },
  { to: '/settings', label: 'Settings', icon: SettingsIcon, adminOnly: true },
]

// Quick actions for the header dropdown
const quickActions: QuickAction[] = [
  { label: 'New Booking', path: '/bookings', icon: '📅', module: 'bookings', flagKey: 'bookings', state: { openNew: true } },
  { label: 'New Job Card', path: '/job-cards/new', icon: '🔧', module: 'jobs', flagKey: 'jobs' },
  { label: 'New Quote', path: '/quotes/new', icon: '📝', module: 'quotes', flagKey: 'quotes' },
  { label: 'New Invoice', path: '/invoices/new', icon: '🧾' },
  { label: 'New Customer', path: '/customers/new', icon: '👤' },
]

export function OrgLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [quickActionsOpen, setQuickActionsOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)
  const { settings, tradeFamily } = useTenant()
  const { isEnabled } = useModules()
  const isBranchModuleEnabled = isEnabled('branch_management')
  const { isGlobalAdmin, isBranchAdmin, user, logout } = useAuth()
  const { flags } = useFeatureFlags()
  const navigate = useNavigate()
  const location = useLocation()
  const branding = settings?.branding

  // Refresh the compliance badge count whenever the user navigates to /compliance.
  const [badgeRefreshKey, setBadgeRefreshKey] = useState(0)
  useEffect(() => {
    if (location.pathname.startsWith('/compliance')) {
      setBadgeRefreshKey((k) => k + 1)
    }
  }, [location.pathname])

  // Payment method enforcement — blocking/warning modals for org_admin
  const {
    showBlockingModal, showWarningModal, expiringMethod,
    dismissWarning, refetchStatus,
  } = usePaymentMethodEnforcement()

  // Active branch indicator state
  const { selectedBranchId: activeBranchId, branches: branchList, isBranchLocked } = useBranch()

  // Branch name for branch_admin badge
  // The branches array is empty for branch_admin (fetch is skipped due to RBAC),
  // so we show "My Branch" as a static indicator. The branch context is auto-locked.
  const branchAdminBranchName = isBranchAdmin ? 'My Branch' : null
  const activeBranchIndicator = useMemo(
    () => getActiveBranchIndicatorState(activeBranchId, branchList),
    [activeBranchId, branchList],
  )

  // "View as Org" mode for global admin
  const viewAsOrg = useMemo(() => {
    try {
      const raw = sessionStorage.getItem('admin_view_as_org')
      return raw ? JSON.parse(raw) as { id: string; name: string } : null
    } catch { return null }
  }, [])

  const handleBackToAdmin = () => {
    sessionStorage.removeItem('admin_view_as_org')
    navigate('/admin/organisations')
  }

  const userRole = user?.role

  const visibleNavItems = useMemo(
    () => navItems.filter((item) => {
      // Admin-only items hidden from non-admin roles
      if (item.adminOnly && userRole !== 'org_admin' && userRole !== 'global_admin') return false
      // Trade family gating — null tradeFamily treated as automotive for backward compat
      if (item.tradeFamily && (tradeFamily ?? 'automotive-transport') !== item.tradeFamily) return false
      // If the item has a module gate, module enablement is sufficient
      if (item.module) return isEnabled(item.module)
      // Items without a module gate fall back to feature flag check
      if (item.flagKey && !flags[item.flagKey]) return false
      return true
    }),
    [isEnabled, flags, userRole, tradeFamily],
  )

  const visibleQuickActions = useMemo(
    () => quickActions.filter((action) => {
      // If the action has a module gate, module enablement is sufficient
      if (action.module) return isEnabled(action.module)
      // Items without a module gate fall back to feature flag check
      if (action.flagKey && !flags[action.flagKey]) return false
      return true
    }),
    [isEnabled, flags],
  )

  const handleQuickAction = (path: string, state?: Record<string, unknown>) => {
    setQuickActionsOpen(false)
    navigate(path, state ? { state } : undefined)
  }

  const handleLogout = async () => {
    setUserMenuOpen(false)
    await logout()
    navigate('/login')
  }

  // Close user menu on outside click
  useEffect(() => {
    if (!userMenuOpen) return
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [userMenuOpen])

  return (
    <>
      <BlockingPaymentModal open={showBlockingModal} onSuccess={refetchStatus} />
      <ExpiringPaymentWarningModal
        open={showWarningModal && !showBlockingModal}
        expiringMethod={expiringMethod}
        onDismiss={dismissWarning}
      />
      <div className="flex h-screen overflow-hidden" style={{ backgroundColor: 'var(--content-bg)' }}>
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
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col transition-transform duration-200 ease-in-out lg:static lg:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ backgroundColor: 'var(--sidebar-bg)', borderRight: '1px solid var(--sidebar-border)' }}
        role="navigation"
        aria-label="Main navigation"
      >
        {/* Org branding */}
        <div className="flex h-16 items-center gap-3 px-4" style={{ borderBottom: '1px solid var(--sidebar-border)' }}>
          {(() => {
            const mode = branding?.sidebar_display_mode || 'icon_and_name'
            const hasLogo = !!branding?.logo_url
            const orgName = branding?.name || 'WorkshopPro'
            const showIcon = mode === 'icon_and_name' || mode === 'icon_only'
            const showName = mode === 'icon_and_name' || mode === 'name_only' || (mode === 'icon_only' && !hasLogo)
            const iconOnly = mode === 'icon_only' && hasLogo

            return (
              <>
                {showIcon && (
                  hasLogo ? (
                    <img
                      src={branding!.logo_url!}
                      alt={`${orgName} logo`}
                      className={`rounded-md object-contain shrink-0 ${iconOnly ? 'h-10 max-w-[160px]' : 'h-8 w-8'}`}
                    />
                  ) : (
                    <div
                      className={`rounded-md flex items-center justify-center text-white font-bold shrink-0 ${iconOnly ? 'h-10 w-10 text-lg' : 'h-8 w-8 text-sm'}`}
                      style={{ backgroundColor: 'var(--color-primary, #2563eb)' }}
                    >
                      {orgName.charAt(0).toUpperCase()}
                    </div>
                  )
                )}
                {showName && (
                  <span className="text-lg font-semibold truncate" style={{ color: 'var(--sidebar-text)' }}>
                    {orgName}
                  </span>
                )}
              </>
            )
          })()}
          <button
            className="ml-auto min-h-[44px] min-w-[44px] flex items-center justify-center lg:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 overflow-y-auto py-4 px-3">
          <ul className="space-y-1">
            {visibleNavItems.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  onClick={() => setSidebarOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 min-h-[44px] text-sm font-medium transition-all duration-[var(--transition-speed)] ${
                      isActive ? 'sidebar-nav-active' : 'sidebar-nav-item'
                    }`
                  }
                  style={({ isActive }) =>
                    isActive
                      ? { backgroundColor: 'var(--sidebar-active-bg)', color: 'var(--sidebar-active-text)', borderLeft: '3px solid var(--sidebar-active-border)' }
                      : { color: 'var(--sidebar-text)' }
                  }
                >
                  <item.icon />
                  {item.label}
                  {item.to === '/compliance' && (
                    <NotificationBadge refreshKey={badgeRefreshKey} />
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        {/* Version footer */}
        <div className="mt-auto px-4 py-2 text-xs" style={{ color: 'var(--sidebar-text)', opacity: 0.4 }}>
          v{__APP_VERSION__}
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
            <MenuIcon />
          </button>

          {/* Global search trigger */}
          <button
            className="hidden sm:flex items-center gap-2 rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 transition-colors"
            aria-label="Search"
            onClick={() => {
              // Dispatch Ctrl+K to trigger GlobalSearchBar
              document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))
            }}
          >
            <SearchIcon />
            <span>Search…</span>
            <kbd className="ml-4 rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-400">
              ⌘K
            </kbd>
          </button>

          {/* Branch selector — hidden when branch_management module disabled or branch_admin (locked to single branch) */}
          {isBranchModuleEnabled && !isBranchLocked && <BranchSelector />}

          {/* Static branch badge for branch_admin */}
          {isBranchModuleEnabled && isBranchAdmin && branchAdminBranchName && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 border border-blue-200 px-2.5 py-1 text-xs font-medium text-blue-700">
              <span className="h-2 w-2 rounded-full bg-blue-500" aria-hidden="true" />
              <span className="truncate max-w-[120px] sm:max-w-[200px]">{branchAdminBranchName}</span>
            </span>
          )}

          {/* Active branch indicator (non-branch_admin) */}
          {isBranchModuleEnabled && !isBranchAdmin && activeBranchIndicator.visible && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 border border-blue-200 px-2.5 py-1 text-xs font-medium text-blue-700">
              <span className="h-2 w-2 rounded-full bg-blue-500" aria-hidden="true" />
              <span className="truncate max-w-[120px] sm:max-w-[200px]">{activeBranchIndicator.branchName}</span>
            </span>
          )}

          <div className="flex-1" />

          {/* Quick Actions Dropdown */}
          {visibleQuickActions.length > 0 && (
            <div className="relative">
              <button
                onClick={() => setQuickActionsOpen(!quickActionsOpen)}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors min-h-[44px]"
                aria-label="Quick actions"
                aria-expanded={quickActionsOpen}
                aria-haspopup="true"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                <span className="hidden sm:inline">New</span>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {/* Dropdown menu */}
              {quickActionsOpen && (
                <>
                  {/* Backdrop */}
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setQuickActionsOpen(false)}
                    aria-hidden="true"
                  />
                  {/* Menu */}
                  <div className="absolute right-0 z-20 mt-2 w-56 rounded-lg border border-gray-200 bg-white shadow-lg">
                    <div className="py-1">
                      {visibleQuickActions.map((action) => (
                        <button
                          key={action.path}
                          onClick={() => handleQuickAction(action.path, action.state)}
                          className="flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors min-h-[44px]"
                        >
                          <span className="text-lg" aria-hidden="true">{action.icon}</span>
                          <span>{action.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {/* Notifications */}
          <button
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors"
            aria-label="Notifications"
            onClick={() => navigate('/notifications')}
          >
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
          </button>

          {/* User menu */}
          <div className="relative" ref={userMenuRef}>
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-full bg-gray-200 text-sm font-medium text-gray-700 hover:bg-gray-300"
              aria-label="User menu"
              aria-expanded={userMenuOpen}
              aria-haspopup="true"
            >
              {(user?.name ?? 'U').charAt(0).toUpperCase()}
            </button>

            {userMenuOpen && (
              <div className="absolute right-0 z-20 mt-2 w-56 rounded-lg border border-gray-200 bg-white shadow-lg">
                <div className="border-b border-gray-100 px-4 py-3">
                  <p className="text-sm font-medium text-gray-900 truncate">{user?.name ?? 'User'}</p>
                  <p className="text-xs text-gray-500 truncate">{user?.email}</p>
                </div>
                <div className="py-1">
                  <button
                    onClick={() => { setUserMenuOpen(false); navigate('/settings?tab=profile') }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors min-h-[44px]"
                  >
                    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                    </svg>
                    Profile
                  </button>
                  {(userRole === 'org_admin' || userRole === 'global_admin') && (
                  <button
                    onClick={() => { setUserMenuOpen(false); navigate('/settings') }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors min-h-[44px]"
                  >
                    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    Settings
                  </button>
                  )}
                  {(userRole === 'org_admin' || userRole === 'global_admin') && (
                  <button
                    onClick={() => { setUserMenuOpen(false); navigate('/setup-guide?rerun=true') }}
                    className="flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 transition-colors min-h-[44px]"
                  >
                    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                    </svg>
                    Setup Guide
                  </button>
                  )}
                  <button
                    onClick={handleLogout}
                    className="flex w-full items-center gap-3 px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors min-h-[44px]"
                  >
                    <svg className="h-4 w-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                    </svg>
                    Sign out
                  </button>
                </div>
              </div>
            )}
          </div>
        </header>

        {/* Page content */}
        {isGlobalAdmin && viewAsOrg && (
          <div className="bg-indigo-600 text-white px-4 py-2 flex items-center justify-between text-sm">
            <span>Viewing as organisation: <span className="font-semibold">{viewAsOrg.name}</span></span>
            <button
              onClick={handleBackToAdmin}
              className="rounded bg-white/20 px-3 py-1 text-sm font-medium hover:bg-white/30 transition-colors"
            >
              ← Back to Admin
            </button>
          </div>
        )}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6 min-h-0" role="main">
          <Outlet />
        </main>
      </div>

      {/* Global search overlay */}
      <GlobalSearchBar />
    </div>
    </>
  )
}

/* ── Inline SVG icon components ── */

function MenuIcon() {
  return (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
    </svg>
  )
}

function DashboardIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" />
    </svg>
  )
}

function CustomersIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

function VehiclesIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 17h8M8 17a2 2 0 11-4 0 2 2 0 014 0zm8 0a2 2 0 104 0 2 2 0 00-4 0zM3 11l2-6h14l2 6M3 11h18v6H3v-6z" />
    </svg>
  )
}

function InvoicesIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  )
}

function QuotesIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
    </svg>
  )
}

function JobCardsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
    </svg>
  )
}

function BookingsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  )
}

function InventoryIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
    </svg>
  )
}

function ReportsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

/* ── Additional nav icons ── */

function StaffIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
    </svg>
  )
}

function ProjectsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
    </svg>
  )
}

function ExpensesIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2z" />
    </svg>
  )
}

function TimeTrackingIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function ScheduleIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  )
}

function POSIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z" />
    </svg>
  )
}

function RecurringIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
    </svg>
  )
}

function PurchaseOrderIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
    </svg>
  )
}

function ConstructionIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    </svg>
  )
}

function FloorPlanIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
    </svg>
  )
}

function KitchenIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  )
}

function FranchiseIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

function AssetsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  )
}

function ComplianceIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  )
}

function LoyaltyIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function EcommerceIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
    </svg>
  )
}

function NotificationsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
    </svg>
  )
}

function DataIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
    </svg>
  )
}

function CatalogueIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
    </svg>
  )
}

function SmsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
    </svg>
  )
}

function ClaimsIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function AccountingIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4h16v16H4z" />
    </svg>
  )
}

function BankingIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
    </svg>
  )
}

function TaxIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z" />
    </svg>
  )
}
