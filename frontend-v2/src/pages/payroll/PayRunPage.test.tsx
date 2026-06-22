/**
 * PayRunPage — pay-cycle labelling + cycle filter (per-staff-pay-cycle).
 *
 * Covers the Part-2a changes:
 *   • When periods carry a `pay_cycle_name`, the cycle name renders in the
 *     period navigator alongside the date range.
 *   • When the loaded periods span more than one distinct `pay_cycle_name`,
 *     a cycle filter (segmented control) appears and filters the periods used
 *     by the navigator + selector.
 *
 * The typed `@/api/payslips` wrappers and the `@/api/client` default export
 * (used for the `/pay-cycles/` probe) are mocked so the page runs end-to-end
 * against deterministic shapes. ModuleGate is mocked to a passthrough so the
 * test doesn't need the ModuleContext provider.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }) },
}))

vi.mock('@/api/payslips', () => ({
  listPayPeriods: vi.fn(),
  listPeriodPayslips: vi.fn(),
  generatePeriodPayslips: vi.fn(),
  bulkFinalisePeriod: vi.fn(),
  reopenPayPeriod: vi.fn(),
}))

import { listPayPeriods, listPeriodPayslips } from '@/api/payslips'
import PayRunPage from './PayRunPage'

const mockListPayPeriods = listPayPeriods as ReturnType<typeof vi.fn>
const mockListPeriodPayslips = listPeriodPayslips as ReturnType<typeof vi.fn>

function period(overrides: Record<string, unknown>) {
  return {
    id: 'p',
    org_id: 'org-1',
    start_date: '2026-06-08',
    end_date: '2026-06-14',
    pay_date: '2026-06-17',
    status: 'open',
    created_at: '2026-06-01T00:00:00Z',
    finalised_at: null,
    paid_at: null,
    pay_cycle_name: null,
    ...overrides,
  }
}

const WEEKLY = period({
  id: 'weekly-open',
  start_date: '2026-06-08',
  end_date: '2026-06-14',
  status: 'open',
  pay_cycle_name: 'Weekly',
})
const FORTNIGHTLY = period({
  id: 'fortnightly-open',
  start_date: '2026-06-01',
  end_date: '2026-06-14',
  status: 'open',
  pay_cycle_name: 'Fortnightly',
})
const WEEKLY_FINALISED = period({
  id: 'weekly-finalised',
  start_date: '2026-05-25',
  end_date: '2026-05-31',
  status: 'finalised',
  pay_cycle_name: 'Weekly',
})

function renderPage(initialEntry = '/payroll') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <PayRunPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockListPeriodPayslips.mockResolvedValue({ items: [], total: 0 })
})

describe('PayRunPage — pay cycle labelling', () => {
  it('renders the cycle name alongside the date range in the navigator', async () => {
    mockListPayPeriods.mockResolvedValue({
      items: [WEEKLY, FORTNIGHTLY, WEEKLY_FINALISED],
      total: 3,
    })
    renderPage()

    // First 'open' period (Weekly) is selected by default; its cycle name
    // shows in the navigator alongside the date range.
    expect(await screen.findAllByText(/Weekly · /)).not.toHaveLength(0)
  })

  it('shows the cycle filter and filters the periods when periods span >1 cycle', async () => {
    mockListPayPeriods.mockResolvedValue({
      items: [WEEKLY, FORTNIGHTLY, WEEKLY_FINALISED],
      total: 3,
    })
    renderPage()

    // The cycle filter appears (two distinct cycle names present).
    const filter = await screen.findByTestId('cycle-filter')
    expect(filter).toBeInTheDocument()
    // Weekly is visible before filtering.
    expect(screen.getAllByText(/Weekly · /).length).toBeGreaterThan(0)

    // Focus on the Fortnightly cycle.
    fireEvent.click(screen.getByTestId('cycle-filter-option-Fortnightly'))

    // Navigator + selector now show only the Fortnightly period; the Weekly
    // periods are filtered out entirely.
    await waitFor(() => {
      expect(screen.getAllByText(/Fortnightly · /).length).toBeGreaterThan(0)
      expect(screen.queryByText(/Weekly · /)).toBeNull()
    })
  })

  it('does not render the cycle filter when all periods share one cycle', async () => {
    mockListPayPeriods.mockResolvedValue({
      items: [WEEKLY, WEEKLY_FINALISED],
      total: 2,
    })
    renderPage()

    await screen.findAllByText(/Weekly · /)
    expect(screen.queryByTestId('cycle-filter')).toBeNull()
  })
})
