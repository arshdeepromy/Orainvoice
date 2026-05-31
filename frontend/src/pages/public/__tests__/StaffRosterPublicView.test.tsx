/**
 * Unit tests for StaffRosterPublicView (Phase 1 task E9).
 *
 * **Validates: Requirement R9.4** — public read-only roster viewer.
 *
 * Scenarios covered:
 * - 200 → renders staff name, week range, and entries.
 * - 200 with empty entries → "No shifts scheduled" empty state.
 * - 404 ``token_not_found`` → "not valid" message.
 * - 410 ``token_expired_staff_deactivated`` → "revoked" message (G4).
 * - 410 ``token_expired`` → "expired" / "fresh link" message.
 * - 429 → "Too many requests" message (G5).
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

/* ------------------------------------------------------------------ */
/*  Mocks (must be declared before imports that use them)              */
/* ------------------------------------------------------------------ */

vi.mock('react-router-dom', () => ({
  useParams: () => ({ token: 'tok_test_abc' }),
}))

/* Tag class used in lieu of the real AxiosError. ``isAxiosError`` in
   the mocked axios module checks ``instanceof`` so any rejection
   constructed with this class is treated as an axios error by the
   component. The real axios package is replaced by the mock below
   before the component module loads. Defined inside ``vi.hoisted``
   so it's available when ``vi.mock``'s factory closure runs. */
const { mockAxiosGet, FakeAxiosError } = vi.hoisted(() => {
  class FakeAxiosError extends Error {
    response: { status: number; data: unknown }
    constructor(message: string, status: number, data: unknown) {
      super(message)
      this.response = { status, data }
    }
  }
  return {
    mockAxiosGet: vi.fn(),
    FakeAxiosError,
  }
})

vi.mock('axios', () => ({
  default: {
    get: mockAxiosGet,
    isAxiosError: (err: unknown): err is InstanceType<typeof FakeAxiosError> =>
      err instanceof FakeAxiosError,
  },
}))

/* ------------------------------------------------------------------ */
/*  Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import StaffRosterPublicView from '../StaffRosterPublicView'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function buildRosterPayload(overrides: Record<string, unknown> = {}) {
  return {
    staff_name: 'Aroha Tāmaki',
    week_start: '2026-06-08',
    week_end: '2026-06-15',
    entries: [
      {
        start_time: '2026-06-09T08:00:00+00:00',
        end_time: '2026-06-09T16:30:00+00:00',
        title: 'Workshop shift',
        notes: 'Bring high-vis vest',
        entry_type: 'job',
      },
      {
        start_time: '2026-06-11T09:00:00+00:00',
        end_time: '2026-06-11T17:00:00+00:00',
        title: null,
        notes: null,
        entry_type: 'other',
      },
    ],
    ...overrides,
  }
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('StaffRosterPublicView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the staff name, week range, and shift entries on a 200 response', async () => {
    mockAxiosGet.mockResolvedValue({ data: buildRosterPayload() })

    render(<StaffRosterPublicView />)

    // Staff name surfaced from the payload
    await waitFor(() => {
      expect(screen.getByText('Aroha Tāmaki')).toBeInTheDocument()
    })

    // Week range header includes both formatted dates
    expect(screen.getByText(/Week of/i)).toBeInTheDocument()
    // The two shift titles render — one explicit, one falling back to "Shift"
    expect(screen.getByText('Workshop shift')).toBeInTheDocument()
    expect(screen.getByText('Shift')).toBeInTheDocument()

    // Notes for the first entry render
    expect(screen.getByText('Bring high-vis vest')).toBeInTheDocument()

    // No "no shifts" empty state when entries are present
    expect(
      screen.queryByText(/No shifts scheduled for this week/i),
    ).not.toBeInTheDocument()
  })

  it('shows the empty state when entries is an empty array', async () => {
    mockAxiosGet.mockResolvedValue({
      data: buildRosterPayload({ entries: [] }),
    })

    render(<StaffRosterPublicView />)

    await waitFor(() => {
      expect(
        screen.getByText(/No shifts scheduled for this week/i),
      ).toBeInTheDocument()
    })

    // Header still renders
    expect(screen.getByText('Aroha Tāmaki')).toBeInTheDocument()
  })

  it('renders the "not valid" message when the API returns 404 token_not_found', async () => {
    mockAxiosGet.mockRejectedValue(
      new FakeAxiosError('Not Found', 404, { detail: 'token_not_found' }),
    )

    render(<StaffRosterPublicView />)

    await waitFor(() => {
      expect(screen.getByText(/Roster unavailable/i)).toBeInTheDocument()
    })
    expect(
      screen.getByText(/This roster link is not valid/i),
    ).toBeInTheDocument()
  })

  it('renders the "revoked" message when 410 token_expired_staff_deactivated is returned (G4)', async () => {
    mockAxiosGet.mockRejectedValue(
      new FakeAxiosError('Gone', 410, {
        detail: 'token_expired_staff_deactivated',
      }),
    )

    render(<StaffRosterPublicView />)

    await waitFor(() => {
      expect(screen.getByText(/Roster link revoked/i)).toBeInTheDocument()
    })
    expect(
      screen.getByText(
        /staff member has been deactivated|deactivated/i,
      ),
    ).toBeInTheDocument()
  })

  it('renders the "expired — ask for fresh link" message when 410 token_expired is returned', async () => {
    mockAxiosGet.mockRejectedValue(
      new FakeAxiosError('Gone', 410, { detail: 'token_expired' }),
    )

    render(<StaffRosterPublicView />)

    await waitFor(() => {
      expect(screen.getByText(/Roster link expired/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Ask your manager to send a fresh one/i)).toBeInTheDocument()
  })

  it('renders the rate-limit message when 429 is returned (G5)', async () => {
    mockAxiosGet.mockRejectedValue(
      new FakeAxiosError('Too Many Requests', 429, null),
    )

    render(<StaffRosterPublicView />)

    await waitFor(() => {
      expect(screen.getByText(/Too many requests/i)).toBeInTheDocument()
    })
    expect(
      screen.getByText(/Please wait a moment and refresh/i),
    ).toBeInTheDocument()
  })
})
