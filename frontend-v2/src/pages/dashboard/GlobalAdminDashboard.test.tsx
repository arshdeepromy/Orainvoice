/**
 * GlobalAdminDashboard tests (Task 17).
 *
 * Verifies the platform dashboard renders against the real (safeFetch-guarded)
 * endpoint shapes: KPI cards (MRR / active orgs / errors / billing), the
 * error-by-severity aggregation, integration health, and the critical-error
 * banner. The HAStatusPanel + OrgBranchRevenueSection make their own fetches,
 * so the api mock returns benign fallbacks for everything else (those sections
 * self-hide on empty/failed data — confirming safe consumption).
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

import apiClient from '@/api/client'
import { GlobalAdminDashboard } from './GlobalAdminDashboard'

const mockGet = apiClient.get as ReturnType<typeof vi.fn>

function renderDashboard() {
  return render(
    <MemoryRouter>
      <GlobalAdminDashboard />
    </MemoryRouter>,
  )
}

function populated(url: string) {
  if (url === '/api/v2/admin/analytics/overview') {
    return Promise.resolve({ data: { total_orgs: 12, active_orgs: 10, mrr: 5400, churn_rate: 0 } })
  }
  if (url === '/admin/reports/mrr') {
    return Promise.resolve({
      data: {
        total_mrr_nzd: 5400,
        interval_breakdown: [
          { interval: 'monthly', org_count: 8, mrr_nzd: 4000 },
          { interval: 'annual', org_count: 2, mrr_nzd: 1400 },
        ],
      },
    })
  }
  if (url === '/admin/errors/dashboard') {
    return Promise.resolve({
      data: {
        by_severity: [
          { label: 'critical', count_24h: 2 },
          { label: 'error', count_24h: 5 },
          { label: 'warning', count_24h: 7 },
          { label: 'info', count_24h: 20 },
        ],
        total_24h: 34,
      },
    })
  }
  if (url === '/admin/integrations') {
    return Promise.resolve({
      data: [
        { name: 'carjam', status: 'healthy', last_checked: null },
        { name: 'stripe', status: 'degraded', last_checked: null },
      ],
    })
  }
  if (url === '/admin/reports/billing-issues') {
    return Promise.resolve({
      data: [{ id: 'b1', org_name: 'Acme Ltd', issue_type: 'payment_failed', amount: 120, created_at: '2025-11-01' }],
    })
  }
  // integration-costs, /ha/*, /admin/org-branch-revenue → benign empties.
  return Promise.resolve({ data: {} })
}

describe('GlobalAdminDashboard — populated', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockImplementation((url: string) => populated(url))
  })

  it('renders the platform heading and KPI cards', async () => {
    renderDashboard()
    expect(await screen.findByText('Platform Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Platform MRR')).toBeInTheDocument()
    expect(screen.getByText('Active Organisations')).toBeInTheDocument()
    expect(screen.getByText('Total Errors (24h)')).toBeInTheDocument()
    // "Billing Issues" is both a KPI label and the section heading — scope to
    // the KPI card label.
    expect(screen.getByText('Billing Issues', { selector: 'p' })).toBeInTheDocument()
  })

  it('aggregates errors by severity and shows the critical banner', async () => {
    renderDashboard()
    // Critical banner (2 critical errors detected) — scope to the banner body.
    expect(await screen.findByText(/critical error.*detected/i)).toBeInTheDocument()
    // Severity cards.
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('Warning')).toBeInTheDocument()
  })

  it('renders integration health and the billing issues table', async () => {
    renderDashboard()
    expect(await screen.findByText('carjam')).toBeInTheDocument()
    expect(screen.getByText('Acme Ltd')).toBeInTheDocument()
  })
})

describe('GlobalAdminDashboard — empty / safe consumption', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockImplementation(() => Promise.resolve({ data: {} }))
  })

  it('renders without crashing when every endpoint returns an empty object', async () => {
    renderDashboard()
    expect(await screen.findByText('Platform Dashboard')).toBeInTheDocument()
    // No integrations configured message (integration_health empty).
    expect(screen.getByText('No integrations configured')).toBeInTheDocument()
    // Billing issues DataTable empty state.
    expect(screen.getByText('No data available')).toBeInTheDocument()
  })
})
