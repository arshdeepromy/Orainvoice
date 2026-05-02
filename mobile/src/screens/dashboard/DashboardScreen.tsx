import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Page,
  Navbar,
  Card,
  Chip,
  List,
  ListItem,
  BlockTitle,
  Badge,
  Block,
  Preloader,
} from 'konsta/react'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'
import StatusBadge from '@/components/konsta/StatusBadge'
import { BranchPickerSheet } from '@/components/konsta/BranchPickerSheet'
import { useAuth } from '@/contexts/AuthContext'
import { useModules } from '@/contexts/ModuleContext'
import { useBranch } from '@/contexts/BranchContext'
import apiClient from '@/api/client'

// ---------------------------------------------------------------------------
// Types — safe shapes for API responses
// ---------------------------------------------------------------------------

interface DashboardStats {
  revenue_this_month?: number
  outstanding_receivables?: number
  overdue_count?: number
  active_jobs_count?: number
  expiring_compliance_docs?: number
}

interface InvoiceItem {
  id?: string
  invoice_number?: string
  customer_name?: string
  total?: number
  balance_due?: number
  status?: string
  created_at?: string
  due_date?: string
  days_overdue?: number
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const formatNZD = (value: number | null | undefined): string =>
  `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

// ---------------------------------------------------------------------------
// Main Dashboard Component
// ---------------------------------------------------------------------------

/**
 * DashboardScreen — Konsta UI redesign with:
 * - Greeting "Hello, {first_name}" with branch selector subtitle
 * - Stat cards in 2-column grid (Revenue, Outstanding, Overdue, Active Jobs)
 * - Scrollable horizontal quick action Chip buttons
 * - "Recent Invoices" section with last 5 invoices as Konsta List
 * - "Needs Attention" section with overdue invoices and red status indicators
 * - Compliance alert card (if compliance_docs module + expiring docs)
 * - Pull-to-refresh using existing PullRefresh component inside Konsta Page
 * - Safe API consumption patterns throughout
 *
 * All business logic preserved from the original DashboardScreen.
 *
 * Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 8.1, 8.2, 8.3
 */
export default function DashboardScreen() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { isModuleEnabled } = useModules()
  const { selectedBranchId, branches, selectBranch } = useBranch()

  // Branch picker state
  const [branchPickerOpen, setBranchPickerOpen] = useState(false)

  // Loading & refresh state
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Data state
  const [stats, setStats] = useState<DashboardStats>({})
  const [recentInvoices, setRecentInvoices] = useState<InvoiceItem[]>([])
  const [overdueInvoices, setOverdueInvoices] = useState<InvoiceItem[]>([])

  // Derive first name from user.name
  const firstName = useMemo(() => {
    const name = user?.name ?? ''
    return name.split(' ')[0] || name
  }, [user?.name])

  // Derive branch name for subtitle
  const branchName = useMemo(() => {
    if (!selectedBranchId) return 'All Branches'
    const branch = branches.find((b) => b.id === selectedBranchId)
    return branch?.name ?? 'All Branches'
  }, [selectedBranchId, branches])

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    try {
      const [statsRes, recentRes, overdueRes] = await Promise.allSettled([
        apiClient.get<DashboardStats>('/api/v1/dashboard/stats', { signal }),
        apiClient.get<{ items?: InvoiceItem[]; total?: number }>(
          '/api/v1/invoices',
          { params: { offset: 0, limit: 5 }, signal },
        ),
        apiClient.get<{ items?: InvoiceItem[]; total?: number }>(
          '/api/v1/invoices',
          { params: { status: 'overdue', offset: 0, limit: 10 }, signal },
        ),
      ])

      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value?.data ?? {})
      }
      if (recentRes.status === 'fulfilled') {
        setRecentInvoices(recentRes.value?.data?.items ?? [])
      }
      if (overdueRes.status === 'fulfilled') {
        setOverdueInvoices(overdueRes.value?.data?.items ?? [])
      }

      // If all requests failed, show error
      const allFailed =
        statsRes.status === 'rejected' &&
        recentRes.status === 'rejected' &&
        overdueRes.status === 'rejected'

      if (allFailed) {
        // Check if it was a cancellation
        const firstErr = statsRes.reason as { name?: string } | undefined
        if (firstErr?.name !== 'CanceledError') {
          setError('Failed to load dashboard data')
        }
      } else {
        setError(null)
      }
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') {
        setError('Failed to load dashboard data')
      }
    }
  }, [])

  // Initial load
  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    fetchAll(controller.signal).finally(() => setIsLoading(false))
    return () => controller.abort()
  }, [fetchAll])

  // Pull-to-refresh handler
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true)
    await fetchAll()
    setIsRefreshing(false)
  }, [fetchAll])

  // Derived values with safe defaults
  const revenueThisMonth = stats?.revenue_this_month ?? 0
  const outstandingReceivables = stats?.outstanding_receivables ?? 0
  const overdueCount = stats?.overdue_count ?? 0
  const activeJobsCount = stats?.active_jobs_count ?? 0
  const expiringComplianceDocs = stats?.expiring_compliance_docs ?? 0

  // Loading state
  if (isLoading) {
    return (
      <Page>
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="dashboard-page">
      <Navbar
        title="Dashboard"
        subtitle={firstName ? `Hello, ${firstName}` : undefined}
        large
        data-testid="dashboard-navbar"
      />
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4 pb-8">
        {/* ── Branch Selector ─────────────────────────────────────── */}
        {isModuleEnabled('branch_management') && (
          <div className="px-1">
            <button
              type="button"
              onClick={() => setBranchPickerOpen(true)}
              className="flex items-center gap-1 text-sm text-gray-500 active:text-gray-700 dark:text-gray-400 dark:active:text-gray-300"
              data-testid="branch-selector-subtitle"
            >
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
              {branchName}
              <svg
                className="h-3 w-3"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          </div>
        )}

        {/* ── Error Banner ────────────────────────────────────────── */}
        {error && (
          <div
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          >
            {error}
            <button
              type="button"
              onClick={() => handleRefresh()}
              className="ml-2 font-medium underline"
            >
              Retry
            </button>
          </div>
        )}

        {/* ── Stat Cards (2-column grid) ──────────────────────────── */}
        <div
          className="grid grid-cols-2 gap-3"
          data-testid="stat-cards"
        >
          {/* Revenue this month */}
          <Card
            className="!m-0"
            data-testid="stat-revenue"
          >
            <div className="p-3">
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                Revenue
              </p>
              <p className="text-[11px] text-gray-400 dark:text-gray-500">
                This month
              </p>
              <p className="mt-1 text-lg font-bold text-gray-900 dark:text-gray-100">
                {formatNZD(revenueThisMonth)}
              </p>
            </div>
          </Card>

          {/* Outstanding receivables */}
          <Card
            className="!m-0"
            data-testid="stat-outstanding"
          >
            <div className="p-3">
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                Outstanding
              </p>
              <p className="text-[11px] text-gray-400 dark:text-gray-500">
                Receivables
              </p>
              <p className="mt-1 text-lg font-bold text-gray-900 dark:text-gray-100">
                {formatNZD(outstandingReceivables)}
              </p>
            </div>
          </Card>

          {/* Overdue count */}
          <Card
            className="!m-0"
            data-testid="stat-overdue"
          >
            <div className="p-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Overdue
                </p>
                {overdueCount > 0 && (
                  <Badge
                    colors={{
                      bg: 'bg-red-500',
                    }}
                    data-testid="overdue-badge"
                  >
                    {overdueCount}
                  </Badge>
                )}
              </div>
              <p className="text-[11px] text-gray-400 dark:text-gray-500">
                Invoices
              </p>
              <p
                className={`mt-1 text-lg font-bold ${
                  overdueCount > 0
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-gray-900 dark:text-gray-100'
                }`}
              >
                {overdueCount}
              </p>
            </div>
          </Card>

          {/* Active jobs — only if jobs module enabled */}
          {isModuleEnabled('jobs') && (
            <Card
              className="!m-0"
              data-testid="stat-active-jobs"
            >
              <div className="p-3">
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  Active Jobs
                </p>
                <p className="text-[11px] text-gray-400 dark:text-gray-500">
                  In progress
                </p>
                <p className="mt-1 text-lg font-bold text-gray-900 dark:text-gray-100">
                  {activeJobsCount}
                </p>
              </div>
            </Card>
          )}
        </div>

        {/* ── Quick Actions (horizontal scrollable chips) ─────────── */}
        <div
          className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1"
          data-testid="quick-actions"
        >
          <Chip
            className="shrink-0 cursor-pointer"
            onClick={() => navigate('/invoices/new')}
            data-testid="quick-action-new-invoice"
          >
            <span className="flex items-center gap-1">
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="12" y1="18" x2="12" y2="12" />
                <line x1="9" y1="15" x2="15" y2="15" />
              </svg>
              New Invoice
            </span>
          </Chip>

          <Chip
            className="shrink-0 cursor-pointer"
            onClick={() => navigate('/customers/new')}
            data-testid="quick-action-new-customer"
          >
            <span className="flex items-center gap-1">
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="8.5" cy="7" r="4" />
                <line x1="20" y1="8" x2="20" y2="14" />
                <line x1="23" y1="11" x2="17" y2="11" />
              </svg>
              New Customer
            </span>
          </Chip>

          {isModuleEnabled('quotes') && (
            <Chip
              className="shrink-0 cursor-pointer"
              onClick={() => navigate('/quotes/new')}
              data-testid="quick-action-new-quote"
            >
              <span className="flex items-center gap-1">
                <svg
                  className="h-4 w-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
                New Quote
              </span>
            </Chip>
          )}

          {isModuleEnabled('jobs') && (
            <Chip
              className="shrink-0 cursor-pointer"
              onClick={() => navigate('/job-cards/new')}
              data-testid="quick-action-new-job"
            >
              <span className="flex items-center gap-1">
                <svg
                  className="h-4 w-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
                  <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
                </svg>
                New Job
              </span>
            </Chip>
          )}

          {isModuleEnabled('bookings') && (
            <Chip
              className="shrink-0 cursor-pointer"
              onClick={() => navigate('/bookings/new')}
              data-testid="quick-action-new-booking"
            >
              <span className="flex items-center gap-1">
                <svg
                  className="h-4 w-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                  <line x1="16" y1="2" x2="16" y2="6" />
                  <line x1="8" y1="2" x2="8" y2="6" />
                  <line x1="3" y1="10" x2="21" y2="10" />
                </svg>
                New Booking
              </span>
            </Chip>
          )}
        </div>

        {/* ── Recent Invoices ─────────────────────────────────────── */}
        <div data-testid="recent-invoices-section">
          <BlockTitle className="!mt-0 !mb-1">Recent Invoices</BlockTitle>
          {recentInvoices.length === 0 ? (
            <Block className="text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">
                No recent invoices
              </p>
            </Block>
          ) : (
            <List strongIos outlineIos dividersIos>
              {recentInvoices.slice(0, 5).map((inv) => (
                <ListItem
                  key={inv?.id ?? inv?.invoice_number}
                  link
                  onClick={() => inv?.id && navigate(`/invoices/${inv.id}`)}
                  title={inv?.customer_name ?? 'Unknown'}
                  subtitle={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {inv?.invoice_number ?? ''}
                      {inv?.created_at ? ` · ${formatDate(inv.created_at)}` : ''}
                    </span>
                  }
                  after={
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-sm font-semibold tabular-nums text-gray-900 dark:text-gray-100">
                        {formatNZD(inv?.total ?? 0)}
                      </span>
                      <StatusBadge status={inv?.status ?? 'draft'} size="sm" />
                    </div>
                  }
                  data-testid={`recent-invoice-${inv?.id}`}
                />
              ))}
            </List>
          )}
        </div>

        {/* ── Needs Attention (Overdue Invoices) ──────────────────── */}
        {overdueInvoices.length > 0 && (
          <div data-testid="needs-attention-section">
            <BlockTitle className="!mt-0 !mb-1">
              <span className="flex items-center gap-2">
                Needs Attention
                <Badge
                  colors={{ bg: 'bg-red-500' }}
                >
                  {overdueInvoices.length}
                </Badge>
              </span>
            </BlockTitle>
            <List strongIos outlineIos dividersIos>
              {overdueInvoices.map((inv) => (
                <ListItem
                  key={inv?.id ?? inv?.invoice_number}
                  link
                  onClick={() => inv?.id && navigate(`/invoices/${inv.id}`)}
                  title={
                    <span className="text-red-700 dark:text-red-400">
                      {inv?.customer_name ?? 'Unknown'}
                    </span>
                  }
                  subtitle={
                    <span className="text-xs text-red-500 dark:text-red-400">
                      {inv?.invoice_number ?? ''}
                      {inv?.due_date
                        ? ` · Due ${formatDate(inv.due_date)}`
                        : ''}
                      {(inv?.days_overdue ?? 0) > 0
                        ? ` · ${inv?.days_overdue}d overdue`
                        : ''}
                    </span>
                  }
                  after={
                    <div className="flex flex-col items-end gap-1">
                      <span className="text-sm font-semibold tabular-nums text-red-600 dark:text-red-400">
                        {formatNZD(inv?.balance_due ?? inv?.total ?? 0)}
                      </span>
                      <StatusBadge status="overdue" size="sm" />
                    </div>
                  }
                  data-testid={`overdue-invoice-${inv?.id}`}
                />
              ))}
            </List>
          </div>
        )}

        {/* ── Compliance Alert Card ───────────────────────────────── */}
        <ModuleGate moduleSlug="compliance_docs">
          {expiringComplianceDocs > 0 && (
            <Card
              className="!m-0 border border-yellow-300 bg-yellow-50 dark:border-yellow-700 dark:bg-yellow-900/20"
              data-testid="compliance-alert-card"
            >
              <div className="flex items-center gap-3 p-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-yellow-200 dark:bg-yellow-800">
                  <svg
                    className="h-5 w-5 text-yellow-700 dark:text-yellow-300"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                    <line x1="12" y1="9" x2="12" y2="13" />
                    <line x1="12" y1="17" x2="12.01" y2="17" />
                  </svg>
                </div>
                <div className="flex-1">
                  <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-200">
                    Compliance Documents Expiring
                  </p>
                  <p className="text-xs text-yellow-700 dark:text-yellow-300">
                    {expiringComplianceDocs} document{expiringComplianceDocs !== 1 ? 's' : ''} expiring soon
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => navigate('/compliance')}
                  className="shrink-0 rounded-lg bg-yellow-200 px-3 py-1.5 text-xs font-medium text-yellow-800 active:bg-yellow-300 dark:bg-yellow-800 dark:text-yellow-200 dark:active:bg-yellow-700"
                >
                  View
                </button>
              </div>
            </Card>
          )}
        </ModuleGate>
      </div>
      </PullRefresh>

      {/* ── Branch Picker Sheet ────────────────────────────────────── */}
      <BranchPickerSheet
        isOpen={branchPickerOpen}
        onClose={() => setBranchPickerOpen(false)}
        onSelect={(branchId) => selectBranch(branchId || null)}
      />
    </Page>
  )
}
