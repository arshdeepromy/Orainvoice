import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import OverviewTab from './OverviewTab'
import { getStaffMonthStats, type StaffMonthStats } from '@/api/staff'

/**
 * OverviewTab — preservation component tests (Task 15.2).
 *
 * The Overview restyle must not drop any existing content. Covers
 * Requirement 10:
 *  - R10.1: the six sections (Personal, Employment, Tax & Pay, Schedule,
 *    Clock-in & roster delivery, Skills) all still render.
 *  - R10.2: inline compliance warnings still render (the G1 missing-employee-id
 *    and G3 missing-start-date banners).
 *  - R10.3: the PayRateHistoryPanel still renders.
 *  - R10.4: the RecurringAllowancesPanel still renders.
 *
 * The two child panels (PayRateHistoryPanel, RecurringAllowancesPanel) make
 * their own API calls; for a preservation test we only care that OverviewTab
 * *renders* them, so they are mocked with lightweight stubs exposing a stable
 * testid. This keeps the test robust and independent of the panels' internals.
 *
 * `@/api/client` (default export) is mocked so the staff GET resolves a
 * configurable StaffMember fixture; `@/api/staff`'s `getStaffMonthStats` is
 * mocked so the right-sidebar This-month/Account panels settle.
 */

// --- panel stubs ----------------------------------------------------------
vi.mock('../components/PayRateHistoryPanel', () => ({
  default: () => <div data-testid="pay-rate-history-panel" />,
}))
vi.mock('../components/RecurringAllowancesPanel', () => ({
  default: () => <div data-testid="recurring-allowances-panel" />,
}))

// --- hoisted mutable fixtures ---------------------------------------------
const h = vi.hoisted(() => ({
  staff: null as Record<string, unknown> | null,
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
    // Manager-fallback chip resolver hits the list endpoint /api/v2/staff
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

beforeEach(() => {
  h.staff = makeStaff()
  mockGetStaffMonthStats.mockReset()
  mockGetStaffMonthStats.mockResolvedValue(makeStats())
})

describe('OverviewTab — preservation', () => {
  it('renders all six detail sections (R10.1)', async () => {
    renderOverview()

    // Wait for the async staff load to resolve (the tab shell appears).
    await screen.findByTestId('overview-tab')

    // The six sections are exposed as <section aria-label="…"> landmarks.
    expect(screen.getByLabelText('Personal')).toBeInTheDocument()
    expect(screen.getByLabelText('Employment')).toBeInTheDocument()
    expect(screen.getByLabelText('Tax and Pay')).toBeInTheDocument()
    expect(screen.getByLabelText('Schedule')).toBeInTheDocument()
    expect(
      screen.getByLabelText('Clock-in and roster delivery'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Skills')).toBeInTheDocument()
  })

  it('renders the inline compliance warnings when fields are missing (R10.2)', async () => {
    h.staff = makeStaff({ employee_id: null })
    renderOverview()

    // G1 — missing employee id banner.
    expect(
      await screen.findByTestId('warning-missing-employee-id'),
    ).toBeInTheDocument()
  })

  it('renders the missing-start-date compliance warning (R10.2)', async () => {
    h.staff = makeStaff({ employment_start_date: null })
    renderOverview()

    // G3 — missing employment start date banner.
    expect(
      await screen.findByTestId('warning-missing-start-date'),
    ).toBeInTheDocument()
  })

  it('renders the PayRateHistoryPanel (R10.3)', async () => {
    renderOverview()

    expect(
      await screen.findByTestId('pay-rate-history-panel'),
    ).toBeInTheDocument()
  })

  it('renders the RecurringAllowancesPanel (R10.4)', async () => {
    renderOverview()

    expect(
      await screen.findByTestId('recurring-allowances-panel'),
    ).toBeInTheDocument()
  })
})
