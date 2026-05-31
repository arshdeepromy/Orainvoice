/**
 * OverviewTab — Staff Detail tabbed shell, task E3.
 *
 * Validates: Requirements R2 (incl. residency_type), R3, R4, R6, G1, G2, G3.
 *
 * Cases covered:
 *   1. Renders all six sections.
 *   2. residency_type='citizen' → visa_expiry_date input hidden.
 *   3. residency_type='work_visa' → visa_expiry_date input shown.
 *   4. employee_id=null → inline G1 warning shown; quick-set PUTs and refreshes.
 *   5. employment_start_date=null → inline G3 warning shown.
 *   6. Below-min-wage save → modal appears; confirm triggers PUT with override flag.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPut = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, put: mockPut, post: mockPost },
  }
})

// PayRateHistoryPanel has its own tests; render a stub so this test
// can focus on the OverviewTab's own behaviour.
vi.mock('../../components/PayRateHistoryPanel', () => ({
  default: ({ staffId }: { staffId: string }) => (
    <div data-testid="pay-rate-history-panel-stub">history:{staffId}</div>
  ),
}))

import apiClient from '@/api/client'
import OverviewTab from '../OverviewTab'

const STAFF_ID = '11111111-2222-3333-4444-555555555555'

interface Overrides {
  employee_id?: string | null
  employment_start_date?: string | null
  residency_type?: string
  visa_expiry_date?: string | null
  hourly_rate?: string | null
  ird_number?: string | null
  bank_account_number?: string | null
}

function buildStaff(overrides: Overrides = {}) {
  return {
    id: STAFF_ID,
    org_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    user_id: null,
    name: 'Aroha Smith',
    first_name: 'Aroha',
    last_name: 'Smith',
    email: 'aroha@example.com',
    phone: '021000000',
    employee_id: 'EMP-100',
    position: 'Mechanic',
    reporting_to: null,
    reporting_to_name: null,
    shift_start: null,
    shift_end: null,
    role_type: 'employee',
    hourly_rate: '30.00',
    overtime_rate: '45.00',
    is_active: true,
    availability_schedule: {},
    skills: ['Brakes'],
    employment_start_date: '2024-01-01',
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

describe('OverviewTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders all six sections', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: buildStaff(),
    })

    render(<OverviewTab staffId={STAFF_ID} />)

    await screen.findByTestId('overview-tab')
    expect(screen.getByRole('region', { name: 'Personal' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Employment' })).toBeInTheDocument()
    expect(
      screen.getByRole('region', { name: 'Tax and Pay' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Schedule' })).toBeInTheDocument()
    expect(
      screen.getByRole('region', { name: 'Clock-in and roster delivery' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Skills' })).toBeInTheDocument()
    // PayRateHistoryPanel rendered inside Tax & Pay.
    expect(
      screen.getByTestId('pay-rate-history-panel-stub'),
    ).toBeInTheDocument()
  })

  it('hides visa_expiry_date when residency_type is citizen', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: buildStaff({ residency_type: 'citizen' }),
    })

    render(<OverviewTab staffId={STAFF_ID} />)

    await screen.findByTestId('overview-tab')
    expect(screen.queryByTestId('visa-expiry-row')).not.toBeInTheDocument()
  })

  it('shows visa_expiry_date when residency_type is work_visa', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: buildStaff({
        residency_type: 'work_visa',
        visa_expiry_date: '2026-12-31',
      }),
    })

    render(<OverviewTab staffId={STAFF_ID} />)

    await screen.findByTestId('overview-tab')
    expect(screen.getByTestId('visa-expiry-row')).toBeInTheDocument()
  })

  it('reveals visa_expiry_date after switching residency to work_visa in edit mode', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: buildStaff({ residency_type: 'citizen' }),
    })
    const user = userEvent.setup()
    render(<OverviewTab staffId={STAFF_ID} />)

    await screen.findByTestId('overview-tab')
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    expect(screen.queryByTestId('visa-expiry-row')).not.toBeInTheDocument()

    const select = screen.getByTestId('residency-type-select') as HTMLSelectElement
    await user.selectOptions(select, 'work_visa')

    expect(screen.getByTestId('visa-expiry-row')).toBeInTheDocument()
    expect(screen.getByTestId('visa-expiry-input')).toBeInTheDocument()

    // Switch back → input hides again, value preserved in form state.
    await user.selectOptions(select, 'citizen')
    expect(screen.queryByTestId('visa-expiry-row')).not.toBeInTheDocument()
  })

  it('shows the G1 missing-employee_id warning and quick-sets via PUT', async () => {
    const get = apiClient.get as ReturnType<typeof vi.fn>
    const put = apiClient.put as ReturnType<typeof vi.fn>
    get
      .mockResolvedValueOnce({ data: buildStaff({ employee_id: null }) })
      .mockResolvedValueOnce({ data: buildStaff({ employee_id: 'EMP-001' }) })
    put.mockResolvedValueOnce({ data: buildStaff({ employee_id: 'EMP-001' }) })

    const user = userEvent.setup()
    render(<OverviewTab staffId={STAFF_ID} />)

    const banner = await screen.findByTestId('warning-missing-employee-id')
    expect(banner).toBeInTheDocument()

    const input = screen.getByTestId('quick-employee-id-input') as HTMLInputElement
    await user.type(input, 'EMP-001')
    await user.click(screen.getByTestId('quick-employee-id-save'))

    await waitFor(() => {
      expect(put).toHaveBeenCalledWith(`/api/v2/staff/${STAFF_ID}`, {
        employee_id: 'EMP-001',
      })
    })

    // Banner disappears once the refresh resolves with a non-null employee_id.
    await waitFor(() => {
      expect(
        screen.queryByTestId('warning-missing-employee-id'),
      ).not.toBeInTheDocument()
    })
  })

  it('shows the G3 missing-start-date warning', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: buildStaff({ employment_start_date: null }),
    })

    render(<OverviewTab staffId={STAFF_ID} />)

    const banner = await screen.findByTestId('warning-missing-start-date')
    expect(banner).toBeInTheDocument()
    expect(screen.getByTestId('quick-start-date-input')).toBeInTheDocument()
  })

  it('opens the min-wage modal on 422 and re-submits with override on confirm', async () => {
    const get = apiClient.get as ReturnType<typeof vi.fn>
    const put = apiClient.put as ReturnType<typeof vi.fn>
    get.mockResolvedValueOnce({ data: buildStaff({ hourly_rate: '30.00' }) })
    put
      // First save → backend rejects with 422.
      .mockRejectedValueOnce({
        response: {
          status: 422,
          data: {
            detail: {
              detail: 'minimum_wage_below_threshold',
              threshold: 23.15,
            },
          },
        },
      })
      // Second save (with override) → succeeds.
      .mockResolvedValueOnce({
        data: buildStaff({ hourly_rate: '20.00' }),
      })

    const user = userEvent.setup()
    render(<OverviewTab staffId={STAFF_ID} />)

    await screen.findByTestId('overview-tab')
    await user.click(screen.getByRole('button', { name: 'Edit' }))

    const hourly = screen.getByTestId('hourly-rate-input') as HTMLInputElement
    await user.clear(hourly)
    await user.type(hourly, '20.00')

    await user.click(screen.getByRole('button', { name: 'Save' }))

    // Modal should appear.
    const modal = await screen.findByRole('dialog')
    expect(modal).toBeInTheDocument()
    expect(within(modal).getByText(/below NZ minimum wage/i)).toBeInTheDocument()

    await user.click(within(modal).getByRole('button', { name: /continue anyway/i }))

    await waitFor(() => {
      expect(put).toHaveBeenCalledTimes(2)
    })
    const secondCallBody = put.mock.calls[1][1]
    expect(secondCallBody.minimum_wage_override).toBe(true)
    // <input type="number"> normalises '20.00' → '20' via the DOM, so
    // this assertion just guards against losing the value entirely.
    expect(parseFloat(secondCallBody.hourly_rate)).toBe(20)
  })
})
