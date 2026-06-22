import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import OverviewTab from './OverviewTab'
import { getStaffMonthStats, type StaffMonthStats } from '@/api/staff'

/**
 * OverviewTab — per-staff pay-cycle selector tests (Task 12.3, Edit form).
 *
 * Covers the Edit-form selector behaviour:
 *  - REQ 1.5 / 1.6: no active cycles → selector hidden + configure hint shown.
 *  - REQ 1.3: when active cycles exist the selector prefills from the staff
 *    response's `pay_cycle_id` when `pay_cycle_is_default` is false (an
 *    explicit staff-level assignment).
 *  - REQ 1.4: when the staff resolves via the org default
 *    (`pay_cycle_is_default` true) the empty "Use organisation default" option
 *    is selected, not the resolved cycle.
 *  - REQ 2.2: submitting with a chosen cycle includes `pay_cycle_id` in the
 *    PUT /api/v2/staff/{id} payload.
 *  - REQ 3.3: choosing "Use organisation default" sends `pay_cycle_id` null to
 *    clear any existing staff-level assignment.
 *
 * The two child panels make their own API calls, so they're stubbed. `@/api/
 * client` is mocked so the single-staff GET resolves a configurable fixture,
 * `GET /api/v2/pay-cycles/` resolves a `{ items, total }` page, and PUT records
 * its payload. `@/api/staff` helpers are stubbed so the right-rail/onboarding
 * cards settle.
 */

// --- child panel stubs ----------------------------------------------------
vi.mock('../components/PayRateHistoryPanel', () => ({
  default: () => <div data-testid="pay-rate-history-panel" />,
}))
vi.mock('../components/RecurringAllowancesPanel', () => ({
  default: () => <div data-testid="recurring-allowances-panel" />,
}))

// --- hoisted mutable fixtures + spies -------------------------------------
const h = vi.hoisted(() => ({
  staff: null as Record<string, unknown> | null,
  payCycles: [] as Array<Record<string, unknown>>,
  putCalls: [] as Array<{ url: string; body: any }>,
}))

vi.mock('@/api/staff', () => ({
  getStaffMonthStats: vi.fn(),
  getOnboardingLinkStatus: vi.fn(async () => ({ state: 'none' })),
  resendOnboardingLink: vi.fn(async () => ({ onboarding_email_sent: true })),
  revokeOnboardingLink: vi.fn(async () => ({ status: 'revoked' })),
}))

vi.mock('@/api/client', () => {
  const get = vi.fn(async (url: string) => {
    // Single staff record: /api/v2/staff/{id}
    if (/^\/api\/v2\/staff\/[^/]+$/.test(url)) {
      return { data: h.staff }
    }
    // Manager-fallback chip resolver hits the list endpoint.
    if (url === '/api/v2/staff') {
      return { data: { staff: [], total: 0 } }
    }
    // Active pay cycles — always wrapped in { items, total } (safe shape).
    if (url === '/api/v2/pay-cycles/') {
      return { data: { items: h.payCycles, total: h.payCycles.length } }
    }
    return { data: {} }
  })
  const put = vi.fn(async (url: string, body?: any) => {
    h.putCalls.push({ url, body })
    return { data: h.staff }
  })
  return {
    default: {
      get,
      put,
      post: vi.fn(async () => ({ data: {} })),
      delete: vi.fn(async () => ({ data: {} })),
    },
  }
})

const mockGetStaffMonthStats = vi.mocked(getStaffMonthStats)

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
    // Per-staff pay cycle resolved fields (default: resolves to org default).
    pay_cycle_id: null,
    pay_cycle_name: null,
    pay_cycle_is_default: false,
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

function makeCycle(overrides: Record<string, unknown> = {}) {
  return {
    id: 'pc-weekly',
    name: 'Weekly',
    frequency: 'weekly',
    anchor_date: '2024-01-01',
    pay_date_offset_days: 3,
    is_default: false,
    ...overrides,
  }
}

