/**
 * TerminationModal — unit tests (Phase 4 task D4).
 *
 * Cases covered:
 *   1. Modal renders the form, both informational banners (G16 + G25),
 *     and the three final-pay-options toggles.
 *   2. Submit is disabled until BOTH end_date and reason are filled.
 *   3. Critical interaction — submitting calls terminateStaff with the
 *     expected payload and invokes onTerminated + onClose.
 */

import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/payslips', () => ({
  terminateStaff: vi.fn(),
}))

import { terminateStaff } from '@/api/payslips'
import TerminationModal from '../TerminationModal'

const STAFF_ID = '11111111-2222-3333-4444-555555555555'

const mockedTerminate = terminateStaff as ReturnType<typeof vi.fn>

describe('TerminationModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the form, banners, and final-pay options when open', () => {
    render(
      <TerminationModal
        staffId={STAFF_ID}
        staffName="Aroha Smith"
        open
        onClose={() => {}}
      />,
    )

    // Informational text mentions both staff name and the s27 explainer.
    expect(
      screen.getByText(/End employment for Aroha Smith/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Future-dated approved leave/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Final payslip pay period/i),
    ).toBeInTheDocument()

    // All three final-pay toggles render.
    expect(
      screen.getByTestId('termination-pay-annual-leave'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('termination-pay-alt-days')).toBeInTheDocument()
    expect(
      screen.getByTestId('termination-pay-casual-8pct'),
    ).toBeInTheDocument()

    // Inputs.
    expect(screen.getByTestId('termination-end-date')).toBeInTheDocument()
    expect(screen.getByTestId('termination-reason')).toBeInTheDocument()
  })

  it('keeps the submit button disabled until reason is filled', async () => {
    const user = userEvent.setup()
    render(
      <TerminationModal
        staffId={STAFF_ID}
        staffName="Aroha"
        open
        onClose={() => {}}
      />,
    )

    const submit = screen.getByTestId('termination-submit') as HTMLButtonElement

    // The end_date defaults to today on open, so reason is the only
    // missing field. Submit must remain disabled.
    expect(submit.disabled).toBe(true)

    await user.type(screen.getByTestId('termination-reason'), 'Resigning')

    await waitFor(() => {
      expect(submit.disabled).toBe(false)
    })
  })

  it('submits the form with the chosen options and notifies callbacks', async () => {
    mockedTerminate.mockResolvedValueOnce({
      staff_id: STAFF_ID,
      end_date: '2026-06-30',
      payout_summary: { annual_hours: '80.00', alt_days: 2 },
    })

    const onClose = vi.fn()
    const onTerminated = vi.fn()
    const user = userEvent.setup()

    render(
      <TerminationModal
        staffId={STAFF_ID}
        staffName="Aroha"
        open
        onClose={onClose}
        onTerminated={onTerminated}
      />,
    )

    const dateInput = screen.getByTestId(
      'termination-end-date',
    ) as HTMLInputElement
    fireEvent.change(dateInput, { target: { value: '2026-06-30' } })

    await user.type(
      screen.getByTestId('termination-reason'),
      'Resignation',
    )

    // Untoggle the casual 8% remainder so we can verify the payload
    // captures the chosen options (rather than the defaults).
    await user.click(screen.getByTestId('termination-pay-casual-8pct'))

    await user.click(screen.getByTestId('termination-submit'))

    await waitFor(() => {
      expect(mockedTerminate).toHaveBeenCalledTimes(1)
    })
    expect(mockedTerminate).toHaveBeenCalledWith(STAFF_ID, {
      end_date: '2026-06-30',
      reason: 'Resignation',
      final_pay_options: {
        pay_annual_leave: true,
        pay_alt_days: true,
        pay_casual_8pct_remainder: false,
      },
    })

    await waitFor(() => {
      expect(onTerminated).toHaveBeenCalledTimes(1)
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })
})
