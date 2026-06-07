import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ThisMonthPanel from './ThisMonthPanel'
import { getStaffMonthStats, type StaffMonthStats } from '@/api/staff'

/**
 * ThisMonthPanel component tests (Task 13.3).
 *
 * Covers R8.1 (labelled "This month" with four metric rows), R8.2 (fetches
 * with period 'this_month' on load), and R8.7 (AbortController aborts the
 * in-flight request on unmount / staff change; non-abort failures render all
 * four metrics as "—" without crashing).
 *
 * `getStaffMonthStats` is mocked so the panel resolves deterministically and
 * we can inspect the call arguments (staffId, period, AbortSignal).
 */

vi.mock('@/api/staff', () => ({
  getStaffMonthStats: vi.fn(),
}))

const mockGetStaffMonthStats = vi.mocked(getStaffMonthStats)

/** Build a fully-populated StaffMonthStats with overridable metrics. */
function makeStats(overrides: Partial<StaffMonthStats> = {}): StaffMonthStats {
  return {
    period: 'this_month',
    hours_logged: { value: 5, has_data: true },
    jobs_completed: { value: 12, has_data: true },
    billable_ratio: { value: 80, has_data: true },
    on_time_rate: { value: 0, has_data: false },
    last_sign_in: null,
    user_role: null,
    ...overrides,
  }
}

beforeEach(() => {
  mockGetStaffMonthStats.mockReset()
  mockGetStaffMonthStats.mockResolvedValue(makeStats())
})

describe('ThisMonthPanel', () => {
  it('renders the "This month" label and all four metric row labels (R8.1)', async () => {
    render(<ThisMonthPanel staffId="staff-1" />)

    expect(screen.getByText('This month')).toBeInTheDocument()
    expect(screen.getByText('Hours logged')).toBeInTheDocument()
    expect(screen.getByText('Jobs completed')).toBeInTheDocument()
    expect(screen.getByText('Billable ratio')).toBeInTheDocument()
    expect(screen.getByText('On-time rate')).toBeInTheDocument()
  })

  it("fetches with period 'this_month' on load and renders formatted values (R8.2)", async () => {
    render(<ThisMonthPanel staffId="staff-42" />)

    await waitFor(() => expect(mockGetStaffMonthStats).toHaveBeenCalledTimes(1))

    const call = mockGetStaffMonthStats.mock.calls[0]
    expect(call[0]).toBe('staff-42')
    expect(call[1]).toBe('this_month')
    // Third arg is an AbortSignal used to cancel the in-flight request.
    expect(call[2]).toBeInstanceOf(AbortSignal)

    // hours_logged {value:5, has_data:true} → "5.0h"
    await waitFor(() => expect(screen.getByText('5.0h')).toBeInTheDocument())
    // billable_ratio {value:80, has_data:true} → "80%"
    expect(screen.getByText('80%')).toBeInTheDocument()
    // jobs_completed {value:12, has_data:true} → "12"
    expect(screen.getByText('12')).toBeInTheDocument()
    // on_time_rate has_data:false → "—"
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('aborts the in-flight request on unmount (R8.7)', async () => {
    const { unmount } = render(<ThisMonthPanel staffId="staff-1" />)

    await waitFor(() => expect(mockGetStaffMonthStats).toHaveBeenCalledTimes(1))
    const signal = mockGetStaffMonthStats.mock.calls[0][2] as AbortSignal
    expect(signal.aborted).toBe(false)

    unmount()

    expect(signal.aborted).toBe(true)
  })

  it('re-fetches with the new staffId and aborts the previous request when staffId changes (R8.7)', async () => {
    const { rerender } = render(<ThisMonthPanel staffId="staff-1" />)

    await waitFor(() => expect(mockGetStaffMonthStats).toHaveBeenCalledTimes(1))
    const firstSignal = mockGetStaffMonthStats.mock.calls[0][2] as AbortSignal
    expect(firstSignal.aborted).toBe(false)

    rerender(<ThisMonthPanel staffId="staff-2" />)

    // Effect re-keys on staffId → second fetch with the new id.
    await waitFor(() => expect(mockGetStaffMonthStats).toHaveBeenCalledTimes(2))
    const secondCall = mockGetStaffMonthStats.mock.calls[1]
    expect(secondCall[0]).toBe('staff-2')
    expect(secondCall[1]).toBe('this_month')

    // The first request's signal is aborted on staff change.
    expect(firstSignal.aborted).toBe(true)
  })

  it('renders "—" for all four metrics when the fetch fails, without crashing (R8.6/R8.7)', async () => {
    mockGetStaffMonthStats.mockRejectedValue(new Error('network error'))

    render(<ThisMonthPanel staffId="staff-1" />)

    await waitFor(() => expect(mockGetStaffMonthStats).toHaveBeenCalledTimes(1))

    // The panel still renders its label (did not crash).
    expect(screen.getByText('This month')).toBeInTheDocument()

    // All four metric rows render "—".
    await waitFor(() => {
      expect(screen.getAllByText('—')).toHaveLength(4)
    })
    // No formatted values leaked through.
    expect(screen.queryByText('5.0h')).not.toBeInTheDocument()
    expect(screen.queryByText('80%')).not.toBeInTheDocument()
  })
})
