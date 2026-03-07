import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — Staff Module
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import StaffList from '../pages/staff/StaffList'
import StaffDetail from '../pages/staff/StaffDetail'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockStaff = [
  {
    id: 'staff-1', org_id: 'org-1', name: 'Alice Smith',
    email: 'alice@example.com', phone: '021-555-0001',
    role_type: 'employee', hourly_rate: '50.00',
    is_active: true, created_at: '2024-06-15T10:00:00Z',
  },
  {
    id: 'staff-2', org_id: 'org-1', name: 'Bob Jones',
    email: 'bob@example.com', phone: null,
    role_type: 'contractor', hourly_rate: '75.00',
    is_active: false, created_at: '2024-06-16T10:00:00Z',
  },
]

const mockStaffDetail = {
  id: 'staff-1', org_id: 'org-1', user_id: null,
  name: 'Alice Smith', email: 'alice@example.com',
  phone: '021-555-0001', role_type: 'employee',
  hourly_rate: '50.00', overtime_rate: '75.00',
  is_active: true,
  availability_schedule: {
    monday: { start: '08:00', end: '16:00' },
    tuesday: { start: '08:00', end: '16:00' },
    wednesday: { start: '08:00', end: '16:00' },
  },
  skills: ['plumbing', 'welding'],
  location_assignments: [
    { id: 'la-1', location_id: 'loc-1', assigned_at: '2024-06-15T10:00:00Z' },
  ],
  created_at: '2024-06-15T10:00:00Z',
  updated_at: '2024-06-15T10:00:00Z',
}

/* ------------------------------------------------------------------ */
/*  StaffList tests                                                    */
/* ------------------------------------------------------------------ */

describe('StaffList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<StaffList />)
    expect(screen.getByRole('status', { name: 'Loading staff' })).toBeInTheDocument()
  })

  it('displays staff members in a table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { staff: mockStaff, total: 2, page: 1, page_size: 20 },
    })
    render(<StaffList />)
    const table = await screen.findByRole('grid', { name: 'Staff list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
    expect(screen.getByText('Alice Smith')).toBeInTheDocument()
    expect(screen.getByText('Bob Jones')).toBeInTheDocument()
  })

  it('renders role filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { staff: [], total: 0, page: 1, page_size: 20 },
    })
    render(<StaffList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Role')).toBeInTheDocument()
  })

  it('renders active/inactive filter', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { staff: [], total: 0, page: 1, page_size: 20 },
    })
    render(<StaffList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Status')).toBeInTheDocument()
  })

  it('shows empty state when no staff', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { staff: [], total: 0, page: 1, page_size: 20 },
    })
    render(<StaffList />)
    expect(await screen.findByText(/No staff members found/)).toBeInTheDocument()
  })

  it('filters by role when dropdown changes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { staff: mockStaff, total: 2, page: 1, page_size: 20 },
    })
    render(<StaffList />)
    await screen.findByRole('grid', { name: 'Staff list' })

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Role'), 'contractor')

    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
      const lastCall = calls[calls.length - 1][0] as string
      expect(lastCall).toContain('role_type=contractor')
    })
  })

  it('shows active/inactive status in table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { staff: mockStaff, total: 2, page: 1, page_size: 20 },
    })
    render(<StaffList />)
    const table = await screen.findByRole('grid', { name: 'Staff list' })
    expect(within(table).getByText('Active')).toBeInTheDocument()
    expect(within(table).getByText('Inactive')).toBeInTheDocument()
  })

  it('has add staff button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { staff: [], total: 0, page: 1, page_size: 20 },
    })
    render(<StaffList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: 'Add staff member' })).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  StaffDetail tests                                                  */
/* ------------------------------------------------------------------ */

describe('StaffDetail', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<StaffDetail staffId="staff-1" />)
    expect(screen.getByRole('status', { name: 'Loading staff member' })).toBeInTheDocument()
  })

  it('displays staff details and edit form', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStaffDetail })
    render(<StaffDetail staffId="staff-1" />)

    expect(await screen.findByText('Alice Smith')).toBeInTheDocument()
    expect(screen.getByTestId('staff-status')).toHaveTextContent('Active')
    expect(screen.getByRole('form', { name: 'Edit staff member' })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Alice Smith')
    expect(screen.getByLabelText('Email')).toHaveValue('alice@example.com')
    expect(screen.getByLabelText('Hourly Rate')).toHaveValue(50)
  })

  it('displays availability schedule editor', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStaffDetail })
    render(<StaffDetail staffId="staff-1" />)

    await screen.findByText('Alice Smith')
    const scheduleGrid = screen.getByRole('grid', { name: 'Availability schedule' })
    expect(scheduleGrid).toBeInTheDocument()

    // Monday, Tuesday, Wednesday should be enabled
    expect(screen.getByLabelText('Enable Mon')).toBeChecked()
    expect(screen.getByLabelText('Enable Tue')).toBeChecked()
    expect(screen.getByLabelText('Enable Wed')).toBeChecked()
    // Thursday should not be enabled
    expect(screen.getByLabelText('Enable Thu')).not.toBeChecked()
  })

  it('shows start/end times for enabled days', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStaffDetail })
    render(<StaffDetail staffId="staff-1" />)

    await screen.findByText('Alice Smith')
    expect(screen.getByLabelText('Mon start time')).toHaveValue('08:00')
    expect(screen.getByLabelText('Mon end time')).toHaveValue('16:00')
  })

  it('submits updated staff data', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStaffDetail })
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStaffDetail })

    render(<StaffDetail staffId="staff-1" />)
    await screen.findByText('Alice Smith')

    const user = userEvent.setup()
    const nameInput = screen.getByLabelText('Name')
    await user.clear(nameInput)
    await user.type(nameInput, 'Alice Updated')

    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    expect(apiClient.put).toHaveBeenCalledWith(
      '/api/v2/staff/staff-1',
      expect.objectContaining({ name: 'Alice Updated' }),
    )
  })

  it('displays skills field', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStaffDetail })
    render(<StaffDetail staffId="staff-1" />)

    await screen.findByText('Alice Smith')
    expect(screen.getByLabelText('Skills (comma-separated)')).toHaveValue('plumbing, welding')
  })

  it('shows role selector', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockStaffDetail })
    render(<StaffDetail staffId="staff-1" />)

    await screen.findByText('Alice Smith')
    expect(screen.getByLabelText('Role')).toHaveValue('employee')
  })
})
