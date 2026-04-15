import { render, screen, cleanup } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'
import * as fc from 'fast-check'

/**
 * Preservation Property Tests — Module Route Guard Bypass
 *
 * Property 2: Preservation — Enabled Modules and Core Routes Render Normally
 *
 * These tests verify that:
 * - Core routes render regardless of module enablement state
 * - Module-gated routes render when their module is enabled
 *
 * **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
 *
 * EXPECTED: These tests PASS on unfixed code (confirms baseline behavior to preserve).
 */

/* ------------------------------------------------------------------ */
/*  Mocks — Contexts                                                   */
/* ------------------------------------------------------------------ */

// ModuleContext mock — will be overridden per-test via mockImplementation
const mockUseModules = vi.fn()

vi.mock('@/contexts/ModuleContext', () => ({
  ModuleProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useModules: () => mockUseModules(),
}))

vi.mock('@/contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    user: { id: '1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
    isLoading: false,
    mfaPending: false,
    mfaSessionToken: null,
    login: vi.fn(),
    loginWithGoogle: vi.fn(),
    loginWithPasskey: vi.fn(),
    logout: vi.fn(),
    completeMfa: vi.fn(),
    isGlobalAdmin: false,
    isOrgAdmin: true,
    isBranchAdmin: false,
    isSalesperson: false,
    isKiosk: false,
  }),
}))

