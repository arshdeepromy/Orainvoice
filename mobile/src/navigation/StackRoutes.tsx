import { Suspense, lazy, useEffect, useRef } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { useAuth } from '@/contexts/AuthContext'

/**
 * Placeholder component for screens not yet implemented.
 */
function ScreenPlaceholder({ name }: { name: string }) {
  return (
    <div className="flex flex-1 items-center justify-center p-4 text-gray-500 dark:text-gray-400">
      <p>{name}</p>
    </div>
  )
}

/**
 * Loading fallback shown while lazy-loaded screens are being fetched.
 */
function ScreenLoader() {
  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Lazy-loaded screen imports
// ---------------------------------------------------------------------------

// Dashboard
const DashboardScreen = lazy(() =>
  import('@/screens/dashboard/DashboardScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Dashboard" />,
  })),
)

// Invoices
const InvoiceListScreen = lazy(() =>
  import('@/screens/invoices/InvoiceListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Invoices" />,
  })),
)
const InvoiceDetailScreen = lazy(() =>
  import('@/screens/invoices/InvoiceDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Invoice Detail" />,
  })),
)
const InvoiceCreateScreen = lazy(() =>
  import('@/screens/invoices/InvoiceCreateScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="New Invoice" />,
  })),
)
const InvoicePDFScreen = lazy(() =>
  import('@/screens/invoices/InvoicePDFScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Invoice PDF" />,
  })),
)

// Customers
const CustomerListScreen = lazy(() =>
  import('@/screens/customers/CustomerListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Customers" />,
  })),
)
const CustomerProfileScreen = lazy(() =>
  import('@/screens/customers/CustomerProfileScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Customer Profile" />,
  })),
)
const CustomerCreateScreen = lazy(() =>
  import('@/screens/customers/CustomerCreateScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="New Customer" />,
  })),
)
const CustomerEditScreen = lazy(() =>
  import('@/screens/customers/CustomerEditScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Edit Customer" />,
  })),
)

// Jobs
const JobListScreen = lazy(() =>
  import('@/screens/jobs/JobListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Jobs" />,
  })),
)
const JobBoardScreen = lazy(() =>
  import('@/screens/jobs/JobBoardScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Job Board" />,
  })),
)
const JobDetailScreen = lazy(() =>
  import('@/screens/jobs/JobDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Job Detail" />,
  })),
)
const JobCardListScreen = lazy(() =>
  import('@/screens/jobs/JobCardListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Job Cards" />,
  })),
)
const JobCardDetailScreen = lazy(() =>
  import('@/screens/jobs/JobCardDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Job Card Detail" />,
  })),
)
const JobCardCreateScreen = lazy(() =>
  import('@/screens/jobs/JobCardCreateScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="New Job Card" />,
  })),
)

// More menu
const MoreMenuScreen = lazy(() =>
  import('@/screens/more/MoreMenuScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="More" />,
  })),
)

// Quotes
const QuoteListScreen = lazy(() =>
  import('@/screens/quotes/QuoteListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Quotes" />,
  })),
)
const QuoteDetailScreen = lazy(() =>
  import('@/screens/quotes/QuoteDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Quote Detail" />,
  })),
)
const QuoteCreateScreen = lazy(() =>
  import('@/screens/quotes/QuoteCreateScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="New Quote" />,
  })),
)

// Inventory
const InventoryListScreen = lazy(() =>
  import('@/screens/inventory/InventoryListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Inventory" />,
  })),
)
const InventoryDetailScreen = lazy(() =>
  import('@/screens/inventory/InventoryDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Inventory Detail" />,
  })),
)
const CatalogueItemsScreen = lazy(() =>
  import('@/screens/inventory/CatalogueItemsScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Catalogue Items" />,
  })),
)

// Staff
const StaffListScreen = lazy(() =>
  import('@/screens/staff/StaffListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Staff" />,
  })),
)
const StaffDetailScreen = lazy(() =>
  import('@/screens/staff/StaffDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Staff Detail" />,
  })),
)

// Time Tracking
const TimeTrackingScreen = lazy(() =>
  import('@/screens/time-tracking/TimeTrackingScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Time Tracking" />,
  })),
)

// Expenses
const ExpenseListScreen = lazy(() =>
  import('@/screens/expenses/ExpenseListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Expenses" />,
  })),
)
const ExpenseCreateScreen = lazy(() =>
  import('@/screens/expenses/ExpenseCreateScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="New Expense" />,
  })),
)