/** Render the tab already in edit mode via the ?edit=1 deep link. */
function renderEdit() {
  return render(
    <MemoryRouter initialEntries={['/staff/staff-1?edit=1']}>
      <OverviewTab staffId="staff-1" />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  h.staff = makeStaff()
  h.payCycles = []
  h.putCalls = []
  mockGetStaffMonthStats.mockReset()
  mockGetStaffMonthStats.mockResolvedValue(makeStats())
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('OverviewTab Edit form — pay-cycle selector', () => {
  it('hides the selector and shows the configure hint when there are no active cycles (REQ 1.5, 1.6)', async () => {
    h.payCycles = []
    renderEdit()

    // Enter edit mode and let the pay-cycle field render.
    await screen.findByTestId('pay-cycle-empty-hint')
    expect(screen.queryByTestId('pay-cycle-select')).not.toBeInTheDocument()
    expect(
      screen.getByText(/No pay cycle configured/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Timesheets → Settings/i)).toBeInTheDocument()
  })

  it('prefills the selector from the staff response when pay_cycle_is_default is false (REQ 1.3)', async () => {
    h.payCycles = [
      makeCycle({ id: 'pc-weekly', name: 'Weekly', is_default: true }),
      makeCycle({ id: 'pc-fortnightly', name: 'Fortnightly' }),
    ]
    h.staff = makeStaff({
      pay_cycle_id: 'pc-fortnightly',
      pay_cycle_name: 'Fortnightly',
      pay_cycle_is_default: false,
    })
    renderEdit()

    const select = (await screen.findByTestId(
      'pay-cycle-select',
    )) as HTMLSelectElement
    expect(select.value).toBe('pc-fortnightly')
  })

  it('selects "Use organisation default" when the staff resolves via the org default (REQ 1.4)', async () => {
    h.payCycles = [
      makeCycle({ id: 'pc-weekly', name: 'Weekly', is_default: true }),
    ]
    // Resolved cycle is the org default — prefill must NOT pin it to the select.
    h.staff = makeStaff({
      pay_cycle_id: 'pc-weekly',
      pay_cycle_name: 'Weekly',
      pay_cycle_is_default: true,
    })
    renderEdit()

    const select = (await screen.findByTestId(
      'pay-cycle-select',
    )) as HTMLSelectElement
    expect(select.value).toBe('')
  })

  it('includes the chosen pay_cycle_id in the update payload (REQ 2.2)', async () => {
    const user = userEvent.setup()
    h.payCycles = [
      makeCycle({ id: 'pc-weekly', name: 'Weekly', is_default: true }),
      makeCycle({ id: 'pc-fortnightly', name: 'Fortnightly' }),
    ]
    h.staff = makeStaff()
    renderEdit()

    const select = (await screen.findByTestId(
      'pay-cycle-select',
    )) as HTMLSelectElement
    await user.selectOptions(select, 'pc-fortnightly')

    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(h.putCalls.length).toBeGreaterThan(0))
    const payload = h.putCalls[h.putCalls.length - 1].body
    expect(payload.pay_cycle_id).toBe('pc-fortnightly')
  })

  it('sends pay_cycle_id null when "Use organisation default" is chosen to clear an assignment (REQ 3.3)', async () => {
    const user = userEvent.setup()
    h.payCycles = [
      makeCycle({ id: 'pc-weekly', name: 'Weekly', is_default: true }),
      makeCycle({ id: 'pc-fortnightly', name: 'Fortnightly' }),
    ]
    // Staff currently has an explicit assignment → prefilled to pc-fortnightly.
    h.staff = makeStaff({
      pay_cycle_id: 'pc-fortnightly',
      pay_cycle_name: 'Fortnightly',
      pay_cycle_is_default: false,
    })
    renderEdit()

    const select = (await screen.findByTestId(
      'pay-cycle-select',
    )) as HTMLSelectElement
    expect(select.value).toBe('pc-fortnightly')

    // Switch back to the org default.
    await user.selectOptions(select, '')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(h.putCalls.length).toBeGreaterThan(0))
    const payload = h.putCalls[h.putCalls.length - 1].body
    expect(payload.pay_cycle_id).toBeNull()
  })
})
