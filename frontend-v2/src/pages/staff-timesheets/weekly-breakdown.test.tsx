import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, beforeEach, vi } from 'vitest'

/**
 * Frontend tests for the "weekly lens" review aid in TimesheetsTab.
 *
 * The weekly lens is a READ-ONLY toggle that only appears for a selected
 * pay period spanning more than one ISO week (fortnightly / monthly):
 *
 *   - Multi-week period → a "Period total | Weekly" segmented toggle appears.
 *     Switching to Weekly calls GET /api/v2/timesheets/weekly-breakdown with the
 *     selected pay_period_id and renders one section per week with its total.
 *   - Single-week period → no toggle is rendered.
 *   - A `{}` / empty weekly-breakdown response renders without crashing.
 *
 * TimesheetsTab imports the default `@/api/client`, so a single hoisted mock of
 * the client drives every endpoint the tab touches.
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

import TimesheetsTab from './TimesheetsTab'

// ---------------------------------------------------------------------------
// Fixtures — one Weekly cycle with a single-week period and one Fortnightly
// cycle with a two-ISO-week period.
// ---------------------------------------------------------------------------

const CYCLES = [
  {
    id: 'cyc-weekly',
    name: 'Weekly',
    frequency: 'weekly',
    is_default: true,
    active: true,
  },
  {
    id: 'cyc-fortnightly',
    name: 'Fortnightly',
    frequency: 'fortnightly',
    is_default: false,
    active: true,
  },
]

const PERIODS = [
  {
    id: 'pp-weekly',
    start_date: '2026-06-08', // Mon
    end_date: '2026-06-14', // Sun — same ISO week
    pay_date: '2026-06-17',
    status: 'open',
    pay_cycle_id: 'cyc-weekly',
    pay_cycle_name: 'Weekly',
  },
  {
    id: 'pp-fortnightly',
    start_date: '2026-06-01', // Mon (ISO week N)
    end_date: '2026-06-14', // Sun (ISO week N+1) — spans two ISO weeks
    pay_date: '2026-06-17',
    status: 'open',
    pay_cycle_id: 'cyc-fortnightly',
    pay_cycle_name: 'Fortnightly',
  },
]

const PERIOD_SUMMARY = {
  total_staff: 2,
  approved_count: 0,
  pending_count: 0,
  locked_count: 0,
  total_ordinary_hours: 0,
  total_overtime_hours: 0,
  total_public_holiday_hours: 0,
}

const WEEKLY_BREAKDOWN = {
  pay_period_id: 'pp-fortnightly',
  multi_week: true,
  weeks: [
    {
      week_index: 1,
      iso_week: 23,
      start_date: '2026-06-01',
      end_date: '2026-06-07',
      total_minutes: 780, // 13.00h
      staff: [{ staff_id: 's1', staff_name: 'Clocker One', minutes: 780 }],
    },
    {
      week_index: 2,
      iso_week: 24,
      start_date: '2026-06-08',
      end_date: '2026-06-14',
      total_minutes: 0,
      staff: [],
    },
  ],
}

function configureApi({
  cycles = CYCLES,
  periods = PERIODS,
  weekly = WEEKLY_BREAKDOWN as unknown,
}: { cycles?: unknown[]; periods?: unknown[]; weekly?: unknown } = {}) {
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/api/v2/pay-cycles/') return { data: { items: cycles, total: cycles.length } }
    if (url === '/api/v2/pay-periods') return { data: { items: periods, total: periods.length } }
    if (url === '/api/v2/timesheets/') {
      return { data: { items: [], total: 0, period_summary: PERIOD_SUMMARY } }
    }
    if (url === '/api/v2/timesheets/weekly-breakdown') return { data: weekly }
    return { data: {} }
  })
  mockPost.mockImplementation(async (url: string) => {
    if (url.includes('generate-periods')) return { data: { created: [], count: 0 } }
    if (url === '/api/v2/timesheets/materialise/') return { data: { created_count: 0 } }
    return { data: {} }
  })
}

/** The period dropdown — identified by its aria-label. */
function periodSelect(): HTMLSelectElement {
  return screen.getByRole('combobox', { name: /pay period/i }) as HTMLSelectElement
}

function viewToggleGroup(): HTMLElement | null {
  return screen.queryByRole('group', { name: /timesheet view/i })
}

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  configureApi()
})

describe('TimesheetsTab — weekly lens', () => {
  it('shows the Weekly toggle for a multi-week period and renders week sections', async () => {
    const user = userEvent.setup()
    render(<TimesheetsTab />)

    // Switch to the Fortnightly cycle (its period spans two ISO weeks).
    const cycleGroup = await screen.findByRole('group', { name: /pay cycle/i })
    await user.click(within(cycleGroup).getByRole('button', { name: /fortnightly/i }))
    await waitFor(() => expect(periodSelect().value).toBe('pp-fortnightly'))

    // The segmented toggle appears for multi-week periods.
    const toggle = await waitFor(() => {
      const g = viewToggleGroup()
      expect(g).not.toBeNull()
      return g as HTMLElement
    })

    // Switch to the Weekly lens.
    await user.click(within(toggle).getByRole('button', { name: /^weekly$/i }))

    // It calls the weekly-breakdown endpoint with the selected period id.
    await waitFor(() => {
      const call = mockGet.mock.calls.find((c) => c[0] === '/api/v2/timesheets/weekly-breakdown')
      expect(call).toBeTruthy()
      expect(call?.[1]?.params?.pay_period_id).toBe('pp-fortnightly')
    })

    // Two week sections render, with their totals.
    const sections = await screen.findAllByTestId('weekly-breakdown-week')
    expect(sections).toHaveLength(2)
    expect(screen.getByText(/week 1/i)).toBeInTheDocument()
    expect(screen.getByText(/week 2/i)).toBeInTheDocument()
    // Week 1 total 780 min == 13.00h; the staff row also shows 13.00h.
    expect(screen.getAllByText('13.00h').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/clocker one/i)).toBeInTheDocument()
  })

  it('does not show the Weekly toggle for a single-week period', async () => {
    render(<TimesheetsTab />)

    // Default cycle is the Weekly one whose period stays within a single ISO week.
    await waitFor(() => expect(periodSelect().value).toBe('pp-weekly'))

    // No weekly-lens toggle for single-week periods.
    expect(viewToggleGroup()).toBeNull()
  })

  it('renders without crashing when the weekly response is empty ({})', async () => {
    configureApi({ weekly: {} })
    const user = userEvent.setup()
    render(<TimesheetsTab />)

    const cycleGroup = await screen.findByRole('group', { name: /pay cycle/i })
    await user.click(within(cycleGroup).getByRole('button', { name: /fortnightly/i }))
    await waitFor(() => expect(periodSelect().value).toBe('pp-fortnightly'))

    const toggle = await waitFor(() => {
      const g = viewToggleGroup()
      expect(g).not.toBeNull()
      return g as HTMLElement
    })
    await user.click(within(toggle).getByRole('button', { name: /^weekly$/i }))

    // Empty response → safe empty state, no week sections, no throw.
    await waitFor(() => {
      expect(screen.getByText(/no weekly breakdown for this period/i)).toBeInTheDocument()
    })
    expect(screen.queryAllByTestId('weekly-breakdown-week')).toHaveLength(0)
  })
})