// Bookings
const BookingCalendarScreen = lazy(() =>
  import('@/screens/bookings/BookingCalendarScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Bookings" />,
  })),
)
const BookingCreateScreen = lazy(() =>
  import('@/screens/bookings/BookingCreateScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="New Booking" />,
  })),
)

// Vehicles
const VehicleListScreen = lazy(() =>
  import('@/screens/vehicles/VehicleListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Vehicles" />,
  })),
)
const VehicleProfileScreen = lazy(() =>
  import('@/screens/vehicles/VehicleProfileScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Vehicle Profile" />,
  })),
)

// Accounting
const ChartOfAccountsScreen = lazy(() =>
  import('@/screens/accounting/ChartOfAccountsScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Chart of Accounts" />,
  })),
)
const JournalEntryListScreen = lazy(() =>
  import('@/screens/accounting/JournalEntryListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Journal Entries" />,
  })),
)
const JournalEntryDetailScreen = lazy(() =>
  import('@/screens/accounting/JournalEntryDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Journal Entry Detail" />,
  })),
)
const BankAccountsScreen = lazy(() =>
  import('@/screens/accounting/BankAccountsScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Bank Accounts" />,
  })),
)
const BankTransactionsScreen = lazy(() =>
  import('@/screens/accounting/BankTransactionsScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Bank Transactions" />,
  })),
)
const ReconciliationScreen = lazy(() =>
  import('@/screens/accounting/ReconciliationScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Reconciliation" />,
  })),
)
const GstPeriodsScreen = lazy(() =>
  import('@/screens/accounting/GstPeriodsScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="GST Periods" />,
  })),
)
const GstFilingDetailScreen = lazy(() =>
  import('@/screens/accounting/GstFilingDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="GST Filing Detail" />,
  })),
)
const TaxPositionScreen = lazy(() =>
  import('@/screens/accounting/TaxPositionScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Tax Position" />,
  })),
)

// Compliance
const ComplianceDashboardScreen = lazy(() =>
  import('@/screens/compliance/ComplianceDashboardScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Compliance" />,
  })),
)
const ComplianceUploadScreen = lazy(() =>
  import('@/screens/compliance/ComplianceUploadScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Upload Document" />,
  })),
)

// Reports
const ReportsMenuScreen = lazy(() =>
  import('@/screens/reports/ReportsMenuScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Reports" />,
  })),
)
const ReportViewScreen = lazy(() =>
  import('@/screens/reports/ReportViewScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Report" />,
  })),
)

// Notifications
const NotificationPreferencesScreen = lazy(() =>
  import('@/screens/notifications/NotificationPreferencesScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Notifications" />,
  })),
)

// POS
const POSScreen = lazy(() =>
  import('@/screens/pos/POSScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Point of Sale" />,
  })),
)

// Construction
const ProgressClaimListScreen = lazy(() =>
  import('@/screens/construction/ProgressClaimListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Progress Claims" />,
  })),
)
const VariationListScreen = lazy(() =>
  import('@/screens/construction/VariationListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Variations" />,
  })),
)
const RetentionSummaryScreen = lazy(() =>
  import('@/screens/construction/RetentionSummaryScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Retentions" />,
  })),
)
const ConstructionDetailScreen = lazy(() =>
  import('@/screens/construction/ConstructionDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Construction Detail" />,
  })),
)

// Franchise
const FranchiseDashboardScreen = lazy(() =>
  import('@/screens/franchise/FranchiseDashboardScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Franchise" />,
  })),
)

// Hospitality
const FloorPlanScreen = lazy(() =>
  import('@/screens/hospitality/FloorPlanScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Floor Plan" />,
  })),
)
const KitchenDisplayScreen = lazy(() =>
  import('@/screens/hospitality/KitchenDisplayScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Kitchen Display" />,
  })),
)

// Assets
const AssetListScreen = lazy(() =>
  import('@/screens/assets/AssetListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Assets" />,
  })),
)
const AssetDetailScreen = lazy(() =>
  import('@/screens/assets/AssetDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Asset Detail" />,
  })),
)
const LocationDetailScreen = lazy(() =>
  import('@/screens/franchise/LocationDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Location Detail" />,
  })),
)
const StockTransferListScreen = lazy(() =>
  import('@/screens/franchise/StockTransferListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Stock Transfers" />,
  })),
)

