import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import StaffList from './StaffList'
import apiClient from '@/api/client'

/**
 * StaffList preservation component tests (Task 10.2).
 *
 * These tests guard Requirement 6 — that the redesign preserves all existing
 * Staff list capabilities. Each test asserts that a pre-existing capability
 * still renders and operates after the restyle:
 *   - add/edit modal incl. the per-day WorkSchedule editor (R6.1)
 *   - the "also create as user" invite flow with role + branch selects (R6.2)
 *   - deactivate / activate row actions (R6.3)
 *   - permanent-delete with the "also delete user account" option (R6.4)
 *   - inline duplicate detection in the add modal (R6.5)
 *   - pagination of the staff table (R6.6)
 *
 * Kept SEPARATE from `StaffList.test.tsx` (Task 9.9) so the page-level tests
 * are untouched, but the mock scaffolding mirrors that file exactly:
 * `@/api/client` is mocked so `GET /staff` resolves a deterministic page (and
 * `GET /staff/check-duplicate` / `GET /org/users` resolve fixtures);
 * `@/api/staff`, BranchContext and ModuleContext hooks are mocked so the page
 * mounts without the real provider tree; `useNavigate` is a spy.
 */

// --- hoisted mutable fixtures + spies -------------------------------------
const h = vi.hoisted(() => ({
  staff: [] as Array<Record<string, unknown>>,
  total: 0,
  pendingLeaveCount: 0,
  branches: [] as Array<Record<string, unknown>>,
  duplicateResponse: { duplicate: false } as Record<string, unknown>,
  navigate: vi.fn(),
  getCalls: [] as Array<{ url: string; params?: Record<string, unknown> }>,
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => h.navigate }
})

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({ branches: h.branches }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => false }),
}))

