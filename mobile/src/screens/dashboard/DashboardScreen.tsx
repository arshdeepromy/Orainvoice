import { useState, useEffect, useCallback, useMemo, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { MobileCard } from '@/components/ui'
import { MobileButton } from '@/components/ui'
import { MobileSpinner } from '@/components/ui'
import { MobileBadge } from '@/components/ui'
import type { BadgeVariant } from '@/components/ui/MobileBadge'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { ModuleGate } from '@/components/common/ModuleGate'
import { useAuth } from '@/contexts/AuthContext'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'

// ---------------------------------------------------------------------------
// Types — safe shapes for API responses
// ---------------------------------------------------------------------------

interface CashFlowItem {
  month?: string
  month_label?: string
  revenue?: number
  expenses?: number
}

interface WidgetsResponse {
  cash_flow?: {
    items?: CashFlowItem[]
    total?: number
  }
}

interface OutstandingInvoice {
  id?: string
  invoice_number?: string
  customer_name?: string
  total?: number
  balance_due?: number
  due_date?: string
  days_overdue?: number
  status?: string
}

interface OutstandingResponse {
  total_outstanding?: number
  count?: number
  invoices?: OutstandingInvoice[]
}

interface InvoiceItem {
  id?: string
  invoice_number?: string
  customer_name?: string
  total?: number
  status?: string
  created_at?: string
}

interface QuoteItem {
  id?: string
  quote_number?: string
  customer_name?: string
  total?: number
  status?: string
  created_at?: string
}

interface ExpenseItem {
  id?: string
  description?: string
  amount?: number
  category?: string
  date?: string
  expense_type?: string
}

interface BranchMetrics {
  revenue?: number
  invoice_count?: number
  invoice_value?: number
  customer_count?: number
  staff_count?: number
  total_expenses?: number
  clocked_in?: boolean
  current_time_entry_id?: string | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const formatNZD = (value: number) =>
  new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
  }).format(value)

function statusToBadgeVariant(status: string | undefined): BadgeVariant {
  switch ((status ?? '').toLowerCase()) {
    case 'paid':
      return 'paid'
    case 'overdue':
      return 'overdue'
    case 'draft':
      return 'draft'
    case 'sent':
    case 'submitted':
      return 'sent'
    case 'cancelled':
    case 'rejected':
      return 'cancelled'
    case 'pending':
    case 'accepted':
      return 'pending'
    case 'expired':
      return 'expired'
    default:
      return 'info'
  }
}

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
// Sub-components
// ---------------------------------------------------------------------------

/** Section 1 — Welcome header */
function WelcomeHeader({ userName }: { userName: string }) {
  return (
    <div className="px-1 py-2">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
        Welcome{userName ? `, ${userName}` : ''}
      </h1>
      <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
        Happy Invoicing!
      </p>
    </div>
  )
}

/** Section 2 — Quick action icon buttons */
function QuickActionButton({
  label,
  bgColor,
  icon,
  onTap,
}: {
  label: string
  bgColor: string
  icon: ReactNode
  onTap: () => void
}) {
  return (
    <button
      type="button"
      onClick={onTap}
      className="flex min-w-[68px] flex-col items-center gap-1.5 rounded-lg p-2 active:opacity-70"
    >
      <div
        className={`flex h-11 w-11 items-center justify-center rounded-xl ${bgColor}`}
      >
        {icon}
      </div>
      <span className="text-[11px] font-medium text-gray-700 dark:text-gray-300">
        {label}
      </span>
    </button>
  )
}

