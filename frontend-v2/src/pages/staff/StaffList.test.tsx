import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import StaffList from './StaffList'

/**
 * StaffList page-level component tests (Task 9.9).
 *
 * Covers the StaffList behaviours that span the page wiring:
 *  - name cell navigates to `/staff/{id}` (R4.3)
 *  - segmented filters forward `role_type` + `is_active` to the fetch and
 *    preserve client-side search (R2.3, R2.5)
 *  - Leave header action links to `/leave/approvals` and shows a pending
 *    badge (R5.1, R5.2)
 *  - Export produces a CSV reflecting the filtered/searched set (R5.3)
 *  - the Add Staff action is retained and opens the modal (R5.4)
 *
 * `@/api/client` is mocked so `GET /staff` resolves a deterministic page;
 * `@/api/staff` and the BranchContext/ModuleContext hooks are mocked so the
 * page mounts without the real provider tree. `useNavigate` is mocked with a
 * spy so navigation targets can be asserted directly.
 */

// --- hoisted mutable fixtures + spies -------------------------------------
const h = vi.hoisted(() => ({
  staff: [] as Array<Record<string, unknown>>,
  total: 0,
  pendingLeaveCount: 0,
  navigate: vi.fn(),
  getCalls: [] as Array<{ url: string; params?: Record<string, unknown> }>,
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => h.navigate }
})

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({ branches: [] }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => false }),
}))

vi.mock('@/api/staff', () => ({
  getPendingLeaveCount: vi.fn(async () => h.pendingLeaveCount),
  // StaffKpiStrip (a child of StaffList) calls this on mount.
  getStaffListKpis: vi.fn(async () => ({
    total_staff: h.total,
    employee_count: 0,
    with_login_count: 0,
    avg_hourly_rate: null,
  })),
}))

vi.mock('@/api/client', () => {
  const get = vi.fn(async (url: string, config?: { params?: Record<string, unknown> }) => {
    h.getCalls.push({ url, params: config?.params })
    if (url === '/staff') {
      return { data: { staff: h.staff, total: h.total } }
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

function makeStaff(overrides: Record<string, unknown> = {}) {
  return {
    id: 's-1',
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
    hourly_rate: '30',
    overtime_rate: null,
    skills: [],
    availability_schedule: {},
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
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

/** The params passed to the most recent `GET /staff` list fetch (page fetch). */
function lastListParams() {
  const listCalls = h.getCalls.filter(
    (c) => c.url === '/staff' && c.params?.page !== undefined,
  )
  return listCalls[listCalls.length - 1]?.params
}

beforeEach(() => {
  h.staff = [makeStaff()]
  h.total = 1
  h.pendingLeaveCount = 0
  h.navigate = vi.fn()
  h.getCalls = []
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('StaffList', () => {
  it('navigates to /staff/{id} when the name cell is clicked (R4.3)', async () => {
    const user = userEvent.setup()
    renderPage()
    const nameBtn = await screen.findByRole('button', { name: /Jordan Blake/ })
    await user.click(nameBtn)
    expect(h.navigate).toHaveBeenCalledWith('/staff/s-1')
  })

  it('renders role and status segmented filter options', async () => {
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    expect(screen.getByRole('button', { name: 'All roles' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Employees' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Contractors' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Active' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inactive' })).toBeInTheDocument()
  })

  it('forwards role_type when the Employees filter is selected (R2.3)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    await user.click(screen.getByRole('button', { name: 'Employees' }))
    await waitFor(() => expect(lastListParams()?.role_type).toBe('employee'))
  })

  it('forwards is_active when the Active filter is selected (R2.3)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    await user.click(screen.getByRole('button', { name: 'Active' }))
    await waitFor(() => expect(lastListParams()?.is_active).toBe('true'))
  })

  it('preserves client-side search alongside the filters (R2.5)', async () => {
    const user = userEvent.setup()
    h.staff = [
      makeStaff({ id: 's-1', first_name: 'Jordan', last_name: 'Blake' }),
      makeStaff({ id: 's-2', first_name: 'Casey', last_name: 'Moore', email: 'casey@example.com', employee_id: 'EMP-002' }),
    ]
    h.total = 2
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    expect(screen.getByRole('button', { name: /Casey Moore/ })).toBeInTheDocument()

    await user.type(screen.getByLabelText('Search staff'), 'casey')

    // Search filters the rendered rows client-side.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Jordan Blake/ })).not.toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /Casey Moore/ })).toBeInTheDocument()
  })

  it('shows the Leave action and navigates to /leave/approvals (R5.1)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    const leaveBtn = screen.getByRole('button', { name: /^Leave/ })
    await user.click(leaveBtn)
    expect(h.navigate).toHaveBeenCalledWith('/leave/approvals')
  })

  it('shows the pending leave badge when there are pending requests (R5.2)', async () => {
    h.pendingLeaveCount = 4
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    expect(await screen.findByLabelText('4 pending leave requests')).toBeInTheDocument()
  })

  it('hides the pending leave badge when the count is zero (R5.2)', async () => {
    h.pendingLeaveCount = 0
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    expect(screen.queryByLabelText(/pending leave requests/)).not.toBeInTheDocument()
  })

  it('exports a CSV reflecting the filtered/searched set (R5.3)', async () => {
    const user = userEvent.setup()
    h.staff = [
      makeStaff({ id: 's-1', first_name: 'Jordan', last_name: 'Blake', employee_id: 'EMP-001' }),
      makeStaff({ id: 's-2', first_name: 'Casey', last_name: 'Moore', email: 'casey@example.com', employee_id: 'EMP-002' }),
    ]
    h.total = 2

    // Capture the Blob handed to URL.createObjectURL so we can read its text.
    let captured: Blob | null = null
    const createObjectURL = vi.fn((blob: Blob) => {
      captured = blob
      return 'blob:mock'
    })
    const revokeObjectURL = vi.fn()
    // jsdom lacks these — define them on URL.
    ;(URL as unknown as { createObjectURL: typeof createObjectURL }).createObjectURL = createObjectURL
    ;(URL as unknown as { revokeObjectURL: typeof revokeObjectURL }).revokeObjectURL = revokeObjectURL
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    // Narrow to a single staff member via search, then export.
    await user.type(screen.getByLabelText('Search staff'), 'casey')
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Jordan Blake/ })).not.toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: /Export/ }))

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(captured).not.toBeNull()

    const text = await (captured as unknown as Blob).text()
    // Header row present.
    expect(text).toContain('Employee ID')
    // Filtered row present, excluded row absent (reflects the search filter).
    expect(text).toContain('EMP-002')
    expect(text).not.toContain('EMP-001')

    clickSpy.mockRestore()
  })

  it('retains the Add Staff action and opens the modal (R5.4)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })
    const addBtn = screen.getByRole('button', { name: /Add Staff/ })
    await user.click(addBtn)
    // The add modal renders its heading.
    expect(await screen.findByText('Add Staff Member')).toBeInTheDocument()
    // The modal includes the required first-name field.
    expect(screen.getByText('First Name *')).toBeInTheDocument()
  })
})
