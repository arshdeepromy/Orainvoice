import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach, vi } from 'vitest'

/**
 * Frontend tests for the cycle-first pay-period filter in TimesheetsTab and
 * PayRunsTab (replaces the old single cross-cycle <select> with optgroups).
 *
 * The control is now cycle-first:
 *
 *   - One clickable cycle "box"/chip per active cycle (e.g. a Weekly and a
 *     Fortnightly control are both present).
 *   - Selecting a cycle scopes the period stepper/dropdown to ONLY that cycle's
 *     periods, so two periods that share a date range across cycles are never
 *     shown together — they are separated by which cycle is selected.
 *   - The selected period id drives the materialise call (TimesheetsTab) and
 *     the /api/v2/pay-run/generate/ call (PayRunsTab).
 *   - All API responses are consumed safely ({ items, total } shapes); missing
 *     arrays never throw.
 *
 * Both components import the default `@/api/client` (and PayRunsTab reaches the
 * same client indirectly via `@/api/payslips`), so a single hoisted mock of the
 * client drives every endpoint the tabs touch.
 */

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: vi.fn(async () => ({ data: {} })),
    patch: vi.fn(async () => ({ data: {} })),
    delete: vi.fn(async () => ({ data: {} })),
  },
}))

import PayRunsTab from './PayRunsTab'

// ---------------------------------------------------------------------------
// Fixtures — two active cycles, plus two periods that share an identical date
// range across the two cycles so the only thing distinguishing them is which
// cycle is selected.
// ---------------------------------------------------------------------------

const CYCLES = [
  {
    id: 'cyc-weekly',
    name: 'Weekly',
    frequency: 'weekly',
    anchor_date: '2026-01-05',
    pay_date_offset_days: 3,
    is_default: true,
    active: true,
  },
  {
    id: 'cyc-fortnightly',
    name: 'Fortnightly',
    frequency: 'fortnightly',
    anchor_date: '2026-01-05',
    pay_date_offset_days: 3,
    is_default: false,
    active: true,
  },
]

// Same start AND end date across the two cycles: the rendered date label is
// identical, so only the selected cycle tells them apart.
const PERIODS = [
  {
    id: 'pp-weekly',
    start_date: '2026-06-08',
    end_date: '2026-06-14',
    pay_date: '2026-06-17',
    status: 'open',
    pay_cycle_id: 'cyc-weekly',
    pay_cycle_name: 'Weekly',
  },
  {
    id: 'pp-fortnightly',
    start_date: '2026-06-08',
    end_date: '2026-06-14',
    pay_date: '2026-06-17',
    status: 'open',
    pay_cycle_id: 'cyc-fortnightly',
    pay_cycle_name: 'Fortnightly',
  },
]

const PERIOD_SUMMARY = {
  total_staff: 1,
  approved_count: 0,
  pending_count: 0,
  locked_count: 1,
}

/** Wire the client mock to deterministic, safely-shaped backend responses. */
function configureApi({
  cycles = CYCLES,
  periods = PERIODS,
}: { cycles?: unknown[]; periods?: unknown[] } = {}) {
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/api/v2/pay-cycles/') return { data: { items: cycles, total: cycles.length } }
    if (url === '/api/v2/pay-periods') return { data: { items: periods, total: periods.length } }
    if (url === '/api/v2/timesheets/') {
      return { data: { items: [], total: 0, period_summary: PERIOD_SUMMARY } }
    }
    if (url === '/api/v2/pay-run/adjustments/') return { data: { items: [], total: 0 } }
    if (url.endsWith('/payslips')) return { data: { items: [], total: 0 } }
    return { data: {} }
  })
  mockPost.mockImplementation(async (url: string) => {
    if (url.includes('generate-periods')) return { data: { created: [], count: 0 } }
    if (url === '/api/v2/timesheets/materialise/') return { data: { created_count: 2 } }
    if (url === '/api/v2/pay-run/generate/') {
      return { data: { payslips_generated: 1, total_timesheets: 1, adjustments_included: 0, errors: [] } }
    }
    return { data: {} }
  })
}

/** The period dropdown — identified by its aria-label. */
function periodSelect(): HTMLSelectElement {
  return screen.getByRole('combobox', { name: /pay period/i }) as HTMLSelectElement
}

/** Option values currently present in the period dropdown. */
function periodOptionValues(): string[] {
  return Array.from(periodSelect().querySelectorAll('option')).map((o) => (o as HTMLOptionElement).value)
}

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  configureApi()
})

// ===========================================================================
// PayRunsTab
// ===========================================================================

function renderPayRuns() {
  return render(
    <MemoryRouter initialEntries={['/payroll']}>
      <PayRunsTab />
    </MemoryRouter>,
  )
}

describe('PayRunsTab — cycle-first period filter', () => {
  it('renders one cycle box per active cycle', async () => {
    renderPayRuns()

    const cycleGroup = await screen.findByRole('group', { name: /pay cycle/i })
    expect(within(cycleGroup).getByRole('button', { name: /weekly/i })).toBeTruthy()
    expect(within(cycleGroup).getByRole('button', { name: /fortnightly/i })).toBeTruthy()
  })

  it('scopes the period dropdown to the selected cycle (same-range periods stay separated)', async () => {
    const user = userEvent.setup()
    renderPayRuns()

    await waitFor(() => expect(periodOptionValues()).toEqual(['pp-weekly']))
    expect(periodSelect().value).toBe('pp-weekly')

    const cycleGroup = screen.getByRole('group', { name: /pay cycle/i })
    await user.click(within(cycleGroup).getByRole('button', { name: /fortnightly/i }))

    await waitFor(() => expect(periodOptionValues()).toEqual(['pp-fortnightly']))
    expect(periodSelect().value).toBe('pp-fortnightly')
  })

  it('drives the pay-run call with the selected period id', async () => {
    const user = userEvent.setup()
    renderPayRuns()

    const cycleGroup = await screen.findByRole('group', { name: /pay cycle/i })
    await user.click(within(cycleGroup).getByRole('button', { name: /fortnightly/i }))
    await waitFor(() => expect(periodSelect().value).toBe('pp-fortnightly'))

    const runButton = screen.getByRole('button', { name: /generate pay run/i })
    await waitFor(() => expect(runButton).not.toBeDisabled())
    await user.click(runButton)

    await waitFor(() => {
      const call = mockPost.mock.calls.find((c) => c[0] === '/api/v2/pay-run/generate/')
      expect(call).toBeTruthy()
      expect(call?.[2]?.params?.pay_period_id).toBe('pp-fortnightly')
    })
  })

  it('consumes responses safely when arrays are missing (no crash)', async () => {
    mockGet.mockImplementation(async () => ({ data: {} }))

    renderPayRuns()

    // No cycles → the "configure a pay cycle" guidance renders, no throw.
    await waitFor(() => {
      expect(screen.getByText(/no pay cycle configured yet/i)).toBeInTheDocument()
    })
  })
})