/** Section 3 — Receivables summary with aging bar chart */
function ReceivablesSummary({
  outstanding,
}: {
  outstanding: OutstandingResponse
}) {
  const totalReceivables = outstanding?.total_outstanding ?? 0
  const invoices = outstanding?.invoices ?? []

  // Bucket invoices by days overdue
  const buckets = useMemo(() => {
    const b = { current: 0, d1_15: 0, d16_30: 0, d31_45: 0, d45plus: 0 }
    for (const inv of invoices) {
      const days = inv?.days_overdue ?? 0
      const amt = inv?.balance_due ?? inv?.total ?? 0
      if (days <= 0) b.current += amt
      else if (days <= 15) b.d1_15 += amt
      else if (days <= 30) b.d16_30 += amt
      else if (days <= 45) b.d31_45 += amt
      else b.d45plus += amt
    }
    return b
  }, [invoices])

  const maxBucket = Math.max(
    buckets.current,
    buckets.d1_15,
    buckets.d16_30,
    buckets.d31_45,
    buckets.d45plus,
    1, // avoid division by zero
  )

  const currentTotal = buckets.current
  const overdueTotal =
    buckets.d1_15 + buckets.d16_30 + buckets.d31_45 + buckets.d45plus

  const barData = [
    { label: 'Current', value: buckets.current, color: 'bg-green-500' },
    { label: '1-15', value: buckets.d1_15, color: 'bg-yellow-500' },
    { label: '16-30', value: buckets.d16_30, color: 'bg-orange-500' },
    { label: '31-45', value: buckets.d31_45, color: 'bg-red-400' },
    { label: '>45', value: buckets.d45plus, color: 'bg-red-600' },
  ]

  return (
    <MobileCard>
      <div className="mb-3 flex items-center gap-2">
        <svg
          className="h-5 w-5 text-blue-500"
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
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Receivables Summary
        </h2>
      </div>

      <p className="text-xs text-gray-500 dark:text-gray-400">
        Total Receivables
      </p>
      <p className="mb-4 text-2xl font-bold text-gray-900 dark:text-gray-100">
        {formatNZD(totalReceivables)}
      </p>

      {/* Aging bar chart */}
      <div className="mb-4 flex items-end gap-2" style={{ height: 80 }}>
        {barData.map((bar) => (
          <div key={bar.label} className="flex flex-1 flex-col items-center">
            <div
              className="relative w-full"
              style={{ height: 60 }}
            >
              <div
                className={`absolute bottom-0 w-full rounded-t ${bar.color}`}
                style={{
                  height: `${Math.max((bar.value / maxBucket) * 100, bar.value > 0 ? 8 : 0)}%`,
                  minHeight: bar.value > 0 ? 4 : 0,
                }}
              />
            </div>
            <span className="mt-1 text-[10px] text-gray-500 dark:text-gray-400">
              {bar.label}
            </span>
          </div>
        ))}
      </div>

      {/* Current / Overdue summary */}
      <div className="flex gap-4">
        <div className="flex-1 rounded-lg bg-green-50 p-2.5 dark:bg-green-900/20">
          <p className="text-[10px] font-medium text-green-700 dark:text-green-400">
            Current
          </p>
          <p className="text-sm font-semibold text-green-800 dark:text-green-300">
            {formatNZD(currentTotal)}
          </p>
        </div>
        <div className="flex-1 rounded-lg bg-red-50 p-2.5 dark:bg-red-900/20">
          <p className="text-[10px] font-medium text-red-700 dark:text-red-400">
            Overdue
          </p>
          <p className="text-sm font-semibold text-red-800 dark:text-red-300">
            {formatNZD(overdueTotal)}
          </p>
        </div>
      </div>
    </MobileCard>
  )
}

