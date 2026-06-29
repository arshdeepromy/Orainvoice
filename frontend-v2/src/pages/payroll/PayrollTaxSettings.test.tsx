/**
 * Rendering tests for the Payroll org tax-settings surfaces
 * (feature: payroll-tax-settings, task 12.4).
 *
 * Covers:
 *   • Req 4.1 — the Settings control on the Payroll page renders when the
 *     authenticated user's role is `org_admin`.
 *   • Req 4.2 — the Settings control is omitted for any non-`org_admin` role.
 *   • Req 9.4 — the org tax-settings view shows an Inherited vs Override badge
 *     per Tax_Field (mixing override=true / override=false), and after resetting
 *     an overridden field the field re-renders as Inherited (the returned view
 *     drives the re-render).
 *
 * The Settings-control cases render `PayRunPage` with `useAuth` flipped between
 * roles (the typed `@/api/payslips` wrappers + the `@/api/client` probe are
 * mocked to deterministic empty shapes, and `ModuleGate` is a passthrough so the
 * page renders without the ModuleContext provider).
 *
 * The badge cases render `PayrollTaxSettings` with `@/api/payrollTax` partially
 * mocked: the network functions are stubbed while the pure helpers
 * (`SECONDARY_TAX_CODES`, `parseFieldErrors`) run for real.
 *
 * **Validates: Requirements 4.1, 4.2, 9.4**
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

// --- hoisted mutable auth fixture (shared by both surfaces) ----------------
const auth = vi.hoisted(() => ({ user: null as Record<string, unknown> | null }))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: auth.user }),
}))

// ModuleGate → passthrough so PayRunPage renders without ModuleContext.
vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// `@/api/client` is only used by PayRunPage for the `/pay-cycles/` probe.
vi.mock('@/api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }) },
}))

// Typed payslips wrappers used by PayRunPage.
vi.mock('@/api/payslips', () => ({
  listPayPeriods: vi.fn(),
  listPeriodPayslips: vi.fn(),
  generatePeriodPayslips: vi.fn(),
  bulkFinalisePeriod: vi.fn(),
  reopenPayPeriod: vi.fn(),
}))

// Org-tier payroll-tax client used by PayrollTaxSettings — partial mock so the
// real `SECONDARY_TAX_CODES` / `parseFieldErrors` helpers still run.
vi.mock('@/api/payrollTax', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/payrollTax')>()
  return {
    ...actual,
    getOrgTaxSettings: vi.fn(),
    updateOrgTaxSettings: vi.fn(),
    resetOrgTaxField: vi.fn(),
    resetAllOrgTaxFields: vi.fn(),
  }
})

import { listPayPeriods, listPeriodPayslips } from '@/api/payslips'
import {
  getOrgTaxSettings,
  resetOrgTaxField,
  type OrgTaxSettingsView,
} from '@/api/payrollTax'
import PayRunPage from './PayRunPage'
import PayrollTaxSettings from './PayrollTaxSettings'

const mockListPayPeriods = listPayPeriods as ReturnType<typeof vi.fn>
const mockListPeriodPayslips = listPeriodPayslips as ReturnType<typeof vi.fn>
const mockGetOrg = getOrgTaxSettings as ReturnType<typeof vi.fn>
const mockResetField = resetOrgTaxField as ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
  auth.user = null
  mockListPayPeriods.mockResolvedValue({ items: [], total: 0 })
  mockListPeriodPayslips.mockResolvedValue({ items: [], total: 0 })
})

/* ════════════════════════════════════════════════════════════════════════
 * Req 4.1 / 4.2 — Settings control visibility on the Payroll page
 * ════════════════════════════════════════════════════════════════════════ */

function renderPayRun() {
  return render(
    <MemoryRouter initialEntries={['/payroll/run']}>
      <PayRunPage />
    </MemoryRouter>,
  )
}

describe('PayRunPage — tax Settings control visibility', () => {
  it('renders the Settings control when the user is an org_admin (Req 4.1)', async () => {
    auth.user = {
      id: 'u1',
      email: 'admin@test.com',
      name: 'Admin',
      role: 'org_admin',
      org_id: 'org-1',
    }
    renderPayRun()

    // The control is part of the page header which renders synchronously.
    const btn = await screen.findByTestId('tax-settings-button')
    expect(btn).toBeInTheDocument()
    expect(btn).toHaveTextContent(/Settings/i)
  })

  it('omits the Settings control for a non-org_admin role (Req 4.2)', async () => {
    auth.user = {
      id: 'u2',
      email: 'staff@test.com',
      name: 'Staff',
      role: 'staff',
      org_id: 'org-1',
    }
    renderPayRun()

    // Let the page settle (period probe resolves) before asserting absence.
    await waitFor(() => expect(mockListPayPeriods).toHaveBeenCalled())
    expect(screen.queryByTestId('tax-settings-button')).toBeNull()
  })
})

