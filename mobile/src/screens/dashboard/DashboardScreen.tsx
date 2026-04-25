import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { MobileCard } from '@/components/ui'
import { MobileButton } from '@/components/ui'
import { MobileSpinner } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'
import { useAuth } from '@/contexts/AuthContext'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'

/**
 * Dashboard summary data returned by the backend.
 * All fields are optional — we use safe defaults via `?? 0`.
 */
interface DashboardSummary {
  revenue?: number
  outstanding_invoices?: number
  outstanding_amount?: number
  jobs_in_progress?: number
  upcoming_bookings?: number
  clocked_in?: boolean
  current_time_entry_id?: string | null
}

/**
 * Dashboard screen — role-based summary cards, quick action buttons,
 * pull-to-refresh, and clock in/out button.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 19.1
 */
export default function DashboardScreen() {
  const navigate = useNavigate()
  const { user, isKiosk } = useAuth()
  const { isModuleEnabled } = useModules()

  const [summary, setSummary] = useState<DashboardSummary>({})
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Clock in/out state
  const [isClockedIn, setIsClockedIn] = useState(false)
  const [isClockLoading, setIsClockLoading] = useState(false)

  const fetchDashboard = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await apiClient.get<DashboardSummary>(
        '/api/v1/dashboard/branch-metrics',
        { signal },
      )
      const data = res.data ?? {}
      setSummary(data)
      setIsClockedIn(!!data.clocked_in)
      setError(null)
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
    fetchDashboard(controller.signal).finally(() => setIsLoading(false))
    return () => controller.abort()
  }, [fetchDashboard])

  // Pull-to-refresh handler
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true)
    await fetchDashboard()
    setIsRefreshing(false)
  }, [fetchDashboard])

  // Clock in/out handler
  const handleClockToggle = useCallback(async () => {
    setIsClockLoading(true)
    try {
      if (isClockedIn) {
        await apiClient.post('/api/v2/time-entries/clock-out')
        setIsClockedIn(false)
      } else {
        await apiClient.post('/api/v2/time-entries/clock-in')
        setIsClockedIn(true)
      }
    } catch {
      // Silently handle — user can retry
    } finally {
      setIsClockLoading(false)
    }
  }, [isClockedIn])

  // Format currency for display
  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-NZ', {
      style: 'currency',
      currency: 'NZD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <MobileSpinner size="lg" />
      </div>
    )
  }

  const revenue = summary?.revenue ?? 0
  const outstandingInvoices = summary?.outstanding_invoices ?? 0
  const outstandingAmount = summary?.outstanding_amount ?? 0
  const jobsInProgress = summary?.jobs_in_progress ?? 0
  const upcomingBookings = summary?.upcoming_bookings ?? 0

  return (
    <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4">
        {/* Page heading */}
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          Welcome{user?.name ? `, ${user.name}` : ''}
        </h1>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          >
            {error}
          </div>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-2 gap-3">
          {/* Revenue card — visible to non-kiosk roles */}
          {!isKiosk && (
            <MobileCard
              onTap={() => navigate('/invoices')}
              className="col-span-2"
            >
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Revenue
              </p>
              <p
                className="mt-1 text-2xl font-bold text-gray-900 dark:text-gray-100"
                data-testid="revenue-value"
              >
                {formatCurrency(revenue)}
              </p>
            </MobileCard>
          )}

          {/* Outstanding invoices card */}
          {!isKiosk && (
            <MobileCard onTap={() => navigate('/invoices')}>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Outstanding
              </p>
              <p
                className="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100"
                data-testid="outstanding-count"
              >
                {outstandingInvoices}
              </p>
              <p className="text-xs text-gray-400 dark:text-gray-500">
                {formatCurrency(outstandingAmount)}
              </p>
            </MobileCard>
          )}

          {/* Jobs in progress card */}
          <ModuleGate moduleSlug="jobs">
            <MobileCard onTap={() => navigate('/jobs')}>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Jobs In Progress
              </p>
              <p
                className="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100"
                data-testid="jobs-count"
              >
                {jobsInProgress}
              </p>
            </MobileCard>
          </ModuleGate>

          {/* Upcoming bookings card */}
          <ModuleGate moduleSlug="bookings">
            <MobileCard onTap={() => navigate('/bookings')}>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Upcoming Bookings
              </p>
              <p
                className="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100"
                data-testid="bookings-count"
              >
                {upcomingBookings}
              </p>
            </MobileCard>
          </ModuleGate>
        </div>

        {/* Clock in/out button — visible when time_tracking module enabled */}
        <ModuleGate moduleSlug="time_tracking">
          <MobileButton
            variant={isClockedIn ? 'danger' : 'primary'}
            fullWidth
            isLoading={isClockLoading}
            onClick={handleClockToggle}
            icon={
              <svg
                className="h-5 w-5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
            }
          >
            {isClockedIn ? 'Clock Out' : 'Clock In'}
          </MobileButton>
        </ModuleGate>

        {/* Quick actions */}
        <div>
          <h2 className="mb-2 text-sm font-medium text-gray-500 dark:text-gray-400">
            Quick Actions
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {/* New Invoice — always visible (invoices are core) */}
            <MobileButton
              variant="secondary"
              fullWidth
              onClick={() => navigate('/invoices/new')}
              icon={
                <svg
                  className="h-5 w-5"
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
              }
            >
              New Invoice
            </MobileButton>

            {/* New Quote — gated by quotes module */}
            <ModuleGate moduleSlug="quotes">
              <MobileButton
                variant="secondary"
                fullWidth
                onClick={() => navigate('/quotes/new')}
                icon={
                  <svg
                    className="h-5 w-5"
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
                }
              >
                New Quote
              </MobileButton>
            </ModuleGate>

            {/* New Job Card — gated by jobs module */}
            <ModuleGate moduleSlug="jobs">
              <MobileButton
                variant="secondary"
                fullWidth
                onClick={() => navigate('/jobs/cards')}
                icon={
                  <svg
                    className="h-5 w-5"
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
                }
              >
                New Job Card
              </MobileButton>
            </ModuleGate>

            {/* New Customer — always visible */}
            <MobileButton
              variant="secondary"
              fullWidth
              onClick={() => navigate('/customers/new')}
              icon={
                <svg
                  className="h-5 w-5"
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
              }
            >
              New Customer
            </MobileButton>
          </div>
        </div>
      </div>
    </PullRefresh>
  )
}
