/**
 * PayRunPage — unit tests (Staff Management Phase 4, task D1).
 *
 * Cases covered:
 *   1. Renders the empty-state message when no pay periods exist.
 *   2. Renders the payslip table when listPeriodPayslips returns rows.
 *   3. "Finalise all" button is disabled when there are no draft payslips.
 *   4. Reopen button is replaced by a tooltip-disabled stub when the
 *      selected period has status='paid' (G21).
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// PayslipDetail is lazy-loaded by the drawer — replace it with a stub so the
// test bundle does not depend on the full editor.
vi.mock('../PayslipDetail', () => ({
  default: ({ payslipId }: { payslipId: string }) => (
    <div data-testid="payslip-detail-stub">detail:{payslipId}</div>
  ),
}))

vi.mock('@/api/payslips', () => ({
  listPayPeriods: vi.fn(),
  listPeriodPayslips: vi.fn(),
  generatePeriodPayslips: vi.fn(),
  bulkFinalisePeriod: vi.fn(),
  reopenPayPeriod: vi.fn(),
}))

import {
  listPayPeriods,
  listPeriodPayslips,
} from '@/api/payslips'
import type { PayPeriod, Payslip } from '@/api/payslips'

import PayRunPage from '../PayRunPage'

const ORG = '00000000-0000-0000-0000-000000000001'

function buildPeriod(overrides: Partial<PayPeriod> = {}): PayPeriod {
  return {
    id: '11111111-2222-3333-4444-555555555555',
    org_id: ORG,
    start_date: '2026-06-01',
    end_date: '2026-06-14',
    pay_date: '2026-06-17',
    status: 'open',
    created_at: '2026-06-01T00:00:00Z',
    finalised_at: null,
    paid_at: null,
    ...overrides,
  }
}

function buildPayslip(overrides: Partial<Payslip> = {}): Payslip {
  return {
    id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    org_id: ORG,
    staff_id: 'cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa',
    staff_name: 'Aroha Smith',
    pay_period_id: '11111111-2222-3333-4444-555555555555',
    pay_period: null,
    status: 'draft',
    ordinary_hours: '40.00',
    overtime_hours: '0.00',
    public_holiday_hours: '0.00',
    ordinary_rate: '30.00',
    overtime_rate: '45.00',
    public_holiday_rate: '45.00',
    gross_pay: '1200.00',
    gross_ytd: '1200.00',
    net_pay: '950.00',
    pdf_file_key: null,
    emailed_at: null,
    finalised_at: null,
    notes: null,
    created_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
    ...overrides,
  }
}

const mockedListPayPeriods = listPayPeriods as ReturnType<typeof vi.fn>
const mockedListPeriodPayslips = listPeriodPayslips as ReturnType<typeof vi.fn>

function renderPage() {
  return render(
    <MemoryRouter>
      <PayRunPage />
    </MemoryRouter>,
  )
}

describe('PayRunPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the empty-state hint when no pay periods are returned', async () => {
    mockedListPayPeriods.mockResolvedValueOnce({ items: [], total: 0 })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('payslips-empty')).toBeInTheDocument()
    })
    expect(screen.getByTestId('payslips-empty')).toHaveTextContent(
      'Select a pay period to begin.',
    )

    // The select exists but has only the "no pay periods" option and is
    // disabled.
    const selector = screen.getByTestId('period-selector') as HTMLSelectElement
    expect(selector.disabled).toBe(true)
  })

  it('renders the payslip table when listPeriodPayslips returns rows', async () => {
    const period = buildPeriod()
    mockedListPayPeriods.mockResolvedValueOnce({
      items: [period],
      total: 1,
    })
    mockedListPeriodPayslips.mockResolvedValueOnce({
      items: [
        buildPayslip(),
        buildPayslip({
          id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          staff_name: 'Hone Te Rangi',
          status: 'finalised',
          gross_pay: '2000.00',
          net_pay: '1700.00',
        }),
      ],
      total: 2,
    })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('payslips-table')).toBeInTheDocument()
    })
    expect(screen.getByText('Aroha Smith')).toBeInTheDocument()
    expect(screen.getByText('Hone Te Rangi')).toBeInTheDocument()
    // Both currency values are formatted via Intl.NumberFormat.
    expect(screen.getAllByText(/\$1,200\.00/)[0]).toBeInTheDocument()
    expect(screen.getAllByText(/\$2,000\.00/)[0]).toBeInTheDocument()
  })

  it('disables "Finalise all" when there are no draft payslips', async () => {
    mockedListPayPeriods.mockResolvedValueOnce({
      items: [buildPeriod()],
      total: 1,
    })
    mockedListPeriodPayslips.mockResolvedValueOnce({
      items: [
        buildPayslip({ status: 'finalised' }),
        buildPayslip({
          id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          status: 'voided',
        }),
      ],
      total: 2,
    })

    renderPage()

    const button = await screen.findByTestId('bulk-finalise-button')
    expect(button).toBeDisabled()
    expect(button).toHaveTextContent(/Finalise all \(0\)/)
  })

  it('disables the Reopen action with a "contact support" tooltip when the period is paid (G21)', async () => {
    mockedListPayPeriods.mockResolvedValueOnce({
      items: [
        buildPeriod({
          status: 'paid',
          paid_at: '2026-06-20T00:00:00Z',
          finalised_at: '2026-06-19T00:00:00Z',
        }),
      ],
      total: 1,
    })
    mockedListPeriodPayslips.mockResolvedValueOnce({ items: [], total: 0 })

    renderPage()

    const wrapper = await screen.findByTestId('reopen-disabled')
    expect(wrapper).toBeInTheDocument()
    expect(wrapper).toHaveAttribute('title', 'Already paid — contact support')
    // The Reopen button inside the wrapper is disabled.
    const reopenButton = wrapper.querySelector('button')
    expect(reopenButton).not.toBeNull()
    expect(reopenButton).toBeDisabled()

    // The active "Reopen" button (used for finalised status) should NOT
    // be present when the period is paid.
    expect(screen.queryByTestId('reopen-button')).not.toBeInTheDocument()
  })
})
