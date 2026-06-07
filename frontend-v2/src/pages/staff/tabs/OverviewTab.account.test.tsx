import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import OverviewTab from './OverviewTab'
import { getStaffMonthStats, type StaffMonthStats } from '@/api/staff'

/**
 * OverviewTab — Account panel component tests (Task 14.2).
 *
 * Covers Requirement 9:
 *  - R9.1/R9.2/R9.3: linked account renders "Login access", "User role", and
 *    "Last sign-in" rows with the role and a formatted sign-in date.
 *  - R9.4: a null last sign-in renders "—".
 *  - R9.5: an unlinked account renders the "No account?" prompt with a
 *    "Create user account" action (and no role / last-sign-in rows).
 *  - R9.6: activating "Create user account" opens the create-account modal,
 *    and submitting it POSTs to /api/v2/staff/{id}/create-account.
 *
 * `@/api/client` (default export) is mocked so the staff GET resolves a
 * configurable StaffMember fixture and POST can be asserted. `@/api/staff`'s
 * `getStaffMonthStats` is mocked to drive `user_role` / `last_sign_in`.
 */

// --- hoisted mutable fixtures + spies -------------------------------------
const h = vi.hoisted(() => ({
  staff: null as Record<string, unknown> | null,
  post: vi.fn(async () => ({ data: {} })),
}))

vi.mock('@/api/staff', () => ({
  getStaffMonthStats: vi.fn(),
}))

vi.mock('@/api/client', () => {
  const get = vi.fn(async (url: string) => {
    // Single staff record: /api/v2/staff/{id}
    if (/^\/api\/v2\/staff\/[^/]+$/.test(url)) {
      return { data: h.staff }
    }
    // Manager-login resolver hits the list endpoint /api/v2/staff
    if (url === '/api/v2/staff') {
      return { data: { staff: [], total: 0 } }
    }
    return { data: {} }
  })
  return {
    default: {
      get,
      post: h.post,
      put: vi.fn(async () => ({ data: {} })),
      delete: vi.fn(async () => ({ data: {} })),
    },
  }
})

const mockGetStaffMonthStats = vi.mocked(getStaffMonthStats)

/**
 * Build a complete StaffMember object matching the interface in
 * OverviewTab.tsx, with sensible defaults and overridable fields.
 */
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

function renderOverview() {
  return render(
    <MemoryRouter>
      <OverviewTab staffId="staff-1" />
    </MemoryRouter>,
  )
}

/** Resolve the Account section once the async staff load has completed. */
async function findAccountPanel(): Promise<HTMLElement> {
  const panel = await screen.findByLabelText('Account')
  return panel
}

beforeEach(() => {
  h.staff = makeStaff()
  h.post.mockReset()
  h.post.mockResolvedValue({ data: {} })
  mockGetStaffMonthStats.mockReset()
  mockGetStaffMonthStats.mockResolvedValue(makeStats())
})

describe('OverviewTab — Account panel', () => {
  it('renders Login access, User role and a formatted Last sign-in for a linked account (R9.1, R9.2, R9.3)', async () => {
    h.staff = makeStaff({ user_id: 'user-1' })
    mockGetStaffMonthStats.mockResolvedValue(
      makeStats({
        user_role: 'org_admin',
        last_sign_in: '2026-05-20T08:30:00Z',
      }),
    )

    renderOverview()

    const panel = await findAccountPanel()

    // R9.1 — the three account labels render.
    expect(within(panel).getByText('Login access')).toBeInTheDocument()
    expect(within(panel).getByText('User role')).toBeInTheDocument()
    expect(within(panel).getByText('Last sign-in')).toBeInTheDocument()

    // R9.2 — linked account shows a login-access indicator ("Active") and the role.
    expect(within(panel).getByText('Active')).toBeInTheDocument()
    await waitFor(() =>
      expect(within(panel).getByText('org_admin')).toBeInTheDocument(),
    )

    // R9.3 — Last sign-in renders a non-"—" formatted date value.
    const lastSignInLabel = within(panel).getByText('Last sign-in')
    const lastSignInValue = lastSignInLabel.nextElementSibling as HTMLElement
    await waitFor(() => {
      expect(lastSignInValue.textContent?.trim()).not.toBe('—')
      expect(lastSignInValue.textContent?.trim()).not.toBe('')
    })
  })

  it('renders "—" for Last sign-in when the linked account has no sign-in timestamp (R9.4)', async () => {
    h.staff = makeStaff({ user_id: 'user-1' })
    mockGetStaffMonthStats.mockResolvedValue(
      makeStats({ user_role: 'salesperson', last_sign_in: null }),
    )

    renderOverview()

    const panel = await findAccountPanel()
    const lastSignInLabel = within(panel).getByText('Last sign-in')
    const lastSignInValue = lastSignInLabel.nextElementSibling as HTMLElement

    await waitFor(() =>
      expect(within(panel).getByText('salesperson')).toBeInTheDocument(),
    )
    expect(lastSignInValue.textContent?.trim()).toBe('—')
  })

  it('renders the "No account?" prompt and Create action for an unlinked account (R9.5)', async () => {
    h.staff = makeStaff({ user_id: null })

    renderOverview()

    const panel = await findAccountPanel()

    // The prompt + create action render.
    expect(within(panel).getByText('No account?')).toBeInTheDocument()
    expect(
      within(panel).getByRole('button', { name: 'Create user account' }),
    ).toBeInTheDocument()

    // Login access indicator reads "None" for an unlinked account.
    expect(within(panel).getByText('None')).toBeInTheDocument()

    // The role / last-sign-in rows are NOT shown for an unlinked account.
    expect(within(panel).queryByText('User role')).not.toBeInTheDocument()
    expect(within(panel).queryByText('Last sign-in')).not.toBeInTheDocument()
  })

  it('opens the create-account modal and POSTs to create-account on submit (R9.6)', async () => {
    const user = userEvent.setup()
    h.staff = makeStaff({ user_id: null, email: 'jordan@example.com' })

    renderOverview()

    const panel = await findAccountPanel()
    await user.click(
      within(panel).getByRole('button', { name: 'Create user account' }),
    )

    // The modal renders — its heading + password field appear.
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByRole('heading', { name: 'Create user account' }),
    ).toBeInTheDocument()
    const passwordInput = within(dialog).getByLabelText('Temporary password')
    expect(passwordInput).toBeInTheDocument()

    // Fill a valid password and submit.
    await user.type(passwordInput, 'sup3rs3cret')
    await user.click(within(dialog).getByRole('button', { name: 'Create account' }))

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1))
    const [url, body] = h.post.mock.calls[0]
    expect(url).toBe('/api/v2/staff/staff-1/create-account')
    expect(body).toEqual({ password: 'sup3rs3cret' })
  })
})
