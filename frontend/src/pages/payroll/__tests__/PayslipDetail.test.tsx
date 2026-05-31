/**
 * PayslipDetail — unit tests (Staff Management Phase 4, tasks D2 + D8).
 *
 * Cases covered:
 *   1. Renders hours, allowances, and deductions sections from getPayslip.
 *   2. PDF iframe appears when status='finalised' (D8).
 *   3. PDF iframe NOT shown when status='draft'.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/api/payslips', () => ({
  getPayslip: vi.fn(),
  updatePayslip: vi.fn(),
  finalisePayslip: vi.fn(),
  emailPayslip: vi.fn(),
  voidPayslip: vi.fn(),
  downloadPayslipPdf: vi.fn(),
}))

import {
  downloadPayslipPdf,
  getPayslip,
} from '@/api/payslips'
import type { PayslipDetail as PayslipDetailType } from '@/api/payslips'

import PayslipDetail from '../PayslipDetail'

const PAYSLIP_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

function buildDetail(
  overrides: Partial<PayslipDetailType> = {},
): PayslipDetailType {
  return {
    id: PAYSLIP_ID,
    org_id: '00000000-0000-0000-0000-000000000001',
    staff_id: 'cccccccc-dddd-eeee-ffff-aaaaaaaaaaaa',
    staff_name: 'Aroha Smith',
    pay_period_id: '11111111-2222-3333-4444-555555555555',
    pay_period: {
      id: '11111111-2222-3333-4444-555555555555',
      org_id: '00000000-0000-0000-0000-000000000001',
      start_date: '2026-06-01',
      end_date: '2026-06-14',
      pay_date: '2026-06-17',
      status: 'open',
      created_at: '2026-06-01T00:00:00Z',
      finalised_at: null,
      paid_at: null,
    },
    status: 'draft',
    ordinary_hours: '40.00',
    overtime_hours: '0.00',
    public_holiday_hours: '0.00',
    ordinary_rate: '30.00',
    overtime_rate: '45.00',
    public_holiday_rate: '45.00',
    gross_pay: '1200.00',
    gross_ytd: '1200.00',
    net_pay: '950.00',
    pdf_file_key: null,
    emailed_at: null,
    finalised_at: null,
    notes: null,
    created_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
    allowances: [
      {
        id: 'al-1',
        payslip_id: PAYSLIP_ID,
        allowance_type_id: 'at-1',
        label: 'Tool allowance',
        quantity: '5',
        unit: 'shift',
        amount: '50.00',
        taxable: true,
      },
      {
        id: 'al-2',
        payslip_id: PAYSLIP_ID,
        allowance_type_id: 'at-2',
        label: 'Phone allowance',
        quantity: '1',
        unit: 'period',
        amount: '20.00',
        taxable: false,
      },
    ],
    deductions: [
      {
        id: 'de-1',
        payslip_id: PAYSLIP_ID,
        kind: 'paye',
        label: 'PAYE',
        amount: '180.00',
      },
      {
        id: 'de-2',
        payslip_id: PAYSLIP_ID,
        kind: 'kiwisaver_employee',
        label: 'KiwiSaver (3%)',
        amount: '36.00',
      },
      {
        id: 'de-3',
        payslip_id: PAYSLIP_ID,
        kind: 'kiwisaver_employer',
        label: 'KiwiSaver employer (3%)',
        amount: '36.00',
      },
    ],
    reimbursements: [],
    leave_lines: [],
    ...overrides,
  }
}

const mockedGetPayslip = getPayslip as ReturnType<typeof vi.fn>
const mockedDownloadPayslipPdf = downloadPayslipPdf as ReturnType<typeof vi.fn>

// jsdom does not implement createObjectURL — stub for the iframe blob preview.
beforeEach(() => {
  vi.clearAllMocks()
  if (!('createObjectURL' in URL)) {
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:mock'),
    })
  } else {
    URL.createObjectURL = vi.fn(() => 'blob:mock') as typeof URL.createObjectURL
  }
  if (!('revokeObjectURL' in URL)) {
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
  } else {
    URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL
  }
})

function renderDetail(payslipId: string = PAYSLIP_ID) {
  return render(
    <MemoryRouter initialEntries={[`/payroll/payslips/${payslipId}`]}>
      <PayslipDetail payslipId={payslipId} />
    </MemoryRouter>,
  )
}

describe('PayslipDetail', () => {
  it('renders hours, allowances, and deductions for a draft payslip', async () => {
    mockedGetPayslip.mockResolvedValueOnce(buildDetail())

    renderDetail()

    await waitFor(() => {
      expect(screen.getByTestId('payslip-detail')).toBeInTheDocument()
    })

    // Hours section + public-holiday band row visible.
    expect(screen.getByTestId('payslip-hours-section')).toBeInTheDocument()
    expect(screen.getByTestId('public-holiday-row')).toBeInTheDocument()

    // Hours inputs are populated.
    const ordHours = screen.getByTestId(
      'ordinary-hours-input',
    ) as HTMLInputElement
    expect(ordHours.value).toBe('40.00')

    // Allowance rows rendered with quantity × unit_price = amount.
    const toolRow = screen.getByTestId('allowance-row-al-1')
    expect(toolRow).toHaveTextContent('Tool allowance')
    expect(toolRow).toHaveTextContent(/5\s*shifts/)
    expect(toolRow).toHaveTextContent(/\$50\.00/)

    // Period unit shows just the amount.
    const phoneRow = screen.getByTestId('allowance-row-al-2')
    expect(phoneRow).toHaveTextContent('Phone allowance')
    expect(phoneRow).toHaveTextContent(/\$20\.00/)

    // Deductions render including the informational employer KiwiSaver.
    expect(screen.getByTestId('deduction-row-paye')).toHaveTextContent('PAYE')
    expect(
      screen.getByTestId('deduction-row-kiwisaver_employer'),
    ).toHaveTextContent(/informational, not subtracted/)
  })

  it('does NOT render the PDF preview iframe when status=draft', async () => {
    mockedGetPayslip.mockResolvedValueOnce(buildDetail({ status: 'draft' }))

    renderDetail()

    await waitFor(() => {
      expect(screen.getByTestId('payslip-detail')).toBeInTheDocument()
    })

    expect(
      screen.queryByTestId('payslip-pdf-preview-section'),
    ).not.toBeInTheDocument()
    expect(screen.queryByTestId('payslip-pdf-iframe')).not.toBeInTheDocument()
    // downloadPayslipPdf must NOT be auto-called for a draft.
    expect(mockedDownloadPayslipPdf).not.toHaveBeenCalled()
  })

  it('renders the PDF preview iframe when status=finalised (D8)', async () => {
    mockedGetPayslip.mockResolvedValueOnce(
      buildDetail({
        status: 'finalised',
        finalised_at: '2026-06-18T00:00:00Z',
        pdf_file_key: 'payslips/org/abc.pdf',
      }),
    )
    mockedDownloadPayslipPdf.mockResolvedValueOnce(
      new Blob(['%PDF-1.4 mock'], { type: 'application/pdf' }),
    )

    renderDetail()

    await waitFor(() => {
      expect(
        screen.getByTestId('payslip-pdf-preview-section'),
      ).toBeInTheDocument()
    })

    // Iframe appears once the blob URL is constructed.
    await waitFor(() => {
      expect(screen.getByTestId('payslip-pdf-iframe')).toBeInTheDocument()
    })
    const iframe = screen.getByTestId('payslip-pdf-iframe') as HTMLIFrameElement
    expect(iframe.src).toContain('blob:')
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)

    // Save button is disabled because the payslip is finalised.
    const saveButton = screen.getByTestId('payslip-save-button')
    expect(saveButton).toBeDisabled()
  })
})
