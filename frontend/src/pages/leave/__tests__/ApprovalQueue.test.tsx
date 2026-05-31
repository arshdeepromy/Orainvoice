/**
 * ApprovalQueue UI tests — confidential family-violence filtering.
 *
 * The frontend trusts the backend's `_apply_confidential_filter` helper
 * (per design §4.4): the queue list endpoint never returns FV rows the
 * current user can't see. So the frontend's job is just to render what
 * comes back and decorate confidential rows with a "Confidential" badge.
 *
 * Cases covered:
 *   1. Non-permitted admin — API returns the filtered list (no FV rows).
 *      The page must not render any FV row.
 *   2. Permitted admin — API returns FV rows alongside regular rows.
 *      The FV rows render and carry a "Confidential" badge.
 *   3. Confidential badge appears specifically on rows whose
 *      leave_type_code === 'family_violence'.
 *
 * **Validates: Staff Management Phase 2 task D10**
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../../../api/leave', async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    '../../../api/leave',
  )
  return {
    ...actual,
    listApprovalQueue: vi.fn(),
    approveLeaveRequest: vi.fn(),
    rejectLeaveRequest: vi.fn(),
  }
})

import * as leaveApi from '../../../api/leave'
import type { LeaveRequest } from '../../../api/leave'
import ApprovalQueue from '../ApprovalQueue'

function makeRequest(overrides: Partial<LeaveRequest> = {}): LeaveRequest {
  return {
    id: 'req-' + Math.random().toString(36).slice(2, 8),
    org_id: 'org-1',
    staff_id: 'staff-1',
    staff_name: 'Alice Anderson',
    leave_type_id: 'lt-annual',
    leave_type_code: 'annual',
    leave_type_name: 'Annual leave',
    start_date: '2026-06-12',
    end_date: '2026-06-19',
    hours_requested: '40.00',
    status: 'pending',
    reason: 'Family trip',
    relationship_to_subject: null,
    partial_day_start_time: null,
    attachment_upload_id: null,
    requested_by: 'user-1',
    requested_by_name: 'Alice Anderson',
    decided_by: null,
    decided_at: null,
    decision_notes: null,
    created_at: '2026-06-01T10:00:00Z',
    updated_at: '2026-06-01T10:00:00Z',
    ...overrides,
  }
}

const mockedList = leaveApi.listApprovalQueue as unknown as ReturnType<typeof vi.fn>

describe('ApprovalQueue confidential family-violence filtering', () => {
  beforeEach(() => {
    mockedList.mockReset()
  })

  it('renders no family-violence rows when the backend filters them out (non-permitted admin)', async () => {
    const annualRow = makeRequest({
      id: 'req-annual',
      leave_type_code: 'annual',
      leave_type_name: 'Annual leave',
    })
    mockedList.mockResolvedValue({ items: [annualRow], total: 1 })

    render(<ApprovalQueue />)

    await waitFor(() => {
      expect(screen.getByTestId('approval-row-req-annual')).toBeInTheDocument()
    })

    // No FV rows should be rendered, and no Confidential badges either.
    expect(screen.queryByText(/family.?violence/i)).not.toBeInTheDocument()
    expect(screen.queryAllByText(/^Confidential$/i)).toHaveLength(0)
  })

  it('renders family-violence rows with a Confidential badge when the backend returns them (permitted admin)', async () => {
    const annualRow = makeRequest({
      id: 'req-annual',
      leave_type_code: 'annual',
      leave_type_name: 'Annual leave',
    })
    const fvRow = makeRequest({
      id: 'req-fv',
      leave_type_code: 'family_violence',
      leave_type_name: 'Family violence leave',
      staff_name: 'Bob Brown',
      reason: 'Sensitive — should be hidden in UI',
    })
    mockedList.mockResolvedValue({ items: [annualRow, fvRow], total: 2 })

    render(<ApprovalQueue />)

    // Both rows render
    await waitFor(() => {
      expect(screen.getByTestId('approval-row-req-annual')).toBeInTheDocument()
      expect(screen.getByTestId('approval-row-req-fv')).toBeInTheDocument()
    })

    // Confidential badge is on the FV row only
    expect(screen.getByTestId('confidential-badge-req-fv')).toBeInTheDocument()
    expect(
      screen.queryByTestId('confidential-badge-req-annual'),
    ).not.toBeInTheDocument()

    // Reason on the FV row is hidden in the UI even though the backend included it.
    expect(
      screen.queryByText('Sensitive — should be hidden in UI'),
    ).not.toBeInTheDocument()

    // Annual reason renders normally.
    expect(screen.getByText('Family trip')).toBeInTheDocument()
  })

  it('passes the active tab status to the listApprovalQueue API call', async () => {
    mockedList.mockResolvedValue({ items: [], total: 0 })

    render(<ApprovalQueue />)

    await waitFor(() => {
      expect(mockedList).toHaveBeenCalled()
    })

    // Default tab is "Pending".
    const firstCall = mockedList.mock.calls[0]
    expect(firstCall[0]).toMatchObject({ status: 'pending' })
  })
})
