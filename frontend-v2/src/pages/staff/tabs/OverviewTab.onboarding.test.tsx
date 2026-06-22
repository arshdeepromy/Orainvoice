import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import OverviewTab from './OverviewTab'
import {
  getStaffMonthStats,
  getOnboardingLinkStatus,
  resendOnboardingLink,
  revokeOnboardingLink,
  type StaffMonthStats,
  type OnboardingLinkStatus,
} from '@/api/staff'

/**
 * OverviewTab — Onboarding link card tests (Task 10.2).
 *
 * Covers Requirements 10.1, 10.2, 10.3, 13.1, 13.2, 13.5:
 *  - R13.5/R13.1: the card fetches the lifecycle status on mount and renders a
 *    headline per state (not_started / in_progress / completed / none).
 *  - R13.2: an in_progress link shows a progress bar with the completion
 *    percentage and a "Last saved …" line.
 *  - R10.2: Resend posts to the resend helper and surfaces an inline error when
 *    the email send fails.
 *  - R10.3: Revoke posts to the revoke helper and refetches the status.
 *  - Terminal/none states surface a "Send onboarding link" action.
 *
 * `@/api/staff` is mocked so the onboarding helpers resolve configurable
 * fixtures; `@/api/client` is mocked so the staff GET resolves a StaffMember.
 */

const h = vi.hoisted(() => ({
  staff: null as Record<string, unknown> | null,
}))

vi.mock('@/api/staff', () => ({
  getStaffMonthStats: vi.fn(),
  getOnboardingLinkStatus: vi.fn(),
  resendOnboardingLink: vi.fn(),
  revokeOnboardingLink: vi.fn(),
}))

vi.mock('@/api/client', () => {
  const get = vi.fn(async (url: string) => {
    if (/^\/api\/v2\/staff\/[^/]+$/.test(url)) {
      return { data: h.staff }
    }
    if (url === '/api/v2/staff') {
      return { data: { staff: [], total: 0 } }
    }
    return { data: {} }
  })
  return {
    default: {
      get,
      post: vi.fn(async () => ({ data: {} })),
      put: vi.fn(async () => ({ data: {} })),
      delete: vi.fn(async () => ({ data: {} })),
    },
  }
})

const mockGetStaffMonthStats = vi.mocked(getStaffMonthStats)
const mockGetStatus = vi.mocked(getOnboardingLinkStatus)
const mockResend = vi.mocked(resendOnboardingLink)
const mockRevoke = vi.mocked(revokeOnboardingLink)

function makeStaff(overrides: Record<string, unknown> = {}) {
  return {
    id: 'staff-1',
    org_id: 'org-1',
    user_id: 'user-1',
    name: 'Jordan Blake',
    first_name: 'Jordan',
    last_name: 'Blake',
    email: 'jordan@example.com',
    phone: '021 111 2222',
    employee_id: 'EMP-001',
    position: 'Mechanic',
    reporting_to: null,
    reporting_to_name: null,
    shift_start: null,
    shift_end: null,
    role_type: 'employee',
    hourly_rate: '32.50',
    overtime_rate: null,
    is_active: true,
    availability_schedule: {},
    skills: [],
    employment_start_date: '2024-01-15',
    employment_end_date: null,
    employment_type: 'permanent',
    standard_hours_per_week: '40',
    tax_code: 'M',
    ird_number: null,
    student_loan: false,
    kiwisaver_enrolled: false,
    kiwisaver_employee_rate: null,
    kiwisaver_employer_rate: '3.00',
    bank_account_number: null,
    probation_end_date: null,
    residency_type: 'citizen',
    visa_expiry_date: null,
    self_service_clock_enabled: false,
    on_file_photo_url: null,
    emergency_contact_name: null,
    emergency_contact_phone: null,
    weekly_roster_email_enabled: true,
    weekly_roster_sms_enabled: false,
    last_pay_review_date: null,
    employment_agreement_upload_id: null,
    ...overrides,
  }
}

function makeStats(overrides: Partial<StaffMonthStats> = {}): StaffMonthStats {
  return {
    period: 'this_month',
    hours_logged: { value: 0, has_data: false },
    jobs_completed: { value: 0, has_data: false },
    billable_ratio: { value: 0, has_data: false },
    on_time_rate: { value: 0, has_data: false },
    last_sign_in: null,
    user_role: null,
    ...overrides,
  }
}

function makeStatus(
  overrides: Partial<OnboardingLinkStatus> = {},
): OnboardingLinkStatus {
  return {
    state: 'none',
    expires_at: null,
    created_at: null,
    consumed_at: null,
    completion_percentage: null,
    last_saved_at: null,
    ...overrides,
  }
}

function renderOverview() {
  return render(
    <MemoryRouter>
      <OverviewTab staffId="staff-1" />
    </MemoryRouter>,
  )
}

async function findOnboardingCard(): Promise<HTMLElement> {
  return screen.findByTestId('onboarding-link-card')
}

beforeEach(() => {
  h.staff = makeStaff()
  mockGetStaffMonthStats.mockReset()
  mockGetStaffMonthStats.mockResolvedValue(makeStats())
  mockGetStatus.mockReset()
  mockResend.mockReset()
  mockRevoke.mockReset()
  mockResend.mockResolvedValue({
    onboarding_email_sent: true,
    onboarding_email_error: null,
    expires_at: '2026-06-20T00:00:00Z',
  })
  mockRevoke.mockResolvedValue({ status: 'revoked' })
})

