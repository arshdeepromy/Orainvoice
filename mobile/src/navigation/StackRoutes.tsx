import { Suspense, lazy, useEffect, useRef } from 'react'
import { Routes, Route, useLocation } from 'react-router-dom'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'

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
        {/* Auth screens (outside tab navigator) */}
        <Route path="/login" element={<LoginScreen />} />
        <Route path="/mfa-verify" element={<MfaScreen />} />
        <Route path="/forgot-password" element={<ForgotPasswordScreen />} />
        <Route path="/biometric-lock" element={<BiometricLockScreen />} />

        {/* Dashboard tab */}
        <Route path="/" element={<DashboardScreen />} />

        {/* Invoices tab stack */}
        <Route path="/invoices" element={<InvoiceListScreen />} />
        <Route path="/invoices/new" element={<InvoiceCreateScreen />} />
        <Route path="/invoices/:id" element={<InvoiceDetailScreen />} />
        <Route path="/invoices/:id/pdf" element={<InvoicePDFScreen />} />

        {/* Customers tab stack */}
        <Route path="/customers" element={<CustomerListScreen />} />
        <Route path="/customers/new" element={<CustomerCreateScreen />} />
        <Route path="/customers/:id" element={<CustomerProfileScreen />} />

        {/* Jobs tab stack */}
        <Route path="/jobs" element={<JobListScreen />} />
        <Route path="/jobs/board" element={<JobBoardScreen />} />
        <Route path="/jobs/:id" element={<JobDetailScreen />} />
        <Route path="/jobs/cards" element={<JobCardListScreen />} />
        <Route path="/jobs/cards/:id" element={<JobCardDetailScreen />} />

        {/* More menu */}
        <Route path="/more" element={<MoreMenuScreen />} />

        {/* Quotes */}
        <Route path="/quotes" element={<QuoteListScreen />} />
        <Route path="/quotes/new" element={<QuoteCreateScreen />} />
        <Route path="/quotes/:id" element={<QuoteDetailScreen />} />

        {/* Inventory */}
        <Route path="/inventory" element={<InventoryListScreen />} />
        <Route path="/inventory/:id" element={<InventoryDetailScreen />} />

        {/* Staff */}
        <Route path="/staff" element={<StaffListScreen />} />
        <Route path="/staff/:id" element={<StaffDetailScreen />} />

        {/* Time Tracking */}
        <Route path="/time-tracking" element={<TimeTrackingScreen />} />

        {/* Expenses */}
        <Route path="/expenses" element={<ExpenseListScreen />} />
        <Route path="/expenses/new" element={<ExpenseCreateScreen />} />

        {/* Bookings */}
        <Route path="/bookings" element={<BookingCalendarScreen />} />
        <Route path="/bookings/new" element={<BookingCreateScreen />} />

        {/* Vehicles (automotive) */}
        <Route path="/vehicles" element={<VehicleListScreen />} />
        <Route path="/vehicles/:id" element={<VehicleProfileScreen />} />

        {/* Accounting */}
        <Route path="/accounting" element={<ChartOfAccountsScreen />} />
        <Route path="/accounting/journals" element={<JournalEntryListScreen />} />
        <Route path="/accounting/journals/:id" element={<JournalEntryDetailScreen />} />

        {/* Banking */}
        <Route path="/banking" element={<BankAccountsScreen />} />
        <Route path="/banking/:id/transactions" element={<BankTransactionsScreen />} />
        <Route path="/banking/reconciliation" element={<ReconciliationScreen />} />

        {/* Tax / GST */}
        <Route path="/tax" element={<GstPeriodsScreen />} />
        <Route path="/tax/:id" element={<GstFilingDetailScreen />} />
        <Route path="/tax/position" element={<TaxPositionScreen />} />

        {/* Compliance */}
        <Route path="/compliance" element={<ComplianceDashboardScreen />} />
        <Route path="/compliance/upload" element={<ComplianceUploadScreen />} />

        {/* Reports */}
        <Route path="/reports" element={<ReportsMenuScreen />} />
        <Route path="/reports/:type" element={<ReportViewScreen />} />

        {/* Notifications */}
        <Route path="/notifications" element={<NotificationPreferencesScreen />} />

        {/* POS */}
        <Route path="/pos" element={<POSScreen />} />

        {/* Construction */}
        <Route path="/construction/claims" element={<ProgressClaimListScreen />} />
        <Route path="/construction/variations" element={<VariationListScreen />} />
        <Route path="/construction/retentions" element={<RetentionSummaryScreen />} />
        <Route path="/construction/:id" element={<ConstructionDetailScreen />} />

        {/* Franchise */}
        <Route path="/franchise" element={<FranchiseDashboardScreen />} />
        <Route path="/franchise/locations/:id" element={<LocationDetailScreen />} />
        <Route path="/franchise/transfers" element={<StockTransferListScreen />} />

        {/* Recurring Invoices */}
        <Route path="/recurring" element={<RecurringListScreen />} />
        <Route path="/recurring/:id" element={<RecurringDetailScreen />} />

        {/* Purchase Orders */}
        <Route path="/purchase-orders" element={<POListScreen />} />
        <Route path="/purchase-orders/:id" element={<PODetailScreen />} />

        {/* Projects */}
        <Route path="/projects" element={<ProjectListScreen />} />
        <Route path="/projects/:id" element={<ProjectDashboardScreen />} />

        {/* Schedule */}
        <Route path="/schedule" element={<ScheduleCalendarScreen />} />

        {/* SMS */}
        <Route path="/sms" element={<SMSComposeScreen />} />

        {/* Settings */}
        <Route path="/settings" element={<SettingsScreen />} />

        {/* Kiosk */}
        <Route path="/kiosk" element={<KioskScreen />} />

        {/* Fallback */}
        <Route
          path="*"
          element={
            <div className="flex flex-1 items-center justify-center p-4 text-gray-500 dark:text-gray-400">
              <p>Page not found</p>
            </div>
          }
        />
      </Routes>
    </Suspense>
    </ErrorBoundary>
  )
}
