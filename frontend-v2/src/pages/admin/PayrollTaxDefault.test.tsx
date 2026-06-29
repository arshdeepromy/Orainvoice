/**
 * PayrollTaxDefault — rendering tests for the Global Admin platform tax editor
 * (feature: payroll-tax-settings, task 11.3).
 *
 * Covers:
 *   • Render with mocked data: every documented Tax_Field appears — the PAYE
 *     bracket rows (incl. the open-ended top band), the five secondary code
 *     inputs, ACC rate + cap, student-loan rate + threshold, the five IETC
 *     params, the two KiwiSaver defaults, and the tax-year label.
 *   • A 422 response on save renders per-field inline error messages.
 *
 * The `@/api/payrollTax` module is partially mocked: `getPlatformTaxDefault`
 * and `updatePlatformTaxDefault` are stubbed while the pure helpers
 * (`parseFieldErrors`, `SECONDARY_TAX_CODES`) run for real so the per-field
 * error wiring is exercised end-to-end.
 *
 * **Validates: Requirements 2.1, 2.2**
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/payrollTax', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/payrollTax')>()
  return {
    ...actual,
    getPlatformTaxDefault: vi.fn(),
    updatePlatformTaxDefault: vi.fn(),
  }
})

import {
  getPlatformTaxDefault,
  updatePlatformTaxDefault,
  type PlatformTaxDefaultView,
} from '@/api/payrollTax'
import { PayrollTaxDefault } from './PayrollTaxDefault'

const mockGet = getPlatformTaxDefault as ReturnType<typeof vi.fn>
const mockUpdate = updatePlatformTaxDefault as ReturnType<typeof vi.fn>

/** Full PlatformTaxDefaultView fixture with the documented 2024/25 values. */
function fullView(): PlatformTaxDefaultView {
  return {
    paye_brackets: [
      { upper_limit: 15600, rate: 0.105 },
      { upper_limit: 53500, rate: 0.175 },
      { upper_limit: 78100, rate: 0.3 },
      { upper_limit: 180000, rate: 0.33 },
      { upper_limit: null, rate: 0.39 },
    ],
    secondary_rates: { SB: 0.105, S: 0.175, SH: 0.3, ST: 0.33, SA: 0.39 },
    acc_levy_rate: 0.016,
    acc_max_liable_earnings: 142283,
    student_loan_rate: 0.12,
    student_loan_threshold: 24128,
    ietc: {
      amount: 520,
      lower: 24000,
      abatement_start: 44000,
      abatement_rate: 0.13,
      upper: 48000,
    },
    default_kiwisaver_employee_rate: 3.0,
    default_kiwisaver_employer_rate: 3.0,
    tax_year_label: '2024/25',
    updated_at: '2026-01-15T03:30:00Z',
    updated_by: 'admin-uuid',
  }
}

