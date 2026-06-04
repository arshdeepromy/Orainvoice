import { render, screen, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/* ============================================================
   MainDashboard tests (Task 16).
   ------------------------------------------------------------
   Verifies the ported prototype layout renders against the real API
   surface it consumes: KPI row, revenue chart card, recent invoices
   table, activity feed and upcoming bookings — plus the empty states.

   The contexts (Auth/Tenant/Branch/Module) are mocked so the page
   renders deterministically; the api client is mocked to return the
   actual backend response shapes (see safe-api-consumption — every
   list/number is guarded, so a degraded/empty response must not crash).
   recharts' ResponsiveContainer needs a sized parent in jsdom, so it's
   stubbed to a plain box to keep the test fast and stable.
   ============================================================ */

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'arsh@kerikeri.test', name: 'Arsh Singh', role: 'org_admin', org_id: 'org-1' },
    isLoading: false,
  }),
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ settings: { branding: { name: 'Kerikeri Motors' } } }),
}))

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({ selectedBranchId: null }),
}))

let modulesEnabled = true
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => modulesEnabled }),
}))

// Stub recharts' ResponsiveContainer (zero-size in jsdom => no chart paint).
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 600, height: 200 }}>{children}</div>
    ),
  }
})

vi.mock('@/api/client', () => ({
  default: { get: vi.fn() },
}))

import apiClient from '@/api/client'
import { MainDashboard } from './MainDashboard'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>

function renderDashboard() {
  return render(
    <MemoryRouter>
      <MainDashboard />
    </MemoryRouter>,
  )
}

/** Populated backend responses keyed by endpoint. */
function populatedResponses(url: string) {
  if (url === '/reports/revenue') {
    return Promise.resolve({ data: { total_inclusive: '48250.00', total_revenue: '41956.52', invoice_count: 12 } })
  }
  if (url === '/reports/outstanding') {
    return Promise.resolve({
      data: {
        total_outstanding: '12840.00',
        count: 18,
        invoices: [
          { invoice_id: 'i1', invoice_number: 'INV-2041', customer_name: 'Bay Plumbing Ltd', balance_due: '2480.00', days_overdue: 6 },
          { invoice_id: 'i2', invoice_number: 'INV-2030', customer_name: 'M. Taufa', balance_due: '640.00', days_overdue: 0 },
        ],
      },
    })
  }
  if (url === '/job-cards') {
    return Promise.resolve({ data: { job_cards: [], total: 14 } })
  }
  if (url === '/invoices') {
    return Promise.resolve({
      data: {
        invoices: [
          { id: 'i1', invoice_number: 'INV-2041', customer_name: 'Bay Plumbing Ltd', total: '2480.00', status: 'overdue', issue_date: '2025-11-01' },
          { id: 'i3', invoice_number: 'INV-2039', customer_name: 'Northland Freight', total: '4120.50', status: 'paid', issue_date: '2025-11-10' },
        ],
        total: 2,
      },
    })
  }
  if (url === '/bookings') {
    return Promise.resolve({
      data: {
        bookings: [
          { id: 'b1', customer_name: 'M. Taufa', vehicle_rego: 'ABC123', service_type: 'WOF + Service', scheduled_at: '2025-11-13T09:00:00Z', start_time: '2025-11-13T09:00:00Z', status: 'scheduled' },
        ],
        total: 1,
      },
    })
  }
  if (url === '/dashboard/widgets/cash-flow') {
    return Promise.resolve({
      data: {
        items: [
          { month: '2025-09', month_label: 'Sep', revenue: 22000, expenses: 8000 },
          { month: '2025-10', month_label: 'Oct', revenue: 34000, expenses: 9000 },
          { month: '2025-11', month_label: 'Nov', revenue: 48250, expenses: 10000 },
        ],
        total: 3,
      },
    })
  }
  return Promise.resolve({ data: {} })
}