// Recurring
const RecurringListScreen = lazy(() =>
  import('@/screens/recurring/RecurringListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Recurring Invoices" />,
  })),
)
const RecurringDetailScreen = lazy(() =>
  import('@/screens/recurring/RecurringDetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Recurring Detail" />,
  })),
)

// Purchase Orders
const POListScreen = lazy(() =>
  import('@/screens/purchase-orders/POListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Purchase Orders" />,
  })),
)
const PODetailScreen = lazy(() =>
  import('@/screens/purchase-orders/PODetailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="PO Detail" />,
  })),
)

// Projects
const ProjectListScreen = lazy(() =>
  import('@/screens/projects/ProjectListScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Projects" />,
  })),
)
const ProjectDashboardScreen = lazy(() =>
  import('@/screens/projects/ProjectDashboardScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Project Dashboard" />,
  })),
)

// Schedule
const ScheduleCalendarScreen = lazy(() =>
  import('@/screens/schedule/ScheduleCalendarScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Schedule" />,
  })),
)

// SMS
const SMSComposeScreen = lazy(() =>
  import('@/screens/sms/SMSComposeScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="SMS" />,
  })),
)

// Settings
const SettingsScreen = lazy(() =>
  import('@/screens/settings/SettingsScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Settings" />,
  })),
)

// Portal
const PortalScreen = lazy(() =>
  import('@/screens/portal/PortalScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Portal" />,
  })),
)

// Kiosk
const KioskScreen = lazy(() =>
  import('@/screens/kiosk/KioskScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Kiosk" />,
  })),
)

// Auth screens
const LoginScreen = lazy(() =>
  import('@/screens/auth/LoginScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Login" />,
  })),
)
const MfaScreen = lazy(() =>
  import('@/screens/auth/MfaScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="MFA Verification" />,
  })),
)
const ForgotPasswordScreen = lazy(() =>
  import('@/screens/auth/ForgotPasswordScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Forgot Password" />,
  })),
)
const BiometricLockScreen = lazy(() =>
  import('@/screens/auth/BiometricLockScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Biometric Lock" />,
  })),
)
const SignupScreen = lazy(() =>
  import('@/screens/auth/SignupScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Sign Up" />,
  })),
)
const ResetPasswordScreen = lazy(() =>
  import('@/screens/auth/ResetPasswordScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Reset Password" />,
  })),
)
const VerifyEmailScreen = lazy(() =>
  import('@/screens/auth/VerifyEmailScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Verify Email" />,
  })),
)
const LandingScreen = lazy(() =>
  import('@/screens/auth/LandingScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Landing" />,
  })),
)
const PublicPaymentScreen = lazy(() =>
  import('@/screens/auth/PublicPaymentScreen').catch(() => ({
    default: () => <ScreenPlaceholder name="Payment" />,
  })),
)

// ---------------------------------------------------------------------------
// Scroll position preservation hook
// ---------------------------------------------------------------------------

/**
 * Preserves and restores scroll position when navigating within tab stacks.
 * Uses a ref map keyed by pathname to store scroll positions.
 */
function useScrollPreservation() {
  const location = useLocation()
  const scrollPositions = useRef<Map<string, number>>(new Map())

  useEffect(() => {
    // Save current scroll position before navigating away
    const saveScroll = () => {
      scrollPositions.current.set(location.pathname, window.scrollY)
    }

    // Restore scroll position for the current route
    const savedPosition = scrollPositions.current.get(location.pathname)
    if (savedPosition !== undefined) {
      // Use requestAnimationFrame to ensure DOM has rendered
      requestAnimationFrame(() => {
        window.scrollTo(0, savedPosition)
      })
    } else {
      window.scrollTo(0, 0)
    }

    // Save scroll on beforeunload and on next navigation
    window.addEventListener('beforeunload', saveScroll)
    return () => {
      saveScroll()
      window.removeEventListener('beforeunload', saveScroll)
    }
  }, [location.pathname])
}

/**
 * Auth guard — redirects to /login when the user is not authenticated.
 * Shows a loading spinner while the auth state is being restored.
 */
function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return <ScreenLoader />
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

/**
 * Redirect authenticated users away from auth screens (login, signup, etc.)
 * back to the dashboard.
 */