vi.mock('@/api/staff', () => ({
  getPendingLeaveCount: vi.fn(async () => h.pendingLeaveCount),
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
    if (url === '/staff/check-duplicate') {
      return { data: h.duplicateResponse }
    }
    if (url === '/org/users') {
      return { data: { users: [] } }
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
  h.branches = []
  h.duplicateResponse = { duplicate: false }
  h.navigate = vi.fn()
  h.getCalls = []
})

afterEach(() => {
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('StaffList preservation (Requirement 6)', () => {
  // --- R6.1: add/edit modal incl. per-day WorkSchedule editor --------------
  it('opens the Add modal with the WorkSchedule editor (R6.1)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    await user.click(screen.getByRole('button', { name: /Add Staff/ }))

    // Add modal heading + required first-name field.
    expect(await screen.findByText('Add Staff Member')).toBeInTheDocument()
    expect(screen.getByText('First Name *')).toBeInTheDocument()
    // The WorkSchedule editor renders its per-day toggles (Mon…Sun).
    expect(screen.getByRole('button', { name: 'Mon' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sun' })).toBeInTheDocument()
  })

  it('opens the Edit modal pre-filled with the member values (R6.1)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    await user.click(screen.getByRole('button', { name: 'Edit' }))

    expect(await screen.findByText('Edit Staff Member')).toBeInTheDocument()
    // First name input pre-filled from the row.
    expect(screen.getByDisplayValue('Jordan')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Blake')).toBeInTheDocument()
    // WorkSchedule editor still present in the edit modal.
    expect(screen.getByRole('button', { name: 'Mon' })).toBeInTheDocument()
  })

  // --- R6.2: "also create as user" invite flow ----------------------------
  it('reveals the user-role and branch selects when "also create as user" is checked (R6.2)', async () => {
    const user = userEvent.setup()
    h.branches = [{ id: 'b-1', name: 'Main Branch', is_active: true }]
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    await user.click(screen.getByRole('button', { name: /Add Staff/ }))
    await screen.findByText('Add Staff Member')

    // Invite selects are hidden until the option is checked.
    expect(screen.queryByText('User Role')).not.toBeInTheDocument()
    expect(screen.queryByText('Assign to Branch')).not.toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: /Also create as a user/ }))

    expect(await screen.findByText('User Role')).toBeInTheDocument()
    expect(screen.getByText('Assign to Branch')).toBeInTheDocument()
    // The mocked active branch renders as a selectable option.
    expect(screen.getByRole('option', { name: 'Main Branch' })).toBeInTheDocument()
  })

  // --- R6.3: deactivate / activate ----------------------------------------
  it('deactivates an active member, calling DELETE /staff/{id} (R6.3)', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    // An active row exposes the Deactivate action.
    await user.click(screen.getByRole('button', { name: 'Deactivate' }))

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith('/staff/s-1', { baseURL: '/api/v2' }),
    )
  })

  it('activates an inactive member, calling POST /staff/{id}/activate (R6.3)', async () => {
    const user = userEvent.setup()
    h.staff = [makeStaff({ is_active: false })]
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    // An inactive row exposes the Activate action instead of Deactivate.
    expect(screen.queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Activate' }))

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith('/staff/s-1/activate', {}, { baseURL: '/api/v2' }),
    )
  })

  // --- R6.4: permanent-delete + delete user -------------------------------
  it('opens the permanent-delete confirmation with the delete-user option (R6.4)', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    await user.click(screen.getByRole('button', { name: 'Delete' }))

    // Confirmation modal renders the permanent-delete warning.
    expect(await screen.findByText('Delete Staff Member')).toBeInTheDocument()
    expect(screen.getByText(/permanently delete/i)).toBeInTheDocument()
    // The member has an email, so the "also delete user account" option shows.
    expect(screen.getByText('Also delete user account')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Delete permanently/ }))

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith('/staff/s-1/permanent', { baseURL: '/api/v2' }),
    )
  })

  // --- R6.5: inline duplicate detection -----------------------------------
  it('runs the inline duplicate check and surfaces the warning (R6.5)', async () => {
    const user = userEvent.setup()
    h.duplicateResponse = {
      duplicate: true,
      message: 'A staff member with this email already exists',
    }
    const { container } = renderPage()
    await screen.findByRole('button', { name: /Jordan Blake/ })

    await user.click(screen.getByRole('button', { name: /Add Staff/ }))
    await screen.findByText('Add Staff Member')

    const emailInput = container.querySelector('input[type="email"]') as HTMLInputElement
    expect(emailInput).not.toBeNull()
    await user.type(emailInput, 'dupe@example.com')

    // The debounced check hits GET /staff/check-duplicate…
    await waitFor(
      () =>
        expect(
          h.getCalls.some(
            (c) => c.url === '/staff/check-duplicate' && c.params?.field === 'email',
          ),
        ).toBe(true),
      { timeout: 2000 },
    )
    // …and the duplicate message is rendered inline.
    expect(
      await screen.findByText('A staff member with this email already exists'),
    ).toBeInTheDocument()
  })

  // --- R6.6: pagination ----------------------------------------------------
  it('renders the pagination footer and advances to page 2 (R6.6)', async () => {
    const user = userEvent.setup()
    // total (45) exceeds the page size (20) → 3 pages → footer renders.
    h.total = 45
    h.staff = Array.from({ length: 20 }, (_, i) =>
      makeStaff({ id: `s-${i}`, first_name: `Member${i}`, last_name: 'Test', employee_id: `EMP-${i}` }),
    )
    renderPage()
    await screen.findByRole('button', { name: /Member0 Test/ })

    const prevBtn = screen.getByRole('button', { name: 'Previous' })
    const nextBtn = screen.getByRole('button', { name: 'Next' })
    expect(prevBtn).toBeDisabled()
    expect(nextBtn).toBeEnabled()

    await user.click(nextBtn)

    await waitFor(() => expect(lastListParams()?.page).toBe('2'))
  })
})