/** Section 4 — Recent transactions with tab pills */
function RecentTransactions({
  invoices,
  quotes,
  expenses,
  showQuotes,
  showExpenses,
  navigate,
}: {
  invoices: InvoiceItem[]
  quotes: QuoteItem[]
  expenses: ExpenseItem[]
  showQuotes: boolean
  showExpenses: boolean
  navigate: (path: string) => void
}) {
  type TabKey = 'invoices' | 'quotes' | 'expenses'
  const tabs = useMemo<{ key: TabKey; label: string }[]>(() => {
    const t: { key: TabKey; label: string }[] = [
      { key: 'invoices', label: 'Invoices' },
    ]
    if (showQuotes) t.push({ key: 'quotes', label: 'Quotes' })
    if (showExpenses) t.push({ key: 'expenses', label: 'Expenses' })
    return t
  }, [showQuotes, showExpenses])

  const [activeTab, setActiveTab] = useState<TabKey>('invoices')

  const viewAllPath =
    activeTab === 'invoices'
      ? '/invoices'
      : activeTab === 'quotes'
        ? '/quotes'
        : '/expenses'

  return (
    <MobileCard>
      <div className="mb-3 flex items-center gap-2">
        <svg
          className="h-5 w-5 text-blue-500"
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
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Recent Transactions
        </h2>
      </div>

      {/* Tab pills */}
      <div className="mb-3 flex gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              activeTab === tab.key
                ? 'bg-blue-600 text-white dark:bg-blue-500'
                : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Transaction rows */}
      <div className="divide-y divide-gray-100 dark:divide-gray-700">
        {activeTab === 'invoices' &&
          (invoices.length === 0 ? (
            <p className="py-4 text-center text-sm text-gray-400">
              No recent invoices
            </p>
          ) : (
            invoices.map((inv) => (
              <div
                key={inv?.id ?? inv?.invoice_number}
                className="flex items-center justify-between py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                    {inv?.customer_name ?? 'Unknown'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {formatDate(inv?.created_at)}
                    {inv?.invoice_number ? ` · ${inv.invoice_number}` : ''}
                  </p>
                </div>
                <div className="ml-3 flex flex-col items-end gap-1">
                  <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {formatNZD(inv?.total ?? 0)}
                  </span>
                  <MobileBadge
                    label={inv?.status ?? 'draft'}
                    variant={statusToBadgeVariant(inv?.status)}
                  />
                </div>
              </div>
            ))
          ))}

        {activeTab === 'quotes' &&
          (quotes.length === 0 ? (
            <p className="py-4 text-center text-sm text-gray-400">
              No recent quotes
            </p>
          ) : (
            quotes.map((q) => (
              <div
                key={q?.id ?? q?.quote_number}
                className="flex items-center justify-between py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                    {q?.customer_name ?? 'Unknown'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {formatDate(q?.created_at)}
                    {q?.quote_number ? ` · ${q.quote_number}` : ''}
                  </p>
                </div>
                <div className="ml-3 flex flex-col items-end gap-1">
                  <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {formatNZD(q?.total ?? 0)}
                  </span>
                  <MobileBadge
                    label={q?.status ?? 'draft'}
                    variant={statusToBadgeVariant(q?.status)}
                  />
                </div>
              </div>
            ))
          ))}

        {activeTab === 'expenses' &&
          (expenses.length === 0 ? (
            <p className="py-4 text-center text-sm text-gray-400">
              No recent expenses
            </p>
          ) : (
            expenses.map((exp) => (
              <div
                key={exp?.id ?? exp?.description}
                className="flex items-center justify-between py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                    {exp?.category ?? exp?.description ?? 'Expense'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {formatDate(exp?.date)}
                    {exp?.expense_type ? ` · ${exp.expense_type}` : ''}
                  </p>
                </div>
                <div className="ml-3 text-right">
                  <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {formatNZD(exp?.amount ?? 0)}
                  </span>
                </div>
              </div>
            ))
          ))}
      </div>

      {/* View All link */}
      <button
        type="button"
        onClick={() => navigate(viewAllPath)}
        className="mt-3 flex w-full items-center justify-center gap-1 py-2 text-sm font-medium text-blue-600 active:text-blue-700 dark:text-blue-400"
      >
        View All
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
          <path d="M5 12h14" />
          <path d="m12 5 7 7-7 7" />
        </svg>
      </button>
    </MobileCard>
  )
}

