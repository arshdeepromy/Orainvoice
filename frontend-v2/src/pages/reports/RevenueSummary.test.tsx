import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import RevenueSummary from './RevenueSummary'

/**
 * RevenueSummary unit tests (Task 8.2) — Revenue tab field mapping coverage.
 *
 * Mounts the tab with `@/api/client` mocked so the page's `GET /reports/revenue`
 * call resolves against a deterministic shape, and `@/contexts/BranchContext`
 * mocked to a stable "All Branches" selection (the tab only reads
 * `useBranch().selectedBranchId`). The `revenue` fixture is mutable (vi.hoisted)
 * so a single mock serves every case: the invoice-count alias/fallback, the
 * monthly chart, and the empty state.
 *
 * Validates: Requirements 1.4 (invoice count read as total_invoices ?? invoice_count ?? 0),
 * 1.5 (monthly chart rendered from monthly_breakdown), 1.6 (empty state when absent).
 */

const h = vi.hoisted(() => ({
  revenue: {} as Record<string, unknown>,
}))

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(async () => ({ data: h.revenue })),
    post: vi.fn(async () => ({ data: {} })),
  },
}))

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({
    selectedBranchId: null,
    branches: [],
    selectBranch: vi.fn(),
    isLoading: false,
    isBranchLocked: false,
  }),
}))

function renderTab() {
  render(
    <MemoryRouter>
      <RevenueSummary />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  h.revenue = {}
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('RevenueSummary', () => {
  it('renders the invoice count from total_invoices', async () => {
    h.revenue = { total_revenue: 1200, total_gst: 180, total_invoices: 7, monthly_breakdown: [] }
    renderTab()

    // The Invoices summary card shows the count read from `total_invoices`.
    const label = await screen.findByText('Invoices')
    const card = label.closest('div') as HTMLElement
    expect(within(card).getByText('7')).toBeInTheDocument()
  })

  it('falls back to invoice_count when total_invoices is absent', async () => {
    h.revenue = { total_revenue: 800, total_gst: 120, invoice_count: 4, monthly_breakdown: [] }
    renderTab()

    const label = await screen.findByText('Invoices')
    const card = label.closest('div') as HTMLElement
    expect(within(card).getByText('4')).toBeInTheDocument()
  })

  it('renders the monthly chart from monthly_breakdown', async () => {
    h.revenue = {
      total_revenue: 5000,
      total_gst: 750,
      total_invoices: 12,
      monthly_breakdown: [
        { month: '2024-01', revenue: 2000 },
        { month: '2024-02', revenue: 3000 },
      ],
    }
    renderTab()

    // Both month labels from monthly_breakdown render as chart bars.
    expect(await screen.findByText('2024-01')).toBeInTheDocument()
    expect(screen.getByText('2024-02')).toBeInTheDocument()
    // The empty-state copy must NOT be shown when data is present.
    expect(
      screen.queryByText('No monthly data available for this period.'),
    ).not.toBeInTheDocument()
  })

  it('shows the empty state when monthly_breakdown is absent', async () => {
    h.revenue = { total_revenue: 0, total_gst: 0, total_invoices: 0 }
    renderTab()

    expect(
      await screen.findByText('No monthly data available for this period.'),
    ).toBeInTheDocument()
  })
})
