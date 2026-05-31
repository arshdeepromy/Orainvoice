/**
 * PayPeriodsPage — unit tests (Phase 4 task D5).
 *
 * Cases covered:
 *   1. Empty state — empty list shows the empty-state hint.
 *   2. Populated table — renders rows with status chips.
 *   3. Critical interaction (G21) — Reopen button is disabled with the
 *      "Already paid — contact support" tooltip when status='paid'.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/payslips', () => ({
  listPayPeriods: vi.fn(),
  createPayPeriod: vi.fn(),
  updatePayPeriod: vi.fn(),
  reopenPayPeriod: vi.fn(),
}))

import { listPayPeriods } from '@/api/payslips'
import type { PayPeriod } from '@/api/payslips'
import PayPeriodsPage from '../PayPeriodsPage'

const ORG = '00000000-0000-0000-0000-000000000001'

const mockedList = listPayPeriods as ReturnType<typeof vi.fn>

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

describe('PayPeriodsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the empty-state hint when there are no pay periods', async () => {
    mockedList.mockResolvedValueOnce({ items: [], total: 0 })

    render(<PayPeriodsPage />)

    await waitFor(() => {
      expect(screen.getByTestId('pay-periods-empty')).toBeInTheDocument()
    })
    expect(screen.getByTestId('pay-periods-empty')).toHaveTextContent(
      /No pay periods yet/i,
    )
  })

  it('renders the populated table with status chips for each row', async () => {
    mockedList.mockResolvedValueOnce({
      items: [
        buildPeriod(),
        buildPeriod({
          id: '22222222-3333-4444-5555-666666666666',
          start_date: '2026-05-18',
          end_date: '2026-05-31',
          pay_date: '2026-06-03',
          status: 'finalised',
          finalised_at: '2026-06-01T00:00:00Z',
        }),
      ],
      total: 2,
    })

    render(<PayPeriodsPage />)

    await waitFor(() => {
      expect(screen.getByTestId('pay-periods-table')).toBeInTheDocument()
    })

    expect(screen.getByText('open')).toBeInTheDocument()
    expect(screen.getByText('finalised')).toBeInTheDocument()
  })

  it('disables the Reopen button with the "contact support" tooltip when the period is paid (G21)', async () => {
    mockedList.mockResolvedValueOnce({
      items: [
        buildPeriod({
          id: '99999999-8888-7777-6666-555555555555',
          status: 'paid',
          finalised_at: '2026-05-25T00:00:00Z',
          paid_at: '2026-06-03T00:00:00Z',
        }),
      ],
      total: 1,
    })

    render(<PayPeriodsPage />)

    const wrapper = await screen.findByTestId(
      'pay-period-reopen-disabled-99999999-8888-7777-6666-555555555555',
    )
    expect(wrapper).toBeInTheDocument()
    expect(wrapper).toHaveAttribute(
      'title',
      'Already paid — contact support',
    )
    const button = wrapper.querySelector('button')
    expect(button).not.toBeNull()
    expect(button).toBeDisabled()
  })

  it('shows an enabled Reopen button for finalised periods', async () => {
    mockedList.mockResolvedValueOnce({
      items: [
        buildPeriod({
          id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
          status: 'finalised',
          finalised_at: '2026-06-01T00:00:00Z',
        }),
      ],
      total: 1,
    })

    render(<PayPeriodsPage />)

    const reopen = await screen.findByTestId(
      'pay-period-reopen-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    )
    expect(reopen).toBeInTheDocument()
    expect(reopen).not.toBeDisabled()
  })
})