function GuestOnly({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return <ScreenLoader />
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}

// ---------------------------------------------------------------------------
// Stack Routes
// ---------------------------------------------------------------------------

/**
 * React Router stack routes for all tabs with lazy-loaded screen components
 * and scroll position preservation.
 *
 * Requirements: 1.2, 1.8
 */
export function StackRoutes() {
  useScrollPreservation()

  return (
    <ErrorBoundary>
    <Suspense fallback={<ScreenLoader />}>
      <Routes>
        {/* ── Public / Guest-only screens ─────────────────────────── */}
        <Route path="/login" element={<GuestOnly><LoginScreen /></GuestOnly>} />
        <Route path="/mfa-verify" element={<MfaScreen />} />
        <Route path="/forgot-password" element={<GuestOnly><ForgotPasswordScreen /></GuestOnly>} />
        <Route path="/biometric-lock" element={<BiometricLockScreen />} />
        <Route path="/signup" element={<GuestOnly><SignupScreen /></GuestOnly>} />
        <Route path="/reset-password" element={<GuestOnly><ResetPasswordScreen /></GuestOnly>} />
        <Route path="/verify-email" element={<VerifyEmailScreen />} />
        <Route path="/landing" element={<GuestOnly><LandingScreen /></GuestOnly>} />
        <Route path="/pay/:token" element={<PublicPaymentScreen />} />

        {/* ── Authenticated screens (all wrapped in AuthGuard) ────── */}
        <Route path="/" element={<AuthGuard><DashboardScreen /></AuthGuard>} />
        <Route path="/invoices" element={<AuthGuard><InvoiceListScreen /></AuthGuard>} />
        <Route path="/invoices/new" element={<AuthGuard><InvoiceCreateScreen /></AuthGuard>} />
        <Route path="/invoices/:id/edit" element={<AuthGuard><InvoiceCreateScreen /></AuthGuard>} />
        <Route path="/invoices/:id" element={<AuthGuard><InvoiceDetailScreen /></AuthGuard>} />
        <Route path="/invoices/:id/pdf" element={<AuthGuard><InvoicePDFScreen /></AuthGuard>} />
        <Route path="/customers" element={<AuthGuard><CustomerListScreen /></AuthGuard>} />
        <Route path="/customers/new" element={<AuthGuard><CustomerCreateScreen /></AuthGuard>} />
        <Route path="/customers/:id" element={<AuthGuard><CustomerProfileScreen /></AuthGuard>} />
        <Route path="/customers/:id/edit" element={<AuthGuard><CustomerEditScreen /></AuthGuard>} />
        <Route path="/jobs" element={<AuthGuard><JobListScreen /></AuthGuard>} />
        <Route path="/jobs/board" element={<AuthGuard><JobBoardScreen /></AuthGuard>} />
        <Route path="/jobs/:id" element={<AuthGuard><JobDetailScreen /></AuthGuard>} />
        <Route path="/jobs/cards" element={<AuthGuard><JobCardListScreen /></AuthGuard>} />
        <Route path="/jobs/cards/new" element={<AuthGuard><JobCardCreateScreen /></AuthGuard>} />
        <Route path="/jobs/cards/:id" element={<AuthGuard><JobCardDetailScreen /></AuthGuard>} />
        <Route path="/more" element={<AuthGuard><MoreMenuScreen /></AuthGuard>} />
        <Route path="/quotes" element={<AuthGuard><QuoteListScreen /></AuthGuard>} />
        <Route path="/quotes/new" element={<AuthGuard><QuoteCreateScreen /></AuthGuard>} />
        <Route path="/quotes/:id" element={<AuthGuard><QuoteDetailScreen /></AuthGuard>} />
        <Route path="/inventory" element={<AuthGuard><InventoryListScreen /></AuthGuard>} />
        <Route path="/inventory/:id" element={<AuthGuard><InventoryDetailScreen /></AuthGuard>} />
        <Route path="/items" element={<AuthGuard><CatalogueItemsScreen /></AuthGuard>} />
        <Route path="/staff" element={<AuthGuard><StaffListScreen /></AuthGuard>} />
        <Route path="/staff/:id" element={<AuthGuard><StaffDetailScreen /></AuthGuard>} />
        <Route path="/time-tracking" element={<AuthGuard><TimeTrackingScreen /></AuthGuard>} />
        <Route path="/expenses" element={<AuthGuard><ExpenseListScreen /></AuthGuard>} />
        <Route path="/expenses/new" element={<AuthGuard><ExpenseCreateScreen /></AuthGuard>} />
        <Route path="/bookings" element={<AuthGuard><BookingCalendarScreen /></AuthGuard>} />
        <Route path="/bookings/new" element={<AuthGuard><BookingCreateScreen /></AuthGuard>} />
        <Route path="/vehicles" element={<AuthGuard><VehicleListScreen /></AuthGuard>} />
        <Route path="/vehicles/:id" element={<AuthGuard><VehicleProfileScreen /></AuthGuard>} />
        <Route path="/accounting" element={<AuthGuard><ChartOfAccountsScreen /></AuthGuard>} />
        <Route path="/accounting/journals" element={<AuthGuard><JournalEntryListScreen /></AuthGuard>} />
        <Route path="/accounting/journals/:id" element={<AuthGuard><JournalEntryDetailScreen /></AuthGuard>} />
        <Route path="/banking" element={<AuthGuard><BankAccountsScreen /></AuthGuard>} />
        <Route path="/banking/:id/transactions" element={<AuthGuard><BankTransactionsScreen /></AuthGuard>} />
        <Route path="/banking/reconciliation" element={<AuthGuard><ReconciliationScreen /></AuthGuard>} />
        <Route path="/tax" element={<AuthGuard><GstPeriodsScreen /></AuthGuard>} />
        <Route path="/tax/:id" element={<AuthGuard><GstFilingDetailScreen /></AuthGuard>} />
        <Route path="/tax/position" element={<AuthGuard><TaxPositionScreen /></AuthGuard>} />
        <Route path="/compliance" element={<AuthGuard><ComplianceDashboardScreen /></AuthGuard>} />
        <Route path="/compliance/upload" element={<AuthGuard><ComplianceUploadScreen /></AuthGuard>} />
        <Route path="/reports" element={<AuthGuard><ReportsMenuScreen /></AuthGuard>} />
        <Route path="/reports/:type" element={<AuthGuard><ReportViewScreen /></AuthGuard>} />
        <Route path="/notifications" element={<AuthGuard><NotificationPreferencesScreen /></AuthGuard>} />
        <Route path="/pos" element={<AuthGuard><POSScreen /></AuthGuard>} />
        <Route path="/construction/claims" element={<AuthGuard><ProgressClaimListScreen /></AuthGuard>} />
        <Route path="/construction/variations" element={<AuthGuard><VariationListScreen /></AuthGuard>} />
        <Route path="/construction/retentions" element={<AuthGuard><RetentionSummaryScreen /></AuthGuard>} />
        <Route path="/construction/:id" element={<AuthGuard><ConstructionDetailScreen /></AuthGuard>} />
        <Route path="/franchise" element={<AuthGuard><FranchiseDashboardScreen /></AuthGuard>} />
        <Route path="/franchise/locations/:id" element={<AuthGuard><LocationDetailScreen /></AuthGuard>} />
        <Route path="/franchise/transfers" element={<AuthGuard><StockTransferListScreen /></AuthGuard>} />
        <Route path="/floor-plan" element={<AuthGuard><FloorPlanScreen /></AuthGuard>} />
        <Route path="/kitchen" element={<AuthGuard><KitchenDisplayScreen /></AuthGuard>} />
        <Route path="/assets" element={<AuthGuard><AssetListScreen /></AuthGuard>} />
        <Route path="/assets/:id" element={<AuthGuard><AssetDetailScreen /></AuthGuard>} />
        <Route path="/recurring" element={<AuthGuard><RecurringListScreen /></AuthGuard>} />
        <Route path="/recurring/:id" element={<AuthGuard><RecurringDetailScreen /></AuthGuard>} />
        <Route path="/purchase-orders" element={<AuthGuard><POListScreen /></AuthGuard>} />
        <Route path="/purchase-orders/:id" element={<AuthGuard><PODetailScreen /></AuthGuard>} />
        <Route path="/projects" element={<AuthGuard><ProjectListScreen /></AuthGuard>} />
        <Route path="/projects/:id" element={<AuthGuard><ProjectDashboardScreen /></AuthGuard>} />
        <Route path="/schedule" element={<AuthGuard><ScheduleCalendarScreen /></AuthGuard>} />
        <Route path="/sms" element={<AuthGuard><SMSComposeScreen /></AuthGuard>} />
        <Route path="/settings" element={<AuthGuard><SettingsScreen /></AuthGuard>} />
        <Route path="/portal" element={<AuthGuard><PortalScreen /></AuthGuard>} />
        <Route path="/kiosk" element={<AuthGuard><KioskScreen /></AuthGuard>} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Suspense>
    </ErrorBoundary>
  )
}
