/**
 * WageVariancePage — unit tests (Phase 4 task D6).
 *
 * Cases covered:
 *   1. Empty state — server returns no rows → renders the empty hint.
 *   2. Populated table — renders staff rows with money columns.
 *   3. Critical interaction — rows with above_threshold === true are
 *      highlighted via the data-above-threshold attribute.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/payslips', () => ({
  listPayPeriods: vi.fn(),
  getWageVarianceReport: vi.fn(),
}))

import { listPayPeriods, getWageVarianceReport } from '@/api/payslips'
import type {
  PayPeriod,
  WageVarianceReport,
  WageVarianceRow,
} from '@/api/payslips'
import WageVariancePage from '../WageVariancePage'

const ORG = '00000000-0000-0000-0000-000000000001'

const mockedListPeriods = listPayPeriods as ReturnType<typeof vi.fn>
const mockedReport = getWageVarianceReport as ReturnType<typeof vi.fn>

function buildPeriod(overrides: Partial<PayPeriod> = {}): PayPeriod {
  return {
    id: '11111111-2222-3333-4444-555555555555',
    org_id: ORG,
    start_date: '2026-06-01',
    end_date: '2026-06-14',
    pay_date: '2026-06-17',
    status: 'finalised',
    created_at: '2026-06-01T00:00:00Z',
    finalised_at: '2026-06-15T00:00:00Z',
    paid_at: null,
    ...overrides,
  }
}

function buildReport(items: WageVarianceRow[]): WageVarianceReport {
  return {
    items,
    total: items.length,
    threshold_pct: '10',
    current_period_id: '11111111-2222-3333-4444-555555555555',
    previous_period_id: '22222222-3333-4444-5555-666666666666',
  }
}

describe('WageVariancePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedListPeriods.mockResolvedValue({
      items: [
        buildPeriod(),
        buildPeriod({
          id: '22222222-3333-4444-5555-666666666666',
          start_date: '2026-05-18',
          end_date: '2026-05-31',
          pay_date: '2026-06-03',
        }),
      ],
      total: 2,
    })
  })

  it('shows the empty-state hint when the report returns no rows', async () => {
    mockedReport.mockResolvedValueOnce(buildReport([]))

    render(<WageVariancePage />)

    await waitFor(() => {
      expect(screen.getByTestId('wage-variance-empty')).toBeInTheDocument()
    })
  })

  it('renders the populated variance table with money + percentage columns', async () => {
    mockedReport.mockResolvedValueOnce(
      buildReport([
        {
          staff_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          current_gross: '1500.00',
          previous_gross: '1200.00',
          delta: '300.00',
          delta_pct: '25.00',
          above_threshold: true,
        },
        {
          staff_id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          current_gross: '1200.00',
          previous_gross: '1180.00',
          delta: '20.00',
          delta_pct: '1.69',
          above_threshold: false,
        },
      ]),
    )

    render(<WageVariancePage />)

    await waitFor(() => {
      expect(screen.getByTestId('wage-variance-table')).toBeInTheDocument()
    })

    // Both rows render.
    expect(
      screen.getByTestId(
        'wage-variance-row-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId(
        'wage-variance-row-bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
      ),
    ).toBeInTheDocument()

    // Currency + percentage formatting.
    expect(screen.getByText(/\$1,500\.00/)).toBeInTheDocument()
    expect(screen.getAllByText(/\$1,200\.00/).length).toBeGreaterThan(0)
    expect(screen.getByText(/25\.00%/)).toBeInTheDocument()
  })

  it('flags rows where above_threshold === true via data attribute', async () => {
    mockedReport.mockResolvedValueOnce(
      buildReport([
        {
          staff_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          current_gross: '1500.00',
          previous_gross: '1200.00',
          delta: '300.00',
          delta_pct: '25.00',
          above_threshold: true,
        },
        {
          staff_id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          current_gross: '1200.00',
          previous_gross: '1180.00',
          delta: '20.00',
          delta_pct: '1.69',
          above_threshold: false,
        },
      ]),
    )

    render(<WageVariancePage />)

    const flagged = await screen.findByTestId(
      'wage-variance-row-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    )
    const notFlagged = await screen.findByTestId(
      'wage-variance-row-bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
    )
    expect(flagged).toHaveAttribute('data-above-threshold', 'true')
    expect(notFlagged).toHaveAttribute('data-above-threshold', 'false')
  })
})