function renderEditor() {
  return render(
    <MemoryRouter initialEntries={['/admin/payroll-tax-default']}>
      <PayrollTaxDefault />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PayrollTaxDefault — renders all documented fields', () => {
  it('shows every Tax_Field from the mocked platform default', async () => {
    mockGet.mockResolvedValue(fullView())
    renderEditor()

    // Tax-year label (display-only field).
    const taxYear = (await screen.findByLabelText(/Tax year label/i)) as HTMLInputElement
    expect(taxYear.value).toBe('2024/25')

    // PAYE bracket rows — the four finite upper limits each render in an input.
    expect(screen.getByDisplayValue('15600')).toBeInTheDocument()
    expect(screen.getByDisplayValue('53500')).toBeInTheDocument()
    expect(screen.getByDisplayValue('78100')).toBeInTheDocument()
    expect(screen.getByDisplayValue('180000')).toBeInTheDocument()
    // The open-ended top band is rendered as a non-editable placeholder row.
    expect(screen.getByText(/No upper limit \(top band\)/i)).toBeInTheDocument()

    // Five secondary tax code inputs (shown as percentages).
    expect((screen.getByLabelText('SB') as HTMLInputElement).value).toBe('10.5')
    expect((screen.getByLabelText('S') as HTMLInputElement).value).toBe('17.5')
    expect((screen.getByLabelText('SH') as HTMLInputElement).value).toBe('30')
    expect((screen.getByLabelText('ST') as HTMLInputElement).value).toBe('33')
    expect((screen.getByLabelText('SA') as HTMLInputElement).value).toBe('39')

    // ACC rate (percent) + cap (dollars).
    expect((screen.getByLabelText(/ACC levy rate/i) as HTMLInputElement).value).toBe('1.6')
    expect((screen.getByLabelText(/ACC max liable earnings/i) as HTMLInputElement).value).toBe(
      '142283',
    )

    // Student loan rate (percent) + threshold (dollars).
    expect((screen.getByLabelText(/Student loan rate/i) as HTMLInputElement).value).toBe('12')
    expect((screen.getByLabelText(/Student loan threshold/i) as HTMLInputElement).value).toBe(
      '24128',
    )

    // Five IETC parameters (dollar amounts/bounds + the percent abatement rate).
    expect((screen.getByLabelText(/^Amount/i) as HTMLInputElement).value).toBe('520')
    expect((screen.getByLabelText(/Lower bound/i) as HTMLInputElement).value).toBe('24000')
    expect((screen.getByLabelText(/Abatement start/i) as HTMLInputElement).value).toBe('44000')
    expect((screen.getByLabelText(/Abatement rate/i) as HTMLInputElement).value).toBe('13')
    expect((screen.getByLabelText(/Upper bound/i) as HTMLInputElement).value).toBe('48000')

    // Two KiwiSaver defaults.
    expect((screen.getByLabelText(/Employee default rate/i) as HTMLInputElement).value).toBe('3')
    expect((screen.getByLabelText(/Employer default rate/i) as HTMLInputElement).value).toBe('3')
  })
})

describe('PayrollTaxDefault — percentages convert back to fractions on save', () => {
  it('sends fractions to the backend even though the user edits percentages', async () => {
    mockGet.mockResolvedValue(fullView())
    mockUpdate.mockResolvedValue(fullView())

    renderEditor()
    await screen.findByLabelText(/Tax year label/i)

    // The user edits the ACC levy rate in percent terms: 1.6% → 2%.
    const accInput = screen.getByLabelText(/ACC levy rate/i) as HTMLInputElement
    expect(accInput.value).toBe('1.6')
    fireEvent.change(accInput, { target: { value: '2' } })

    fireEvent.click(screen.getByRole('button', { name: /Save tax default/i }))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    const payload = mockUpdate.mock.calls[0][0] as Record<string, unknown>

    // The edited percent (2) is persisted as the fraction 0.02.
    expect(payload.acc_levy_rate).toBe(0.02)
    // Untouched rates round-trip back to their original fractions, not percents.
    expect(payload.student_loan_rate).toBe(0.12)
    expect((payload.secondary_rates as Record<string, number>).S).toBe(0.175)
    expect((payload.ietc as Record<string, number>).abatement_rate).toBe(0.13)
    expect((payload.paye_brackets as { rate: number }[])[0].rate).toBe(0.105)
    // Dollar fields and KiwiSaver percents are unchanged by the conversion.
    expect(payload.acc_max_liable_earnings).toBe(142283)
    expect(payload.default_kiwisaver_employee_rate).toBe(3)
  })
})

describe('PayrollTaxDefault — 422 renders per-field inline errors', () => {
  it('surfaces per-field validation messages when save is rejected with a 422', async () => {
    mockGet.mockResolvedValue(fullView())
    mockUpdate.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: [
            { field: 'acc_levy_rate', message: 'ACC levy rate must be between 0 and 1' },
            {
              field: 'student_loan_threshold',
              message: 'Student loan threshold must not be negative',
            },
          ],
        },
      },
    })

    renderEditor()
    // Wait for the form to load.
    await screen.findByLabelText(/Tax year label/i)

    // Trigger a save.
    fireEvent.click(screen.getByRole('button', { name: /Save tax default/i }))

    // Per-field inline error messages render for the offending fields.
    expect(
      await screen.findByText('ACC levy rate must be between 0 and 1'),
    ).toBeInTheDocument()
    expect(
      await screen.findByText('Student loan threshold must not be negative'),
    ).toBeInTheDocument()
  })
})
