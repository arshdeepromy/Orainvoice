import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import StaffList from './StaffList'

/**
 * StaffList — per-staff pay-cycle selector tests (Task 12.3, Add modal).
 *
 * Covers the Add-staff modal selector behaviour:
 *  - REQ 1.5 / 1.6: when the org has NO active cycles the selector is hidden
 *    and the "configure under Timesheets → Settings" hint is shown.
 *  - REQ 1.1 / 1.4: when active cycles exist the selector is populated with
 *    them plus a "Use organisation default" option (naming the default cycle).
 *  - REQ 2.1: submitting with a chosen cycle includes `pay_cycle_id` (its uuid)
 *    in the POST /staff payload.
 *  - REQ 2.3: submitting with "Use organisation default" sends `pay_cycle_id`
 *    as null so no staff-level assignment is created.
 *
 * `@/api/client` is mocked so `GET /api/v2/pay-cycles/` resolves a configurable
 * `{ items, total }` page and `POST /staff` records its payload; the
 * BranchContext / ModuleContext hooks and `@/api/staff` are stubbed so the page
 * mounts without the real provider tree.
 */

// --- hoisted mutable fixtures + spies -------------------------------------
const h = vi.hoisted(() => ({
  staff: [] as Array<Record<string, unknown>>,
  total: 0,
  payCycles: [] as Array<Record<string, unknown>>,
  navigate: vi.fn(),
  postCalls: [] as Array<{ url: string; body: any }>,
}))

vi.mock('react-router-dom', async () => {
  const actual =
    await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => h.navigate }
})

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({ branches: [] }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => false }),
}))

vi.mock('@/api/staff', () => ({
  getPendingLeaveCount: vi.fn(async () => 0),
  getStaffListKpis: vi.fn(async () => ({
    total_staff: h.total,
    employee_count: 0,
    with_login_count: 0,
    avg_hourly_rate: null,
  })),
}))

vi.mock('@/api/client', () => {
  const get = vi.fn(
    async (url: string, _config?: { params?: Record<string, unknown> }) => {
      if (url === '/staff') {
        return { data: { staff: h.staff, total: h.total } }
      }
      // Active pay cycles — always wrapped in { items, total } (safe shape).
      if (url === '/api/v2/pay-cycles/') {
        return { data: { items: h.payCycles, total: h.payCycles.length } }
      }
      return { data: {} }
    },
  )
  const post = vi.fn(async (url: string, body?: any) => {
    h.postCalls.push({ url, body })
    return { data: {} }
  })
  return {
    default: {
      get,
      post,
      put: vi.fn(async () => ({ data: {} })),
      delete: vi.fn(async () => ({ data: {} })),
    },
  }
})

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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/staff']}>
      <StaffList />
    </MemoryRouter>,
  )
}

/** Open the Add-staff modal and wait for it to render. */
async function openAddModal(user: ReturnType<typeof userEvent.setup>) {
  // Header action + (after opening) modal submit share the "Add Staff" name;
  // before opening there is only the header trigger.
  await user.click(screen.getByRole('button', { name: 'Add Staff' }))
  await screen.findByText('Add Staff Member')
}

/** The pay-cycle <select> is identified by its unique default option. */
function payCycleSelect(): HTMLSelectElement {
  const opt = screen.getByRole('option', {
    name: /Use organisation default/i,
  })
  return opt.closest('select') as HTMLSelectElement
}

function firstNameInput(): HTMLInputElement {
  const label = screen.getByText('First Name *')
  return label.parentElement!.querySelector('input') as HTMLInputElement
}

/** The most recent POST /staff payload. */
function lastCreatePayload() {
  const calls = h.postCalls.filter((c) => c.url === '/staff')
  return calls[calls.length - 1]?.body
}

beforeEach(() => {
  h.staff = []
  h.total = 0
  h.payCycles = []
  h.navigate = vi.fn()
  h.postCalls = []
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('StaffList Add modal — pay-cycle selector', () => {
  it('hides the selector and shows the configure hint when there are no active cycles (REQ 1.5, 1.6)', async () => {
    const user = userEvent.setup()
    h.payCycles = []
    renderPage()
    await openAddModal(user)

    // Hint directing the user to Timesheets → Settings is shown.
    expect(
      screen.getByText(/No pay cycle configured/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Timesheets → Settings/i)).toBeInTheDocument()

    // The selector itself is absent: no "Pay Cycle" label, no default option.
    expect(screen.queryByText('Pay Cycle')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('option', { name: /Use organisation default/i }),
    ).not.toBeInTheDocument()
  })

  it('populates the selector with active cycles and a default option when cycles exist (REQ 1.1, 1.4)', async () => {
    const user = userEvent.setup()
    h.payCycles = [
      makeCycle({ id: 'pc-weekly', name: 'Weekly', is_default: true }),
      makeCycle({ id: 'pc-fortnightly', name: 'Fortnightly' }),
    ]
    renderPage()
    await openAddModal(user)

    // Selector is shown (label present) and the hint is not.
    expect(screen.getByText('Pay Cycle')).toBeInTheDocument()
    expect(
      screen.queryByText(/No pay cycle configured/i),
    ).not.toBeInTheDocument()

    // Default option names the org default cycle (REQ 1.4).
    expect(
      screen.getByRole('option', {
        name: /Use organisation default \(Weekly\)/i,
      }),
    ).toBeInTheDocument()
    // Each active cycle is an option (REQ 1.1).
    expect(screen.getByRole('option', { name: 'Weekly' })).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: 'Fortnightly' }),
    ).toBeInTheDocument()
  })

  it('includes the chosen pay_cycle_id in the create payload (REQ 2.1)', async () => {
    const user = userEvent.setup()
    h.payCycles = [
      makeCycle({ id: 'pc-weekly', name: 'Weekly', is_default: true }),
      makeCycle({ id: 'pc-fortnightly', name: 'Fortnightly' }),
    ]
    renderPage()
    await openAddModal(user)

    await user.type(firstNameInput(), 'Jordan')
    await user.selectOptions(payCycleSelect(), 'pc-fortnightly')

    const addButtons = screen.getAllByRole('button', { name: 'Add Staff' })
    await user.click(addButtons[addButtons.length - 1])

    await waitFor(() => expect(lastCreatePayload()).toBeTruthy())
    expect(lastCreatePayload().pay_cycle_id).toBe('pc-fortnightly')
  })

  it('sends pay_cycle_id null when "Use organisation default" is left selected (REQ 2.3)', async () => {
    const user = userEvent.setup()
    h.payCycles = [
      makeCycle({ id: 'pc-weekly', name: 'Weekly', is_default: true }),
    ]
    renderPage()
    await openAddModal(user)

    await user.type(firstNameInput(), 'Casey')
    // Leave the default option selected (no explicit choice).
    const addButtons = screen.getAllByRole('button', { name: 'Add Staff' })
    await user.click(addButtons[addButtons.length - 1])

    await waitFor(() => expect(lastCreatePayload()).toBeTruthy())
    expect(lastCreatePayload().pay_cycle_id).toBeNull()
  })
})
