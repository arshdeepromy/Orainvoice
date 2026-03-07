import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 39.1, 39.2, 39.3
 * - 39.1: Multi-trade analytics dashboard with org distribution and geographic map
 * - 39.2: Module adoption heatmap by trade family
 * - 39.3: Conversion funnel metrics
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return {
    default: { get: mockGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  }
})

import apiClient from '@/api/client'
import { AnalyticsDashboard } from '../pages/admin/AnalyticsDashboard'

/* ── Mock data ── */

const mockOverview = {
  total_orgs: 150,
  active_orgs: 120,
  mrr: 8500.0,
  churn_rate: 3.5,
}

const mockTradeDistribution = {
  by_family: [
    { slug: 'automotive', display_name: 'Automotive & Transport', org_count: 60 },
    { slug: 'construction', display_name: 'Building & Construction', org_count: 40 },
    { slug: 'hospitality', display_name: 'Food & Hospitality', org_count: 30 },
  ],
  by_category: [],
}

const mockModuleAdoption = {
  heatmap: [
    { family_slug: 'automotive', family_name: 'Automotive & Transport', module_slug: 'invoicing', enabled_count: 55, total_orgs: 60, adoption_pct: 91.7 },
    { family_slug: 'automotive', family_name: 'Automotive & Transport', module_slug: 'pos', enabled_count: 10, total_orgs: 60, adoption_pct: 16.7 },
    { family_slug: 'construction', family_name: 'Building & Construction', module_slug: 'invoicing', enabled_count: 40, total_orgs: 40, adoption_pct: 100.0 },
    { family_slug: 'construction', family_name: 'Building & Construction', module_slug: 'pos', enabled_count: 5, total_orgs: 40, adoption_pct: 12.5 },
  ],
}

const mockGeographic = {
  by_country: [
    { country_code: 'NZ', org_count: 80 },
    { country_code: 'AU', org_count: 45 },
    { country_code: 'UK', org_count: 25 },
  ],
  by_region: [
    { region: 'nz-au', org_count: 125 },
    { region: 'uk-eu', org_count: 25 },
  ],
}

const mockRevenue = {
  by_plan: [
    { plan_name: 'Professional', org_count: 70, mrr: 5250.0, arr: 63000.0, arpu: 75.0, estimated_ltv: 1800.0 },
    { plan_name: 'Starter', org_count: 40, mrr: 1960.0, arr: 23520.0, arpu: 49.0, estimated_ltv: 1176.0 },
    { plan_name: 'Enterprise', org_count: 10, mrr: 1290.0, arr: 15480.0, arpu: 129.0, estimated_ltv: 3096.0 },
  ],
  total_mrr: 8500.0,
  total_arr: 102000.0,
  total_orgs: 120,
  overall_arpu: 70.83,
}

const mockFunnel = {
  stages: [
    { stage: 'signup', count: 200, rate: 100.0 },
    { stage: 'wizard_complete', count: 160, rate: 80.0 },
    { stage: 'first_invoice', count: 100, rate: 62.5 },
    { stage: 'paid_subscription', count: 60, rate: 60.0 },
  ],
}

function setupMocks() {
  const mockGet = apiClient.get as ReturnType<typeof vi.fn>
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/overview')) return Promise.resolve({ data: mockOverview })
    if (url.includes('/trade-distribution')) return Promise.resolve({ data: mockTradeDistribution })
    if (url.includes('/module-adoption')) return Promise.resolve({ data: mockModuleAdoption })
    if (url.includes('/geographic')) return Promise.resolve({ data: mockGeographic })
    if (url.includes('/revenue')) return Promise.resolve({ data: mockRevenue })
    if (url.includes('/conversion-funnel')) return Promise.resolve({ data: mockFunnel })
    return Promise.reject(new Error('Unknown endpoint'))
  })
}

/* ── Tests ── */

describe('AnalyticsDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupMocks()
  })

  it('renders loading state initially', () => {
    render(<AnalyticsDashboard />)
    expect(screen.getByTestId('analytics-loading')).toBeInTheDocument()
  })

  it('renders overview cards with correct values', async () => {
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('overview-cards')).toBeInTheDocument()
    })
    const overviewCards = screen.getByTestId('overview-cards')
    expect(overviewCards).toHaveTextContent('150')
    expect(overviewCards).toHaveTextContent('120')
    expect(overviewCards).toHaveTextContent('3.5%')
  })

  it('renders trade distribution chart', async () => {
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('trade-distribution')).toBeInTheDocument()
    })
    const tradeSection = screen.getByTestId('trade-distribution')
    expect(tradeSection).toHaveTextContent('Automotive & Transport')
    expect(tradeSection).toHaveTextContent('Building & Construction')
    expect(tradeSection).toHaveTextContent('Food & Hospitality')
  })

  it('renders module adoption heatmap with percentages', async () => {
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('module-heatmap')).toBeInTheDocument()
    })
    expect(screen.getByText('91.7%')).toBeInTheDocument()
    expect(screen.getByText('16.7%')).toBeInTheDocument()
    // 100% appears in multiple places, so check within the heatmap
    const heatmap = screen.getByTestId('module-heatmap')
    expect(heatmap).toHaveTextContent('100%')
    expect(screen.getByText('12.5%')).toBeInTheDocument()
  })

  it('renders geographic distribution', async () => {
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('geographic-distribution')).toBeInTheDocument()
    })
    expect(screen.getByText('NZ')).toBeInTheDocument()
    expect(screen.getByText('AU')).toBeInTheDocument()
    expect(screen.getByText('UK')).toBeInTheDocument()
  })

  it('renders revenue chart with plan breakdown', async () => {
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('revenue-chart')).toBeInTheDocument()
    })
    expect(screen.getByText('Professional')).toBeInTheDocument()
    expect(screen.getByText('Starter')).toBeInTheDocument()
    expect(screen.getByText('Enterprise')).toBeInTheDocument()
  })

  it('renders conversion funnel with all stages', async () => {
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('conversion-funnel')).toBeInTheDocument()
    })
    expect(screen.getByText('Signup')).toBeInTheDocument()
    expect(screen.getByText('Wizard Complete')).toBeInTheDocument()
    expect(screen.getByText('First Invoice')).toBeInTheDocument()
    expect(screen.getByText('Paid Subscription')).toBeInTheDocument()
  })

  it('calls all 6 analytics endpoints on mount', async () => {
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard')).toBeInTheDocument()
    })
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    expect(mockGet).toHaveBeenCalledWith('/api/v2/admin/analytics/overview')
    expect(mockGet).toHaveBeenCalledWith('/api/v2/admin/analytics/trade-distribution')
    expect(mockGet).toHaveBeenCalledWith('/api/v2/admin/analytics/module-adoption')
    expect(mockGet).toHaveBeenCalledWith('/api/v2/admin/analytics/geographic')
    expect(mockGet).toHaveBeenCalledWith('/api/v2/admin/analytics/revenue')
    expect(mockGet).toHaveBeenCalledWith('/api/v2/admin/analytics/conversion-funnel')
  })

  it('shows error state when API fails', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockRejectedValue(new Error('Network error'))

    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('analytics-error')).toBeInTheDocument()
    })
    expect(screen.getByText(/Network error/)).toBeInTheDocument()
  })

  it('refresh button reloads data', async () => {
    const user = userEvent.setup()
    render(<AnalyticsDashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('analytics-dashboard')).toBeInTheDocument()
    })

    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockClear()
    setupMocks()

    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(6)
    })
  })
})