describe('MainDashboard — populated', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    modulesEnabled = true
    mockGet.mockImplementation(populatedResponses)
  })

  it('renders the KPI row with revenue, outstanding, overdue and jobs', async () => {
    renderDashboard()

    expect(await screen.findByText('Revenue (period)')).toBeInTheDocument()
    expect(screen.getByText('Outstanding')).toBeInTheDocument()
    expect(screen.getByText('Overdue')).toBeInTheDocument()
    expect(screen.getByText('Jobs in progress')).toBeInTheDocument()

    // Revenue value (appears in KPI + chart meta) — at least one "48,250.00".
    expect(screen.getAllByText('48,250.00').length).toBeGreaterThan(0)
    // Jobs in progress KPI reads the job-cards total.
    expect(screen.getByText('14')).toBeInTheDocument()
  })

  it('derives the overdue KPI from outstanding invoices (days_overdue > 0)', async () => {
    renderDashboard()
    // Only INV-2041 ($2,480.00) has days_overdue > 0 => overdue count 1.
    // (M. Taufa's INV-2030 has days_overdue 0 and must be excluded.)
    const overdueSub = await screen.findByText('1 invoice overdue')
    // Scope the amount assertion to the Overdue KPI card — "2,480.00" also
    // legitimately appears in the recent invoices table (INV-2041's total).
    const overdueCard = overdueSub.closest('div.rounded-card') as HTMLElement
    expect(overdueCard).not.toBeNull()
    expect(within(overdueCard).getByText('2,480.00')).toBeInTheDocument()
  })

  it('renders the recent invoices table with status badges and amounts', async () => {
    renderDashboard()
    const table = await screen.findByRole('table')
    expect(within(table).getByText('INV-2039')).toBeInTheDocument()
    expect(within(table).getByText('Northland Freight')).toBeInTheDocument()
    expect(within(table).getByText('4,120.50')).toBeInTheDocument()
  })

  it('renders the activity feed synthesised from recent invoices', async () => {
    renderDashboard()
    expect(await screen.findByText('Payment received')).toBeInTheDocument()
    expect(screen.getByText('Invoice overdue')).toBeInTheDocument()
  })

  it('renders the upcoming bookings list', async () => {
    renderDashboard()
    expect(await screen.findByText('WOF + Service')).toBeInTheDocument()
  })
})

describe('MainDashboard — empty states', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    modulesEnabled = true
    mockGet.mockImplementation((url: string) => {
      if (url === '/reports/revenue') {
        return Promise.resolve({ data: { total_inclusive: '0', total_revenue: '0', invoice_count: 0 } })
      }
      if (url === '/reports/outstanding') {
        return Promise.resolve({ data: { total_outstanding: '0', count: 0, invoices: [] } })
      }
      if (url === '/job-cards') return Promise.resolve({ data: { job_cards: [], total: 0 } })
      if (url === '/invoices') return Promise.resolve({ data: { invoices: [], total: 0 } })
      if (url === '/bookings') return Promise.resolve({ data: { bookings: [], total: 0 } })
      if (url === '/dashboard/widgets/cash-flow') return Promise.resolve({ data: { items: [], total: 0 } })
      return Promise.resolve({ data: {} })
    })
  })

  it('shows empty-state messages for chart, invoices, activity and bookings', async () => {
    renderDashboard()
    expect(await screen.findByText('No revenue data for this period')).toBeInTheDocument()
    expect(screen.getByText('No invoices yet')).toBeInTheDocument()
    expect(screen.getByText('No recent activity')).toBeInTheDocument()
    expect(screen.getByText('No upcoming bookings')).toBeInTheDocument()
  })

  it('tolerates malformed responses without crashing (safe API consumption)', async () => {
    mockGet.mockImplementation(() => Promise.resolve({ data: {} }))
    renderDashboard()
    // Page still renders its header + KPI labels despite empty objects.
    expect(await screen.findByText('Revenue (period)')).toBeInTheDocument()
    expect(screen.getByText('No invoices yet')).toBeInTheDocument()
  })
})

describe('MainDashboard — module gating', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockImplementation(populatedResponses)
  })

  it('shows the bookings-disabled message when the bookings module is off', async () => {
    modulesEnabled = false
    renderDashboard()
    expect(await screen.findByText('Bookings module is disabled')).toBeInTheDocument()
    // Jobs KPI subtitle reflects the disabled module too.
    expect(screen.getByText('module disabled')).toBeInTheDocument()
  })
})
