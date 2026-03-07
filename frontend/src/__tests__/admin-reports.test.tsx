import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 46.1-46.5
 * - 46.1: Platform MRR, Organisation Overview, Carjam Cost vs Revenue, Vehicle DB Stats, Churn Report
 * - 46.2: MRR with plan breakdown and month-over-month trend
 * - 46.3: Organisation overview table with plan, signup date, trial, billing, storage, Carjam, last login
 * - 46.4: Vehicle DB stats — total records, cache hit rate, total lookups
 * - 46.5: Churn report — cancelled/suspended orgs with plan type and duration
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return {
    default: { get: mockGet, put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  }
})

import apiClient from '@/api/client'
import { Reports } from '../pages/admin/Reports'
import type {
  MrrData,
  OrgOverviewRow,
  CarjamCostData,
  VehicleDbStatsData,
  ChurnRow,
} from '../pages/admin/Reports'

/* ── Test data factories ── */

function makeMrrData(overrides: Partial<MrrData> = {}): MrrData {
  return {
    total_mrr: 12500,
    plan_breakdown: [
      { plan: 'Starter', mrr: 4900, org_count: 100 },
      { plan: 'Professional', mrr: 7600, org_count: 38 },
    ],
    trend: [
      { month: 'Jan', mrr: 11000 },
      { month: 'Feb', mrr: 12500 },
    ],
    ...overrides,
  }
}

function makeOrgRows(): OrgOverviewRow[] {
  return [
    {
      id: 'org-1',
      name: 'Workshop Alpha',
      plan: 'Starter',
      signup_date: '2024-01-15T00:00:00Z',
      trial_status: 'active',
      billing_status: 'active',
      storage_used_gb: 2.3,
      storage_quota_gb: 5,
      carjam_usage: 42,
      last_login: '2024-06-10T08:30:00Z',
    },
    {
      id: 'org-2',
      name: 'Garage Beta',
      plan: 'Professional',
      signup_date: '2023-11-01T00:00:00Z',
      trial_status: null,
      billing_status: 'suspended',
      storage_used_gb: 4.8,
      storage_quota_gb: 10,
      carjam_usage: 150,
      last_login: null,
    },
  ]
}

function makeCarjamCostData(overrides: Partial<CarjamCostData> = {}): CarjamCostData {
  return {
    total_cost: 320.5,
    total_revenue: 480.0,
    net: 159.5,
    monthly_breakdown: [
      { month: 'Jan', cost: 150, revenue: 220 },
      { month: 'Feb', cost: 170.5, revenue: 260 },
    ],
    ...overrides,
  }
}

function makeVehicleDbStats(overrides: Partial<VehicleDbStatsData> = {}): VehicleDbStatsData {
  return {
    total_records: 25430,
    cache_hit_rate: 87,
    total_lookups: 54200,
    ...overrides,
  }
}

function makeChurnRows(): ChurnRow[] {
  return [
    {
      id: 'churn-1',
      name: 'Old Workshop',
      plan: 'Starter',
      status: 'cancelled',
      cancelled_at: '2024-05-20T00:00:00Z',
      subscription_duration_days: 180,
    },
    {
      id: 'churn-2',
      name: 'Suspended Garage',
      plan: 'Professional',
      status: 'suspended',
      cancelled_at: '2024-06-01T00:00:00Z',
      subscription_duration_days: 15,
    },
  ]
}

function setupMocks(options: {
  mrr?: MrrData
  orgs?: OrgOverviewRow[]
  carjam?: CarjamCostData
  vehicleDb?: VehicleDbStatsData
  churn?: ChurnRow[]
} = {}) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/reports/mrr') return Promise.resolve({ data: options.mrr ?? makeMrrData() })
    if (url === '/admin/reports/organisations') return Promise.resolve({ data: options.orgs ?? makeOrgRows() })
    if (url === '/admin/reports/carjam-cost') return Promise.resolve({ data: options.carjam ?? makeCarjamCostData() })
    if (url === '/admin/reports/vehicle-db') return Promise.resolve({ data: options.vehicleDb ?? makeVehicleDbStats() })
    if (url === '/admin/reports/churn') return Promise.resolve({ data: options.churn ?? makeChurnRows() })
    return Promise.reject(new Error(`Unknown URL: ${url}`))
  })
}