/* ════════════════════════════════════════════════════════════════════════
 * Req 9.4 — Inherited vs Override badges + reset re-renders as Inherited
 * ════════════════════════════════════════════════════════════════════════ */

/** All nine overridable top-level Tax_Field keys (tax_year_label excluded). */
const OVERRIDE_KEYS = [
  'paye_brackets',
  'secondary_rates',
  'acc_levy_rate',
  'acc_max_liable_earnings',
  'student_loan_rate',
  'student_loan_threshold',
  'ietc',
  'default_kiwisaver_employee_rate',
  'default_kiwisaver_employer_rate',
] as const

/** Build a per-field status map; pass the keys that are org overrides. */
function fieldStatus(overrideKeys: string[]): OrgTaxSettingsView['field_status'] {
  const status: OrgTaxSettingsView['field_status'] = {}
  for (const key of OVERRIDE_KEYS) {
    const override = overrideKeys.includes(key)
    status[key] = {
      override,
      inherited: !override,
      source: override ? 'override' : 'platform',
    }
  }
  return status
}

/**
 * A full OrgTaxSettingsView with the 2024/25 effective values. `overrideKeys`
 * controls which fields are marked as org overrides in `field_status`.
 */
function orgView(overrideKeys: string[]): OrgTaxSettingsView {
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
    field_status: fieldStatus(overrideKeys),
  }
}

function renderSettings() {
  return render(
    <MemoryRouter initialEntries={['/payroll/tax-settings']}>
      <PayrollTaxSettings />
    </MemoryRouter>,
  )
}

/** The `<section>` whose heading matches the given exact title. */
function sectionByTitle(title: string): HTMLElement {
  const heading = screen.getByText(title)
  const section = heading.closest('section')
  if (!section) throw new Error(`No <section> found for "${title}"`)
  return section as HTMLElement
}

describe('PayrollTaxSettings — Inherited vs Override badges (Req 9.4)', () => {
  beforeEach(() => {
    auth.user = {
      id: 'u1',
      email: 'admin@test.com',
      name: 'Admin',
      role: 'org_admin',
      org_id: 'org-1',
    }
  })

  it('shows an Override badge for an overridden field and Inherited for the rest', async () => {
    // Only the ACC levy rate is an org override; everything else inherits.
    mockGetOrg.mockResolvedValue(orgView(['acc_levy_rate']))
    renderSettings()

    // Wait for the async load to replace the loading spinner with the form.
    await screen.findByText('ACC levy rate')

    // The overridden ACC levy rate section carries the Override badge.
    const accSection = sectionByTitle('ACC levy rate')
    expect(within(accSection).getByText('Override')).toBeInTheDocument()

    // An inherited field (student loan rate) carries the Inherited badge.
    const slSection = sectionByTitle('Student loan rate')
    expect(within(slSection).getByText('Inherited')).toBeInTheDocument()

    // Exactly one field is overridden → exactly one Override badge overall.
    expect(screen.getAllByText('Override')).toHaveLength(1)
    // The remaining fields (incl. the platform-only tax-year row) are Inherited.
    expect(screen.getAllByText('Inherited').length).toBeGreaterThan(1)
  })

  it('re-renders a reset field as Inherited after resetting its override (Req 9.4)', async () => {
    const user = userEvent.setup()
    // Start with ACC levy rate overridden.
    mockGetOrg.mockResolvedValue(orgView(['acc_levy_rate']))
    // After the reset, the server returns a view where the field now inherits.
    mockResetField.mockResolvedValue(orgView([]))

    renderSettings()

    // Wait for the async load to replace the loading spinner with the form.
    await screen.findByText('ACC levy rate')

    const accSection = sectionByTitle('ACC levy rate')
    expect(within(accSection).getByText('Override')).toBeInTheDocument()

    // The "Reset to default" control is enabled only while the field is an override.
    const resetBtn = within(accSection).getByRole('button', {
      name: /Reset to default/i,
    })
    expect(resetBtn).toBeEnabled()
    await user.click(resetBtn)

    // The reset DELETE was issued for the ACC levy rate field.
    await waitFor(() =>
      expect(mockResetField).toHaveBeenCalledWith('acc_levy_rate'),
    )

    // The field re-renders as Inherited (badge flips) and no Override badge remains.
    await waitFor(() => {
      const refreshed = sectionByTitle('ACC levy rate')
      expect(within(refreshed).getByText('Inherited')).toBeInTheDocument()
    })
    expect(screen.queryByText('Override')).toBeNull()
  })
})