/** Section 5 — Income & Expense bar chart */
function IncomeExpenseChart({
  cashFlowItems,
  totalRevenue,
  totalExpenses,
}: {
  cashFlowItems: CashFlowItem[]
  totalRevenue: number
  totalExpenses: number
}) {
  const maxValue = useMemo(() => {
    let m = 1
    for (const item of cashFlowItems) {
      m = Math.max(m, item?.revenue ?? 0, item?.expenses ?? 0)
    }
    return m
  }, [cashFlowItems])

  return (
    <MobileCard>
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Income &amp; Expense
        </h2>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          Last 12 Months ▾
        </span>
      </div>

      {/* Legend */}
      <div className="mb-3 flex gap-4">
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded-sm bg-blue-500" />
          <span className="text-[10px] text-gray-500 dark:text-gray-400">
            Income
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded-sm bg-orange-500" />
          <span className="text-[10px] text-gray-500 dark:text-gray-400">
            Expenses
          </span>
        </div>
      </div>

      {/* Bar chart */}
      {cashFlowItems.length === 0 ? (
        <p className="py-6 text-center text-sm text-gray-400">
          No data available
        </p>
      ) : (
        <div className="mb-4 overflow-x-auto">
          <div
            className="flex items-end gap-1"
            style={{ height: 100, minWidth: cashFlowItems.length * 40 }}
          >
            {cashFlowItems.map((item, idx) => {
              const rev = item?.revenue ?? 0
              const exp = item?.expenses ?? 0
              const revH = (rev / maxValue) * 100
              const expH = (exp / maxValue) * 100
              return (
                <div
                  key={item?.month ?? idx}
                  className="flex flex-1 flex-col items-center"
                >
                  <div
                    className="flex w-full items-end justify-center gap-0.5"
                    style={{ height: 80 }}
                  >
                    <div
                      className="w-2.5 rounded-t bg-blue-500"
                      style={{
                        height: `${Math.max(revH, rev > 0 ? 4 : 0)}%`,
                      }}
                    />
                    <div
                      className="w-2.5 rounded-t bg-orange-500"
                      style={{
                        height: `${Math.max(expH, exp > 0 ? 4 : 0)}%`,
                      }}
                    />
                  </div>
                  <span className="mt-1 text-[9px] text-gray-500 dark:text-gray-400">
                    {item?.month_label ?? ''}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Summary cards */}
      <div className="mb-2 rounded-lg bg-blue-50 p-2.5 dark:bg-blue-900/20">
        <p className="text-[10px] font-medium text-blue-700 dark:text-blue-400">
          Total Income
        </p>
        <p className="text-sm font-semibold text-blue-800 dark:text-blue-300">
          {formatNZD(totalRevenue)}
        </p>
      </div>
      <div className="flex gap-3">
        <div className="flex-1 rounded-lg bg-orange-50 p-2.5 dark:bg-orange-900/20">
          <p className="text-[10px] font-medium text-orange-700 dark:text-orange-400">
            Total Expenses
          </p>
          <p className="text-sm font-semibold text-orange-800 dark:text-orange-300">
            {formatNZD(totalExpenses)}
          </p>
        </div>
        <div className="flex-1 rounded-lg bg-green-50 p-2.5 dark:bg-green-900/20">
          <p className="text-[10px] font-medium text-green-700 dark:text-green-400">
            Total Receipts
          </p>
          <p className="text-sm font-semibold text-green-800 dark:text-green-300">
            {formatNZD(totalRevenue)}
          </p>
        </div>
      </div>
      <p className="mt-2 text-[10px] text-gray-400 dark:text-gray-500">
        * Sales value displayed is inclusive of tax and inclusive of credits
      </p>
    </MobileCard>
  )
}

/** Section 6 — Top Expenses (gated by expenses module) */
function TopExpenses({
  expenses,
  navigate,
}: {
  expenses: ExpenseItem[]
  navigate: (path: string) => void
}) {
  // Group expenses by category and sum amounts
  const topCategories = useMemo(() => {
    const map = new Map<string, number>()
    for (const exp of expenses) {
      const cat = exp?.category ?? 'Uncategorised'
      map.set(cat, (map.get(cat) ?? 0) + (exp?.amount ?? 0))
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
  }, [expenses])

  return (
    <MobileCard>
      <div className="mb-1 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Top Expenses
        </h2>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          This Fiscal Year ▾
        </span>
      </div>

      {topCategories.length === 0 ? (
        <div className="flex flex-col items-center py-6">
          <p className="mb-3 text-sm text-gray-400">
            No expenses recorded yet
          </p>
          <MobileButton
            variant="primary"
            size="sm"
            onClick={() => navigate('/expenses/new')}
          >
            New Expense
          </MobileButton>
        </div>
      ) : (
        <div className="mt-2 divide-y divide-gray-100 dark:divide-gray-700">
          {topCategories.map(([category, amount]: [string, number]) => (
            <div
              key={category}
              className="flex items-center justify-between py-2"
            >
              <span className="text-sm text-gray-700 dark:text-gray-300">
                {category}
              </span>
              <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {formatNZD(amount)}
              </span>
            </div>
          ))}
        </div>
      )}
    </MobileCard>
  )
}

// ---------------------------------------------------------------------------
// Main Dashboard Component
// ---------------------------------------------------------------------------

export default function DashboardScreen() {
  const navigate = useNavigate()
  const { user, isKiosk } = useAuth()
  const { isModuleEnabled } = useModules()

  // Loading & refresh state
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Clock in/out state
  const [isClockedIn, setIsClockedIn] = useState(false)
  const [isClockLoading, setIsClockLoading] = useState(false)

  // Data state
  const [, setMetrics] = useState<BranchMetrics>({})
  const [widgets, setWidgets] = useState<WidgetsResponse>({})
  const [outstanding, setOutstanding] = useState<OutstandingResponse>({})
  const [recentInvoices, setRecentInvoices] = useState<InvoiceItem[]>([])
  const [recentQuotes, setRecentQuotes] = useState<QuoteItem[]>([])
  const [recentExpenses, setRecentExpenses] = useState<ExpenseItem[]>([])

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    try {
      // Fire all requests in parallel
      const [metricsRes, widgetsRes, outstandingRes, invoicesRes] =
        await Promise.allSettled([
          apiClient.get<BranchMetrics>('/api/v1/dashboard/branch-metrics', {
            signal,
          }),
          apiClient.get<WidgetsResponse>('/api/v1/dashboard/widgets', {
            signal,
          }),
          apiClient.get<OutstandingResponse>('/api/v1/reports/outstanding', {
            signal,
          }),
          apiClient.get<{ items?: InvoiceItem[]; total?: number }>(
            '/api/v1/invoices?page=1&page_size=5',
            { signal },
          ),
        ])

      // Safely extract results
      if (metricsRes.status === 'fulfilled') {
        const data = metricsRes.value?.data ?? {}
        setMetrics(data)
        setIsClockedIn(!!data.clocked_in)
      }
      if (widgetsRes.status === 'fulfilled') {
        setWidgets(widgetsRes.value?.data ?? {})
      }
      if (outstandingRes.status === 'fulfilled') {
        setOutstanding(outstandingRes.value?.data ?? {})
      }
      if (invoicesRes.status === 'fulfilled') {
        setRecentInvoices(invoicesRes.value?.data?.items ?? [])
      }

      setError(null)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') {
        setError('Failed to load dashboard data')
      }
    }
  }, [])

  // Fetch module-gated data separately
  const fetchModuleData = useCallback(
    async (signal?: AbortSignal) => {
      const promises: Promise<void>[] = []

      if (isModuleEnabled('quotes')) {
        promises.push(
          apiClient
            .get<{ items?: QuoteItem[]; total?: number }>(
              '/api/v1/quotes?page=1&page_size=5',
              { signal },
            )
            .then((res) => {
              setRecentQuotes(res?.data?.items ?? [])
            })
            .catch(() => {
              setRecentQuotes([])
            }),
        )
      }

      if (isModuleEnabled('expenses')) {
        promises.push(
          apiClient
            .get<{ expenses?: ExpenseItem[]; total?: number }>(
              '/api/v2/expenses?page=1&page_size=5',
              { signal },
            )
            .then((res) => {
              setRecentExpenses(res?.data?.expenses ?? [])
            })
            .catch(() => {
              setRecentExpenses([])
            }),
        )
      }

      await Promise.allSettled(promises)
    },
    [isModuleEnabled],
  )

  // Initial load
  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    Promise.all([
      fetchAll(controller.signal),
      fetchModuleData(controller.signal),
    ]).finally(() => setIsLoading(false))
    return () => controller.abort()
  }, [fetchAll, fetchModuleData])

  // Pull-to-refresh handler
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true)
    await Promise.all([fetchAll(), fetchModuleData()])
    setIsRefreshing(false)
  }, [fetchAll, fetchModuleData])

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

  // Derived data
  const cashFlowItems = widgets?.cash_flow?.items ?? []
  const totalRevenue = useMemo(
    () =>
      cashFlowItems.reduce((sum: number, item: CashFlowItem) => sum + (item?.revenue ?? 0), 0),
    [cashFlowItems],
  )
  const totalExpenses = useMemo(
    () =>
      cashFlowItems.reduce((sum: number, item: CashFlowItem) => sum + (item?.expenses ?? 0), 0),
    [cashFlowItems],
  )

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <MobileSpinner size="lg" />
      </div>
    )
  }

  return (
    <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
      <div className="flex flex-col gap-4 p-4 pb-8">
        {/* 1. Welcome Header */}
        <WelcomeHeader userName={user?.name ?? ''} />

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300"
          >
            {error}
          </div>
        )}

        {/* Clock in/out button — gated by time_tracking module */}
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

        {/* 2. Quick Action Buttons */}
        <MobileCard padding="px-2 py-3">
          <div className="flex justify-around">
            {/* New Invoice — always visible */}
            <QuickActionButton
              label="New Invoice"
              bgColor="bg-blue-100 dark:bg-blue-900/40"
              icon={
                <svg
                  className="h-5 w-5 text-blue-600 dark:text-blue-400"
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
              onTap={() => navigate('/invoices/new')}
            />

            {/* New Customer — always visible */}
            <QuickActionButton
              label="New Customer"
              bgColor="bg-green-100 dark:bg-green-900/40"
              icon={
                <svg
                  className="h-5 w-5 text-green-600 dark:text-green-400"
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
              onTap={() => navigate('/customers/new')}
            />

            {/* New Expense — gated by expenses module */}
            {isModuleEnabled('expenses') && (
              <QuickActionButton
                label="New Expense"
                bgColor="bg-orange-100 dark:bg-orange-900/40"
                icon={
                  <svg
                    className="h-5 w-5 text-orange-600 dark:text-orange-400"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <line x1="12" y1="1" x2="12" y2="23" />
                    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
                  </svg>
                }
                onTap={() => navigate('/expenses/new')}
              />
            )}

            {/* New Quote — gated by quotes module */}
            {isModuleEnabled('quotes') && (
              <QuickActionButton
                label="New Quote"
                bgColor="bg-purple-100 dark:bg-purple-900/40"
                icon={
                  <svg
                    className="h-5 w-5 text-purple-600 dark:text-purple-400"
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
                onTap={() => navigate('/quotes/new')}
              />
            )}
          </div>
        </MobileCard>

        {/* 3. Receivables Summary */}
        {!isKiosk && <ReceivablesSummary outstanding={outstanding} />}

        {/* 4. Recent Transactions */}
        <RecentTransactions
          invoices={recentInvoices}
          quotes={recentQuotes}
          expenses={recentExpenses}
          showQuotes={isModuleEnabled('quotes')}
          showExpenses={isModuleEnabled('expenses')}
          navigate={navigate}
        />

        {/* 5. Income & Expense Chart */}
        {!isKiosk && (
          <IncomeExpenseChart
            cashFlowItems={cashFlowItems}
            totalRevenue={totalRevenue}
            totalExpenses={totalExpenses}
          />
        )}

        {/* 6. Top Expenses — gated by expenses module */}
        <ModuleGate moduleSlug="expenses">
          <TopExpenses expenses={recentExpenses} navigate={navigate} />
        </ModuleGate>
      </div>
    </PullRefresh>
  )
}