vi.mock('@/contexts/TenantContext', () => ({
  TenantProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useTenant: () => ({
    settings: {
      branding: { name: 'Test Org', logo_url: null, primary_colour: '#2563eb', secondary_colour: '#1e40af', address: null, phone: null, email: null, sidebar_display_mode: 'icon_and_name' },
      gst: { gst_number: null, gst_percentage: 15, gst_inclusive: true },
      invoice: { prefix: 'INV', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    tradeFamily: 'automotive-transport',
    tradeCategory: 'general-automotive',
  }),
}))

vi.mock('@/contexts/BranchContext', () => ({
  BranchProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useBranch: () => ({
    selectedBranchId: null,
    branches: [],
    selectBranch: vi.fn(),
    isLoading: false,
    isBranchLocked: false,
  }),
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  FeatureFlagProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useFeatureFlags: () => ({
    flags: {},
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useFlag: () => true,
}))

vi.mock('@/contexts/LocaleContext', () => ({
  LocaleProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useLocale: () => ({ locale: 'en-NZ', currency: 'NZD', setLocale: vi.fn() }),
}))

vi.mock('@/contexts/PlatformBrandingContext', () => ({
  PlatformBrandingProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePlatformBranding: () => ({ platformName: 'OraInvoice', logoUrl: null }),
}))

vi.mock('@/contexts/ThemeContext', () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

vi.mock('@/api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn() },
}))

/* ------------------------------------------------------------------ */
/*  Mocks — Lazy-loaded page components                                */
/* ------------------------------------------------------------------ */

// Core route pages
vi.mock('@/pages/dashboard', () => ({ Dashboard: () => <div>Dashboard</div> }))
vi.mock('@/pages/invoices/InvoiceList', () => ({ default: () => <div>InvoiceList</div> }))
vi.mock('@/pages/invoices/InvoiceCreate', () => ({ default: () => <div>InvoiceCreate</div> }))
vi.mock('@/pages/customers/CustomerList', () => ({ default: () => <div>CustomerList</div> }))
vi.mock('@/pages/customers/CustomerCreate', () => ({ default: () => <div>CustomerCreate</div> }))
vi.mock('@/pages/customers/CustomerProfile', () => ({ default: () => <div>CustomerProfile</div> }))
vi.mock('@/pages/settings/Settings', () => ({ Settings: () => <div>OrgSettingsPage</div> }))
vi.mock('@/pages/reports/ReportsPage', () => ({ default: () => <div>ReportsPage</div> }))
vi.mock('@/pages/notifications/NotificationsPage', () => ({ default: () => <div>NotificationsPage</div> }))
vi.mock('@/pages/data/DataPage', () => ({ default: () => <div>DataPage</div> }))
vi.mock('@/pages/items/ItemsPage', () => ({ default: () => <div>ItemsPage</div> }))

// Module-gated pages
vi.mock('@/pages/vehicles/VehicleList', () => ({ default: () => <div>VehicleList</div> }))
vi.mock('@/pages/vehicles/VehicleProfile', () => ({ default: () => <div>VehicleProfile</div> }))
vi.mock('@/pages/pos/POSScreen', () => ({ default: () => <div>POSScreen</div> }))
vi.mock('@/pages/franchise/FranchiseDashboard', () => ({ default: () => <div>FranchiseDashboard</div> }))
vi.mock('@/pages/franchise/LocationList', () => ({ default: () => <div>LocationList</div> }))
vi.mock('@/pages/franchise/StockTransfers', () => ({ default: () => <div>StockTransfers</div> }))
vi.mock('@/pages/franchise/LocationDetail', () => ({ default: () => <div>LocationDetail</div> }))
vi.mock('@/pages/kitchen/KitchenDisplay', () => ({ default: () => <div>KitchenDisplay</div> }))
vi.mock('@/pages/jobs/JobsPage', () => ({ default: () => <div>JobsPage</div> }))
vi.mock('@/pages/jobs/JobBoard', () => ({ default: () => <div>JobBoard</div> }))
vi.mock('@/pages/jobs/JobDetail', () => ({ default: () => <div>JobDetail</div> }))
vi.mock('@/pages/accounting/ChartOfAccounts', () => ({ default: () => <div>ChartOfAccounts</div> }))
vi.mock('@/pages/accounting/JournalEntries', () => ({ default: () => <div>JournalEntries</div> }))
vi.mock('@/pages/accounting/JournalEntryDetail', () => ({ default: () => <div>JournalEntryDetail</div> }))
vi.mock('@/pages/accounting/AccountingPeriods', () => ({ default: () => <div>AccountingPeriods</div> }))
vi.mock('@/pages/quotes/QuoteList', () => ({ default: () => <div>QuoteList</div> }))
vi.mock('@/pages/quotes/QuoteCreate', () => ({ default: () => <div>QuoteCreate</div> }))
vi.mock('@/pages/quotes/QuoteDetail', () => ({ default: () => <div>QuoteDetail</div> }))
vi.mock('@/pages/job-cards/JobCardList', () => ({ default: () => <div>JobCardList</div> }))
vi.mock('@/pages/job-cards/JobCardCreate', () => ({ default: () => <div>JobCardCreate</div> }))
vi.mock('@/pages/job-cards/JobCardDetail', () => ({ default: () => <div>JobCardDetail</div> }))
vi.mock('@/pages/bookings/BookingCalendarPage', () => ({ default: () => <div>BookingCalendarPage</div> }))
vi.mock('@/pages/inventory/InventoryPage', () => ({ default: () => <div>InventoryPage</div> }))
vi.mock('@/pages/staff/StaffList', () => ({ default: () => <div>StaffList</div> }))
vi.mock('@/pages/staff/StaffDetail', () => ({ default: () => <div>StaffDetail</div> }))
vi.mock('@/pages/projects/ProjectList', () => ({ default: () => <div>ProjectList</div> }))
vi.mock('@/pages/projects/ProjectDashboard', () => ({ default: () => <div>ProjectDashboard</div> }))
vi.mock('@/pages/expenses/ExpenseList', () => ({ default: () => <div>ExpenseList</div> }))
vi.mock('@/pages/time-tracking/TimeSheet', () => ({ default: () => <div>TimeSheet</div> }))
vi.mock('@/pages/schedule/ScheduleCalendar', () => ({ default: () => <div>ScheduleCalendar</div> }))
vi.mock('@/pages/recurring/RecurringList', () => ({ default: () => <div>RecurringList</div> }))
vi.mock('@/pages/purchase-orders/POList', () => ({ default: () => <div>POList</div> }))
vi.mock('@/pages/purchase-orders/PODetail', () => ({ default: () => <div>PODetail</div> }))
vi.mock('@/pages/construction/ProgressClaimList', () => ({ default: () => <div>ProgressClaimList</div> }))
vi.mock('@/pages/construction/VariationList', () => ({ default: () => <div>VariationList</div> }))
vi.mock('@/pages/construction/RetentionSummary', () => ({ default: () => <div>RetentionSummary</div> }))
vi.mock('@/pages/floor-plan/FloorPlan', () => ({ default: () => <div>FloorPlan</div> }))
vi.mock('@/pages/assets/AssetList', () => ({ default: () => <div>AssetList</div> }))
vi.mock('@/pages/assets/AssetDetail', () => ({ default: () => <div>AssetDetail</div> }))
vi.mock('@/pages/compliance/ComplianceDashboard', () => ({ default: () => <div>ComplianceDashboard</div> }))
vi.mock('@/pages/loyalty/LoyaltyConfig', () => ({ default: () => <div>LoyaltyConfig</div> }))
vi.mock('@/pages/ecommerce/WooCommerceSetup', () => ({ default: () => <div>WooCommerceSetup</div> }))
vi.mock('@/pages/catalogue/CataloguePage', () => ({ default: () => <div>CataloguePage</div> }))
vi.mock('@/pages/claims/ClaimsList', () => ({ default: () => <div>ClaimsList</div> }))
vi.mock('@/pages/claims/ClaimDetail', () => ({ default: () => <div>ClaimDetail</div> }))
vi.mock('@/pages/claims/ClaimCreateForm', () => ({ default: () => <div>ClaimCreateForm</div> }))
vi.mock('@/pages/claims/ClaimsReports', () => ({ default: () => <div>ClaimsReports</div> }))
vi.mock('@/pages/reports/ProfitAndLoss', () => ({ default: () => <div>ProfitAndLoss</div> }))
vi.mock('@/pages/reports/BalanceSheet', () => ({ default: () => <div>BalanceSheet</div> }))
vi.mock('@/pages/reports/AgedReceivables', () => ({ default: () => <div>AgedReceivables</div> }))
vi.mock('@/pages/tax/GstPeriods', () => ({ default: () => <div>GstPeriods</div> }))
vi.mock('@/pages/tax/GstFilingDetail', () => ({ default: () => <div>GstFilingDetail</div> }))
vi.mock('@/pages/tax/TaxWallets', () => ({ default: () => <div>TaxWallets</div> }))
vi.mock('@/pages/tax/TaxPosition', () => ({ default: () => <div>TaxPosition</div> }))
vi.mock('@/pages/banking/BankAccounts', () => ({ default: () => <div>BankAccounts</div> }))
vi.mock('@/pages/banking/BankTransactions', () => ({ default: () => <div>BankTransactions</div> }))
vi.mock('@/pages/banking/ReconciliationDashboard', () => ({ default: () => <div>ReconciliationDashboard</div> }))
vi.mock('@/pages/inventory/StockTransfers', () => ({ default: () => <div>BranchStockTransfers</div> }))
vi.mock('@/pages/scheduling/StaffSchedule', () => ({ default: () => <div>StaffSchedule</div> }))
vi.mock('@/pages/setup/SetupWizard', () => ({ SetupWizard: () => <div>SetupWizard</div> }))
vi.mock('@/pages/onboarding/OnboardingWizard', () => ({ OnboardingWizard: () => <div>OnboardingWizard</div> }))
vi.mock('@/pages/kiosk/KioskPage', () => ({ default: () => <div>KioskPage</div> }))
vi.mock('@/pages/portal/PortalPage', () => ({ PortalPage: () => <div>PortalPage</div> }))
vi.mock('@/pages/auth', () => ({
  Login: () => <div>Login</div>,
  MfaVerify: () => <div>MfaVerify</div>,
  PasswordResetRequest: () => <div>PasswordResetRequest</div>,
  PasswordResetComplete: () => <div>PasswordResetComplete</div>,
  VerifyEmail: () => <div>VerifyEmail</div>,
}))
vi.mock('@/pages/auth/SignupWizard', () => ({ SignupWizard: () => <div>SignupWizard</div> }))

/* Mock admin pages */
vi.mock('@/pages/admin/Organisations', () => ({ Organisations: () => <div>Organisations</div> }))
vi.mock('@/pages/admin/AnalyticsDashboard', () => ({ AnalyticsDashboard: () => <div>AnalyticsDashboard</div> }))
vi.mock('@/pages/admin/Settings', () => ({ Settings: () => <div>AdminSettings</div> }))
vi.mock('@/pages/admin/ErrorLog', () => ({ ErrorLog: () => <div>ErrorLog</div> }))
vi.mock('@/pages/admin/NotificationManager', () => ({ default: () => <div>NotificationManager</div> }))
vi.mock('@/pages/admin/BrandingConfig', () => ({ BrandingConfig: () => <div>BrandingConfig</div> }))
vi.mock('@/pages/admin/MigrationTool', () => ({ MigrationTool: () => <div>MigrationTool</div> }))
vi.mock('@/pages/admin/LiveMigrationTool', () => ({ LiveMigrationTool: () => <div>LiveMigrationTool</div> }))
vi.mock('@/pages/admin/HAReplication', () => ({ HAReplication: () => <div>HAReplication</div> }))
vi.mock('@/pages/admin/AuditLog', () => ({ AuditLog: () => <div>AuditLog</div> }))
vi.mock('@/pages/admin/Reports', () => ({ Reports: () => <div>AdminReports</div> }))
vi.mock('@/pages/admin/Integrations', () => ({ Integrations: () => <div>Integrations</div> }))
vi.mock('@/pages/admin/UserManagement', () => ({ UserManagement: () => <div>UserManagement</div> }))
vi.mock('@/pages/admin/SubscriptionPlans', () => ({ SubscriptionPlans: () => <div>SubscriptionPlans</div> }))
vi.mock('@/pages/admin/FeatureFlags', () => ({ FeatureFlags: () => <div>FeatureFlags</div> }))
vi.mock('@/pages/admin/GlobalAdminProfile', () => ({ GlobalAdminProfile: () => <div>GlobalAdminProfile</div> }))
vi.mock('@/pages/admin/TradeFamilies', () => ({ default: () => <div>TradeFamilies</div> }))
vi.mock('@/pages/admin/GlobalBranchOverview', () => ({ default: () => <div>GlobalBranchOverview</div> }))

/* Mock layout components */
vi.mock('@/layouts/AdminLayout', () => ({ AdminLayout: () => <div>AdminLayout</div> }))
vi.mock('@/layouts/OrgLayout', () => {
  const { Outlet } = require('react-router-dom')
  return { OrgLayout: () => <Outlet /> }
})

/* Mock UI components */
vi.mock('@/components/ui', () => ({
  Spinner: ({ label }: { label?: string }) => <div>{label ?? 'Loading'}</div>,
}))
vi.mock('@/components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

/* Override BrowserRouter to passthrough — we control routing via MemoryRouter */
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    BrowserRouter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  }
})

/* ------------------------------------------------------------------ */
/*  Import App after all mocks                                         */
/* ------------------------------------------------------------------ */
import App from '@/App'

/* ------------------------------------------------------------------ */
/*  Test data                                                          */
/* ------------------------------------------------------------------ */

/** All known module slugs used in the app */
const ALL_MODULE_SLUGS = [
  'vehicles', 'quotes', 'jobs', 'bookings', 'inventory', 'staff',
  'projects', 'expenses', 'time_tracking', 'pos', 'scheduling',
  'recurring_invoices', 'purchase_orders', 'progress_claims',
  'variations', 'retentions', 'tables', 'kitchen_display', 'franchise',
  'assets', 'compliance_docs', 'loyalty', 'ecommerce', 'catalogue',
  'customer_claims', 'accounting', 'branch_management',
] as const

/** Core routes that should render regardless of module enablement */
const CORE_ROUTES: Array<{ route: string; pageContent: string }> = [
  { route: '/dashboard', pageContent: 'Dashboard' },
  { route: '/invoices', pageContent: 'InvoiceList' },
  { route: '/customers', pageContent: 'CustomerList' },
  { route: '/settings', pageContent: 'OrgSettingsPage' },
  { route: '/reports', pageContent: 'ReportsPage' },
  { route: '/notifications', pageContent: 'NotificationsPage' },
  { route: '/data', pageContent: 'DataPage' },
]

/** Module-gated routes — one representative route per module */
const MODULE_ROUTES: Array<{ route: string; moduleSlug: string; pageContent: string }> = [
  { route: '/vehicles', moduleSlug: 'vehicles', pageContent: 'VehicleList' },
  { route: '/pos', moduleSlug: 'pos', pageContent: 'POSScreen' },
  { route: '/franchise', moduleSlug: 'franchise', pageContent: 'FranchiseDashboard' },
]

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Build a useModules mock that enables a specific set of module slugs */
function buildModuleMock(enabledSlugs: Set<string>) {
  return () => ({
    modules: [],
    enabledModules: [...enabledSlugs],
    isLoading: false,
    error: null,
    isEnabled: (slug: string) => enabledSlugs.has(slug),
    refetch: vi.fn(),
  })
}

/** fast-check arbitrary: random subset of module slugs */
const arbModuleSubset = fc.subarray([...ALL_MODULE_SLUGS], { minLength: 0 })

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('Preservation: Core routes render regardless of module enablement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  /**
   * Property: For ALL core routes and ANY module enablement state,
   * the core page component renders normally.
   *
   * **Validates: Requirements 3.2**
   */
  it.each(CORE_ROUTES)(
    'core route $route renders $pageContent regardless of module state',
    async ({ route, pageContent }) => {
      await fc.assert(
        fc.asyncProperty(arbModuleSubset, async (enabledSlugs) => {
          cleanup()
          mockUseModules.mockImplementation(buildModuleMock(new Set(enabledSlugs)))

          render(
            <MemoryRouter initialEntries={[route]}>
              <App />
            </MemoryRouter>,
          )

          const el = await screen.findByText(pageContent, {}, { timeout: 3000 })
          expect(el).toBeInTheDocument()

          // Core routes should never show FeatureNotAvailable
          expect(screen.queryByTestId('feature-not-available')).not.toBeInTheDocument()
        }),
        { numRuns: 5 },
      )
    },
  )
})

describe('Preservation: Enabled module routes render normally', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  /**
   * Property: For ALL module-gated routes where isEnabled(moduleSlug) returns true,
   * the module page component renders normally.
   *
   * **Validates: Requirements 3.1**
   */
  it.each(MODULE_ROUTES)(
    'enabled module route $route renders $pageContent when $moduleSlug is enabled',
    async ({ route, moduleSlug, pageContent }) => {
      await fc.assert(
        fc.asyncProperty(arbModuleSubset, async (extraEnabledSlugs) => {
          cleanup()
          // Always include the target module slug as enabled
          const enabledSet = new Set([...extraEnabledSlugs, moduleSlug])
          mockUseModules.mockImplementation(buildModuleMock(enabledSet))

          render(
            <MemoryRouter initialEntries={[route]}>
              <App />
            </MemoryRouter>,
          )

          const el = await screen.findByText(pageContent, {}, { timeout: 3000 })
          expect(el).toBeInTheDocument()

          // Enabled module routes should not show FeatureNotAvailable
          expect(screen.queryByTestId('feature-not-available')).not.toBeInTheDocument()
        }),
        { numRuns: 5 },
      )
    },
  )
})
