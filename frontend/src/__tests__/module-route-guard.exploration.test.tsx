import { render, screen, cleanup } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

/**
 * Bug Condition Exploration Test — Module Route Guard Bypass
 *
 * Property 1: Bug Condition — Disabled Module Routes Are Blocked
 * FOR ALL input WHERE isBugCondition(input):
 *   renderRoute(input.route) contains "Feature not available"
 *   AND NOT contains modulePageContent
 *
 * **Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**
 *
 * EXPECTED: These tests FAIL on unfixed code — failure confirms the bug exists.
 * The bug: AppRoutes renders all module routes unconditionally without checking
 * ModuleContext.isEnabled(), so disabled modules are still accessible via direct URL.
 */

/* ------------------------------------------------------------------ */
/*  Mocks — Contexts                                                   */
/* ------------------------------------------------------------------ */

// Mock ModuleContext: all modules disabled
vi.mock('@/contexts/ModuleContext', () => ({
  ModuleProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useModules: () => ({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isEnabled: () => false, // ALL modules disabled
    refetch: vi.fn(),
  }),
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
/*  Each renders identifiable text so we can detect if the page        */
/*  content renders instead of FeatureNotAvailable                     */
/* ------------------------------------------------------------------ */

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

/* Mock non-module pages (core routes, auth, etc.) to avoid import errors */
vi.mock('@/pages/dashboard', () => ({ Dashboard: () => <div>Dashboard</div> }))
vi.mock('@/pages/customers/CustomerList', () => ({ default: () => <div>CustomerList</div> }))
vi.mock('@/pages/customers/CustomerCreate', () => ({ default: () => <div>CustomerCreate</div> }))
vi.mock('@/pages/customers/CustomerProfile', () => ({ default: () => <div>CustomerProfile</div> }))
vi.mock('@/pages/invoices/InvoiceList', () => ({ default: () => <div>InvoiceList</div> }))
vi.mock('@/pages/invoices/InvoiceCreate', () => ({ default: () => <div>InvoiceCreate</div> }))
vi.mock('@/pages/reports/ReportsPage', () => ({ default: () => <div>ReportsPage</div> }))
vi.mock('@/pages/settings/Settings', () => ({ Settings: () => <div>OrgSettingsPage</div> }))
vi.mock('@/pages/notifications/NotificationsPage', () => ({ default: () => <div>NotificationsPage</div> }))
vi.mock('@/pages/data/DataPage', () => ({ default: () => <div>DataPage</div> }))
vi.mock('@/pages/items/ItemsPage', () => ({ default: () => <div>ItemsPage</div> }))
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


/* ------------------------------------------------------------------ */
/*  Import App after all mocks are set up                              */
/* ------------------------------------------------------------------ */

// We import the AppRoutes indirectly through App — but since App wraps
// everything in providers, and we've mocked all providers, we need to
// import the module and render AppRoutes directly.
// However, AppRoutes is not exported. We'll import App and render it
// within a MemoryRouter (replacing BrowserRouter).

// Actually, App uses BrowserRouter internally. We need to mock that too
// or import AppRoutes. Let's mock react-router-dom's BrowserRouter to
// pass through children, and use MemoryRouter at the test level.

// Simpler approach: We'll re-export AppRoutes by importing the App module
// and extracting the routes. But AppRoutes is a local function.
// Best approach: render the full <App /> but mock BrowserRouter to be MemoryRouter.

// We need to handle this carefully. Let's mock the BrowserRouter.

/* ------------------------------------------------------------------ */
/*  Test cases                                                         */
/* ------------------------------------------------------------------ */

/**
 * Route-to-module mapping for the 6 test cases specified in the task.
 * Each entry: [route, moduleSlug, expectedPageContent]
 */
const BUG_CONDITION_CASES: Array<{
  route: string
  moduleSlug: string
  pageContent: string
  description: string
}> = [
  { route: '/vehicles', moduleSlug: 'vehicles', pageContent: 'VehicleList', description: 'vehicles module disabled → should show FeatureNotAvailable, not VehicleList' },
  { route: '/pos', moduleSlug: 'pos', pageContent: 'POSScreen', description: 'pos module disabled → should show FeatureNotAvailable, not POSScreen' },
  { route: '/franchise', moduleSlug: 'franchise', pageContent: 'FranchiseDashboard', description: 'franchise module disabled → should show FeatureNotAvailable, not FranchiseDashboard' },
  { route: '/kitchen', moduleSlug: 'kitchen_display', pageContent: 'KitchenDisplay', description: 'kitchen_display module disabled → should show FeatureNotAvailable, not KitchenDisplay' },
  { route: '/jobs', moduleSlug: 'jobs', pageContent: 'JobsPage', description: 'jobs module disabled → should show FeatureNotAvailable, not JobsPage' },
  { route: '/accounting', moduleSlug: 'accounting', pageContent: 'ChartOfAccounts', description: 'accounting module disabled → should show FeatureNotAvailable, not ChartOfAccounts' },
]

// Dynamically import App — we need to handle the BrowserRouter issue
// Since App.tsx uses BrowserRouter, we can't nest it inside MemoryRouter.
// Instead, we'll directly test the route rendering by importing App
// and mocking BrowserRouter to just render children.

// Override BrowserRouter to be a passthrough so we can control routing via MemoryRouter
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    BrowserRouter: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  }
})

// Now import App — BrowserRouter is mocked, so we wrap with MemoryRouter in tests
import App from '@/App'

describe('Bug Condition Exploration: Disabled module routes render page content (BUG)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  it.each(BUG_CONDITION_CASES)(
    '$description',
    async ({ route, pageContent }) => {
      render(
        <MemoryRouter initialEntries={[route]}>
          <App />
        </MemoryRouter>,
      )

      // Expected behavior (post-fix): FeatureNotAvailable should render
      // On UNFIXED code, this will FAIL because the module page renders instead
      const featureNotAvailable = await screen.findByTestId('feature-not-available', {}, { timeout: 3000 }).catch(() => null)
      expect(featureNotAvailable).not.toBeNull()

      // The module page content should NOT be present
      expect(screen.queryByText(pageContent)).not.toBeInTheDocument()
    },
  )
})
