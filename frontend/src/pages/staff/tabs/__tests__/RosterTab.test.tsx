/**
 * RosterTab — Staff Detail tabbed shell, task E4.
 *
 * Validates: Requirements R7, R8, R9.
 *
 * Cases covered:
 *   1. Renders the WeekNavigator + Email/SMS toolbar buttons.
 *   2. Click "Email roster" → POSTs to /api/v2/staff/:id/email-roster
 *      with the current Monday's week_start, then shows a success toast.
 *   3. 422 with detail.reason='no_email' → error toast surfaces the
 *      reason verbatim.
 *   4. Clicking "Next →" advances the week by 7 days; the next email
 *      send goes out with the new week_start.
 *
 * The embedded `ScheduleCalendar` is mocked to a simple placeholder so
 * the tab can be unit-tested in isolation (the calendar already has its
 * own tests).
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

vi.mock('@/pages/schedule/ScheduleCalendar', () => ({
  default: ({ focusStaffId }: { focusStaffId?: string }) => (
    <div data-testid="schedule-calendar-stub">
      schedule-for:{focusStaffId ?? '(none)'}
    </div>
  ),
}))

import apiClient from '@/api/client'
import RosterTab from '../RosterTab'

const STAFF_ID = '11111111-2222-3333-4444-555555555555'

/** Compute the Monday-aligned ISO date (YYYY-MM-DD) for a given Date. */
function mondayIso(d: Date): string {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const day = x.getDay()
  const diff = day === 0 ? -6 : 1 - day
  x.setDate(x.getDate() + diff)
  const yyyy = x.getFullYear()
  const mm = String(x.getMonth() + 1).padStart(2, '0')
  const dd = String(x.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/** Add `days` days to an ISO YYYY-MM-DD string, returning a new ISO string. */
function addDaysIso(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y, (m ?? 1) - 1, d ?? 1)
  dt.setDate(dt.getDate() + days)
  const yyyy = dt.getFullYear()
  const mm = String(dt.getMonth() + 1).padStart(2, '0')
  const dd = String(dt.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

describe('RosterTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the WeekNavigator + Email/SMS buttons + the embedded calendar', () => {
    render(<RosterTab staffId={STAFF_ID} />)

    // Toolbar (R7 / R8 / R9 entry points)
    expect(
      screen.getByRole('group', { name: /roster week navigator/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /previous week/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /this week/i })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /next week/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /email roster/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /send roster sms/i }),
    ).toBeInTheDocument()

    // Embedded calendar received the focusStaffId prop
    expect(screen.getByTestId('schedule-calendar-stub')).toHaveTextContent(
      `schedule-for:${STAFF_ID}`,
    )
  })

  it('emails the roster for the current week and shows a success toast', async () => {
    const post = apiClient.post as ReturnType<typeof vi.fn>
    post.mockResolvedValueOnce({ data: { ok: true, message_id: 'msg_123' } })

    const user = userEvent.setup()
    render(<RosterTab staffId={STAFF_ID} />)

    await user.click(screen.getByRole('button', { name: /email roster/i }))

    await waitFor(() => {
      expect(post).toHaveBeenCalledTimes(1)
    })
    expect(post).toHaveBeenCalledWith(
      `/api/v2/staff/${STAFF_ID}/email-roster`,
      { week_start: mondayIso(new Date()) },
    )

    // Success toast
    expect(
      await screen.findByTestId('toast-success'),
    ).toHaveTextContent(/roster emailed successfully/i)
  })

  it('surfaces the reason on a 422 error response', async () => {
    const post = apiClient.post as ReturnType<typeof vi.fn>
    post.mockRejectedValueOnce({
      response: {
        status: 422,
        data: { detail: { reason: 'no_email' } },
      },
    })

    const user = userEvent.setup()
    render(<RosterTab staffId={STAFF_ID} />)

    await user.click(screen.getByRole('button', { name: /email roster/i }))

    const toast = await screen.findByTestId('toast-error')
    expect(toast).toHaveTextContent(/no_email/i)
  })

  it('advances the active week when "Next →" is clicked', async () => {
    const post = apiClient.post as ReturnType<typeof vi.fn>
    post.mockResolvedValue({ data: { ok: true, message_id: 'msg_next' } })

    const user = userEvent.setup()
    render(<RosterTab staffId={STAFF_ID} />)

    const initialMonday = mondayIso(new Date())
    const nextMonday = addDaysIso(initialMonday, 7)

    await user.click(screen.getByRole('button', { name: /next week/i }))
    await user.click(screen.getByRole('button', { name: /email roster/i }))

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith(
        `/api/v2/staff/${STAFF_ID}/email-roster`,
        { week_start: nextMonday },
      )
    })
  })
})