describe('OverviewTab — Onboarding link card', () => {
  it('renders the not_started state with Resend and Revoke actions (R13.5, R10.2, R10.3)', async () => {
    mockGetStatus.mockResolvedValue(
      makeStatus({ state: 'not_started', expires_at: '2026-06-20T00:00:00Z' }),
    )

    renderOverview()
    const card = await findOnboardingCard()

    await waitFor(() =>
      expect(
        within(card).getByText(/not started yet/i),
      ).toBeInTheDocument(),
    )
    expect(
      within(card).getByTestId('onboarding-resend-btn'),
    ).toBeInTheDocument()
    expect(
      within(card).getByTestId('onboarding-revoke-btn'),
    ).toBeInTheDocument()
    // No "Send" button while a link is active.
    expect(
      within(card).queryByTestId('onboarding-send-btn'),
    ).not.toBeInTheDocument()
  })

  it('renders a progress bar, percentage and last-saved line when in_progress (R13.2)', async () => {
    mockGetStatus.mockResolvedValue(
      makeStatus({
        state: 'in_progress',
        expires_at: '2026-06-20T00:00:00Z',
        completion_percentage: 60,
        last_saved_at: '2026-06-15T09:30:00Z',
      }),
    )

    renderOverview()
    const card = await findOnboardingCard()

    await waitFor(() =>
      expect(within(card).getByText(/in progress/i)).toBeInTheDocument(),
    )
    const progress = within(card).getByTestId('onboarding-progress')
    expect(within(progress).getByText('60%')).toBeInTheDocument()
    expect(within(progress).getByText(/Last saved/i)).toBeInTheDocument()

    const bar = within(card).getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '60')
  })

  it('renders the completed state with no action buttons', async () => {
    mockGetStatus.mockResolvedValue(
      makeStatus({ state: 'completed', consumed_at: '2026-06-10T12:00:00Z' }),
    )

    renderOverview()
    const card = await findOnboardingCard()

    await waitFor(() =>
      expect(
        within(card).getByTestId('onboarding-link-state'),
      ).toHaveTextContent(/completed/i),
    )
    expect(
      within(card).queryByTestId('onboarding-resend-btn'),
    ).not.toBeInTheDocument()
    expect(
      within(card).queryByTestId('onboarding-revoke-btn'),
    ).not.toBeInTheDocument()
    expect(
      within(card).queryByTestId('onboarding-send-btn'),
    ).not.toBeInTheDocument()
  })

  it('renders a Send button for the none state and sends on click', async () => {
    const user = userEvent.setup()
    mockGetStatus.mockResolvedValue(makeStatus({ state: 'none' }))

    renderOverview()
    const card = await findOnboardingCard()

    await waitFor(() =>
      expect(
        within(card).getByText(/no active onboarding link/i),
      ).toBeInTheDocument(),
    )
    const sendBtn = within(card).getByTestId('onboarding-send-btn')
    await user.click(sendBtn)

    await waitFor(() => expect(mockResend).toHaveBeenCalledWith('staff-1'))
  })

  it('resends and refetches status on Resend (R10.2)', async () => {
    const user = userEvent.setup()
    mockGetStatus.mockResolvedValue(makeStatus({ state: 'not_started' }))

    renderOverview()
    const card = await findOnboardingCard()

    await user.click(
      await within(card).findByTestId('onboarding-resend-btn'),
    )

    await waitFor(() => expect(mockResend).toHaveBeenCalledWith('staff-1'))
    // initial mount fetch + refetch after resend.
    await waitFor(() => expect(mockGetStatus.mock.calls.length).toBeGreaterThanOrEqual(2))
  })

  it('surfaces an inline error when the resend email fails (R10.2)', async () => {
    const user = userEvent.setup()
    mockGetStatus.mockResolvedValue(makeStatus({ state: 'not_started' }))
    mockResend.mockResolvedValue({
      onboarding_email_sent: false,
      onboarding_email_error: 'send_failed',
      expires_at: '2026-06-20T00:00:00Z',
    })

    renderOverview()
    const card = await findOnboardingCard()

    await user.click(
      await within(card).findByTestId('onboarding-resend-btn'),
    )

    await waitFor(() =>
      expect(
        within(card).getByTestId('onboarding-link-error'),
      ).toBeInTheDocument(),
    )
  })

  it('revokes and refetches status on Revoke (R10.3)', async () => {
    const user = userEvent.setup()
    mockGetStatus.mockResolvedValue(makeStatus({ state: 'not_started' }))

    renderOverview()
    const card = await findOnboardingCard()

    await user.click(
      await within(card).findByTestId('onboarding-revoke-btn'),
    )

    await waitFor(() => expect(mockRevoke).toHaveBeenCalledWith('staff-1'))
    await waitFor(() => expect(mockGetStatus.mock.calls.length).toBeGreaterThanOrEqual(2))
  })

  it('falls back to the none state when the status fetch fails', async () => {
    mockGetStatus.mockRejectedValue(new Error('network'))

    renderOverview()
    const card = await findOnboardingCard()

    await waitFor(() =>
      expect(
        within(card).getByText(/no active onboarding link/i),
      ).toBeInTheDocument(),
    )
    expect(
      within(card).getByTestId('onboarding-send-btn'),
    ).toBeInTheDocument()
  })
})