describe('Admin Reports page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // 46.1: Page renders with all five report tabs
  it('renders the reports page with all five tabs', async () => {
    setupMocks()
    render(<Reports />)

    expect(screen.getByText('Admin Reports')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'MRR' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Organisations' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Carjam Cost' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vehicle DB' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Churn' })).toBeInTheDocument()
  })

  // 46.2: MRR tab shows total MRR, plan breakdown, and trend chart
  it('displays MRR data with plan breakdown and trend', async () => {
    setupMocks()
    render(<Reports />)

    // MRR tab is default — total MRR appears in summary card and trend chart
    expect(await screen.findByText('Total MRR')).toBeInTheDocument()
    const allMrr = screen.getAllByText('$12,500.00')
    expect(allMrr.length).toBeGreaterThanOrEqual(1)

    // Plan breakdown table
    expect(screen.getByText('Starter')).toBeInTheDocument()
    expect(screen.getByText('Professional')).toBeInTheDocument()

    // Trend chart
    expect(screen.getByText('Month-over-Month Trend')).toBeInTheDocument()
  })

  // 46.3: Organisations tab shows table with all required columns
  it('displays organisation overview table with required columns', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Reports />)

    await user.click(screen.getByRole('tab', { name: 'Organisations' }))

    expect(await screen.findByText('Workshop Alpha')).toBeInTheDocument()
    expect(screen.getByText('Garage Beta')).toBeInTheDocument()

    // Check column headers exist
    const table = screen.getByRole('grid')
    const headers = within(table).getAllByRole('columnheader')
    const headerTexts = headers.map((h) => h.textContent?.replace(/[↕↑↓]/g, '').trim())
    expect(headerTexts).toContain('Organisation')
    expect(headerTexts).toContain('Plan')
    expect(headerTexts).toContain('Signup Date')
    expect(headerTexts).toContain('Trial')
    expect(headerTexts).toContain('Billing')
    expect(headerTexts).toContain('Storage')
    expect(headerTexts).toContain('Carjam Usage')
    expect(headerTexts).toContain('Last Login')
  })

  // 46.4: Vehicle DB tab shows total records, cache hit rate, total lookups
  it('displays Vehicle DB stats with all three metrics', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Reports />)

    await user.click(screen.getByRole('tab', { name: 'Vehicle DB' }))

    expect(await screen.findByText('25,430')).toBeInTheDocument()
    expect(screen.getByText('87%')).toBeInTheDocument()
    expect(screen.getByText('54,200')).toBeInTheDocument()

    expect(screen.getByText('Total Records')).toBeInTheDocument()
    expect(screen.getByText('Cache Hit Rate')).toBeInTheDocument()
    expect(screen.getByText('Total Lookups')).toBeInTheDocument()
  })

  // 46.5: Churn tab shows cancelled/suspended orgs with plan and duration
  it('displays churn report with plan type and duration', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Reports />)

    await user.click(screen.getByRole('tab', { name: 'Churn' }))

    expect(await screen.findByText('Old Workshop')).toBeInTheDocument()
    expect(screen.getByText('Suspended Garage')).toBeInTheDocument()

    // Status badges
    expect(screen.getByText('cancelled')).toBeInTheDocument()
    expect(screen.getByText('suspended')).toBeInTheDocument()

    // Duration formatting
    expect(screen.getByText('6 months')).toBeInTheDocument()
    expect(screen.getByText('15d')).toBeInTheDocument()
  })

  // 46.1: Carjam Cost tab shows cost vs revenue comparison
  it('displays Carjam cost vs revenue with net calculation', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Reports />)

    await user.click(screen.getByRole('tab', { name: 'Carjam Cost' }))

    expect(await screen.findByText('$320.50')).toBeInTheDocument()
    expect(screen.getByText('$480.00')).toBeInTheDocument()
    expect(screen.getByText('$159.50')).toBeInTheDocument()

    expect(screen.getByText('Total Cost')).toBeInTheDocument()
    expect(screen.getByText('Total Revenue')).toBeInTheDocument()
    expect(screen.getByText('Net')).toBeInTheDocument()
  })

  // Error handling: MRR tab shows error on API failure
  it('shows error message when MRR API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<Reports />)

    expect(await screen.findByText('Failed to load MRR report.')).toBeInTheDocument()
  })
})
