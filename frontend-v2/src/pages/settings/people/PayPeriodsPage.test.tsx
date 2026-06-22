/**
 * PayPeriodsPage — Cycle column (per-staff-pay-cycle, Part 2b).
 *
 * Covers the new "Cycle" column: it renders each period's `pay_cycle_name`,
 * falling back to `—` when null.
 *
 * The typed `@/api/payslips` wrappers are mocked so the page runs end-to-end
 * against deterministic shapes.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/payslips', () => ({
  listPayPeriods: vi.fn(),
  createPayPeriod: vi.fn(),
  reopenPayPeriod: vi.fn(),
  updatePayPeriod: vi.fn(),
}))

import { listPayPeriods } from '@/api/payslips'
import PayPeriodsPage from './PayPeriodsPage'

const mockListPayPeriods = listPayPeriods as ReturnType<typeof vi.fn>

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

function renderPage() {
  return render(
    <MemoryRouter>
      <PayPeriodsPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PayPeriodsPage — Cycle column', () => {
  it('renders the pay_cycle_name in the Cycle column', async () => {
    const weekly = period({ id: 'weekly-1', pay_cycle_name: 'Weekly' })
    mockListPayPeriods.mockResolvedValue({ items: [weekly], total: 1 })
    renderPage()

    const cell = await screen.findByTestId('pay-period-cycle-weekly-1')
    expect(within(cell).getByText('Weekly')).toBeInTheDocument()
  })

  it('falls back to — when pay_cycle_name is null', async () => {
    const legacy = period({ id: 'legacy-1', pay_cycle_name: null })
    mockListPayPeriods.mockResolvedValue({ items: [legacy], total: 1 })
    renderPage()

    const cell = await screen.findByTestId('pay-period-cycle-legacy-1')
    expect(within(cell).getByText('—')).toBeInTheDocument()
  })

  it('shows a Cycle column header', async () => {
    mockListPayPeriods.mockResolvedValue({
      items: [period({ id: 'p1', pay_cycle_name: 'Fortnightly' })],
      total: 1,
    })
    renderPage()

    await screen.findByTestId('pay-periods-table')
    expect(screen.getByText('Cycle')).toBeInTheDocument()
  })
})
