/**
 * PayslipsTab — unit tests (Phase 4 task D3).
 *
 * Cases covered:
 *   1. Empty state — renders the empty-state hint when no payslips.
 *   2. Populated list — renders status chip + period range + gross/net.
 *   3. Critical interaction — Email button only visible for finalised
 *      payslips; Void button only shown to admins for non-voided rows.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the auth context so we can flip role between admin / non-admin.
const mockUseAuth = vi.fn()
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

vi.mock('@/api/payslips', () => ({
  listStaffPayslips: vi.fn(),
  downloadPayslipPdf: vi.fn(),
  emailPayslip: vi.fn(),
  voidPayslip: vi.fn(),
}))

import { listStaffPayslips } from '@/api/payslips'
import type { Payslip } from '@/api/payslips'
import PayslipsTab from '../PayslipsTab'

const STAFF_ID = '11111111-2222-3333-4444-555555555555'
const ORG = '00000000-0000-0000-0000-000000000001'

const mockedList = listStaffPayslips as ReturnType<typeof vi.fn>

function buildPayslip(overrides: Partial<Payslip> = {}): Payslip {
  return {
    id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    org_id: ORG,
    staff_id: STAFF_ID,
    staff_name: 'Aroha Smith',
    pay_period_id: 'pppppppp-pppp-pppp-pppp-pppppppppppp',
    pay_period: {
      id: 'pppppppp-pppp-pppp-pppp-pppppppppppp',
      org_id: ORG,
      start_date: '2026-06-01',
      end_date: '2026-06-14',
      pay_date: '2026-06-17',
      status: 'finalised',
      created_at: '2026-06-01T00:00:00Z',
      finalised_at: '2026-06-15T00:00:00Z',
      paid_at: null,
    },
    status: 'finalised',
    ordinary_hours: '40.00',
    overtime_hours: '0.00',
    public_holiday_hours: '0.00',
    ordinary_rate: '30.00',
    overtime_rate: '45.00',
    public_holiday_rate: '45.00',
    gross_pay: '1200.00',
    gross_ytd: '1200.00',
    net_pay: '950.00',
    pdf_file_key: 'payslips/org/...',
    emailed_at: null,
    finalised_at: '2026-06-15T00:00:00Z',
    notes: null,
    created_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
    ...overrides,
  }
}

describe('PayslipsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuth.mockReturnValue({ user: { role: 'org_admin' } })
  })

  it('renders the empty-state hint when no payslips exist', async () => {
    mockedList.mockResolvedValueOnce({ items: [], total: 0 })

    render(<PayslipsTab staffId={STAFF_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('payslips-tab-empty')).toBeInTheDocument()
    })
    expect(screen.getByTestId('payslips-tab-empty')).toHaveTextContent(
      /No payslips have been generated/i,
    )
  })

  it('renders the populated table with status chip, period range, gross + net', async () => {
    mockedList.mockResolvedValueOnce({
      items: [
        buildPayslip(),
        buildPayslip({
          id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          status: 'draft',
          gross_pay: '900.00',
          net_pay: '720.00',
          finalised_at: null,
        }),
      ],
      total: 2,
    })

    render(<PayslipsTab staffId={STAFF_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('payslips-tab-table')).toBeInTheDocument()
    })

    // Both status chips are visible (case-insensitive — Badge renders
    // the raw status text).
    expect(screen.getByText('finalised')).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()

    // Period range
    expect(screen.getAllByText(/1 Jun 2026/).length).toBeGreaterThan(0)

    // Money columns
    expect(screen.getByText(/\$1,200\.00/)).toBeInTheDocument()
    expect(screen.getByText(/\$950\.00/)).toBeInTheDocument()
  })

  it('shows Email button only for finalised payslips and Void button only to admins', async () => {
    mockedList.mockResolvedValueOnce({
      items: [
        buildPayslip(), // finalised
        buildPayslip({
          id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
          status: 'draft',
          finalised_at: null,
        }),
        buildPayslip({
          id: 'cccccccc-dddd-eeee-ffff-000000000000',
          status: 'voided',
          finalised_at: null,
        }),
      ],
      total: 3,
    })

    render(<PayslipsTab staffId={STAFF_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('payslips-tab-table')).toBeInTheDocument()
    })

    // Email button: only visible for the finalised row.
    expect(
      screen.getByTestId(
        'payslip-tab-email-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId(
        'payslip-tab-email-bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
      ),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId(
        'payslip-tab-email-cccccccc-dddd-eeee-ffff-000000000000',
      ),
    ).not.toBeInTheDocument()

    // Void button: visible for finalised and draft, hidden for voided.
    expect(
      screen.getByTestId(
        'payslip-tab-void-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId(
        'payslip-tab-void-bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId(
        'payslip-tab-void-cccccccc-dddd-eeee-ffff-000000000000',
      ),
    ).not.toBeInTheDocument()
  })

  it('hides the Void button for non-admin viewers', async () => {
    mockUseAuth.mockReturnValue({ user: { role: 'salesperson' } })
    mockedList.mockResolvedValueOnce({
      items: [buildPayslip()],
      total: 1,
    })

    render(<PayslipsTab staffId={STAFF_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('payslips-tab-table')).toBeInTheDocument()
    })

    expect(
      screen.queryByTestId(
        'payslip-tab-void-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      ),
    ).not.toBeInTheDocument()
  })
})
