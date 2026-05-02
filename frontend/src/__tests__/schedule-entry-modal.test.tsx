import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 36.1, 36.2, 36.3, 36.4, 36.5, 36.6
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  }
})

import apiClient from '@/api/client'
import ScheduleEntryModal from '../pages/schedule/ScheduleEntryModal'

const mockStaff = [
  { id: 'staff-1', name: 'Alice Smith', position: 'Mechanic' },
  { id: 'staff-2', name: 'Bob Jones', position: null },
]

const mockEntry = {
  id: 'entry-1',
  staff_id: 'staff-1',
  job_id: null,
  booking_id: null,
  title: 'Oil change',
  description: 'Full synthetic oil change',
  start_time: '2025-06-15T09:00:00Z',
  end_time: '2025-06-15T10:00:00Z',
  entry_type: 'job',
  status: 'scheduled',
  recurrence_group_id: null,
}

describe('ScheduleEntryModal', () => {
  const onClose = vi.fn()
  const onSave = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/api/v2/schedule/templates') {
        return Promise.resolve({ data: { templates: [], total: 0 } })
      }
      return Promise.resolve({ data: { staff: mockStaff } })
    })
  })

  it('renders create mode with all required fields', async () => {
    render(
      <ScheduleEntryModal open={true} onClose={onClose} onSave={onSave} />,
    )

    // Wait for staff to load
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/api/v2/staff',
        expect.objectContaining({ params: { is_active: true, page_size: 100 } }),
      )
    })

    // Verify all form fields are present (Req 36.2)
    expect(screen.getByLabelText('Staff Member')).toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toBeInTheDocument()
    expect(screen.getByLabelText('Entry Type')).toBeInTheDocument()
    expect(screen.getByLabelText('Start Time')).toBeInTheDocument()
    expect(screen.getByLabelText('End Time')).toBeInTheDocument()
    expect(screen.getByLabelText('Notes')).toBeInTheDocument()

    // Verify modal title for create mode
    expect(screen.getByText('New Schedule Entry')).toBeInTheDocument()

    // Verify Create button
    expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument()
  })

  it('renders entry type dropdown with all options (Req 36.2)', async () => {
    render(
      <ScheduleEntryModal open={true} onClose={onClose} onSave={onSave} />,
    )

    const typeSelect = screen.getByLabelText('Entry Type')
    const options = Array.from((typeSelect as HTMLSelectElement).options).map(
      (o) => o.value,
    )
    expect(options).toEqual(['job', 'booking', 'break', 'leave', 'other'])
  })

  it('populates staff dropdown from API', async () => {
    render(
      <ScheduleEntryModal open={true} onClose={onClose} onSave={onSave} />,
    )

    await waitFor(() => {
      const staffSelect = screen.getByLabelText('Staff Member') as HTMLSelectElement
      const options = Array.from(staffSelect.options).map((o) => o.textContent)
      expect(options).toContain('Alice Smith — Mechanic')
      expect(options).toContain('Bob Jones')
    })
  })

  it('renders edit mode with pre-populated fields (Req 36.4)', async () => {
    render(
      <ScheduleEntryModal
        open={true}
        onClose={onClose}
        onSave={onSave}
        entry={mockEntry}
      />,
    )

    // Verify modal title for edit mode
    expect(screen.getByText('Edit Schedule Entry')).toBeInTheDocument()

    // Verify Update button
    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument()

    // Verify pre-populated fields
    await waitFor(() => {
      expect(screen.getByLabelText('Title')).toHaveValue('Oil change')
      expect(screen.getByLabelText('Notes')).toHaveValue('Full synthetic oil change')
      expect(screen.getByLabelText('Entry Type')).toHaveValue('job')
    })
  })

  it('validates required fields before submit', async () => {
    render(
      <ScheduleEntryModal open={true} onClose={onClose} onSave={onSave} />,
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Create' }))

    // Should show validation errors for start and end time
    expect(screen.getByText('Start time is required')).toBeInTheDocument()
    expect(screen.getByText('End time is required')).toBeInTheDocument()

    // Should NOT have called the API
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('calls POST /api/v2/schedule on create submit (Req 36.3)', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'new-entry-1' },
    })
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/api/v2/schedule/templates') {
        return Promise.resolve({ data: { templates: [], total: 0 } })
      }
      if (url.includes('/conflicts')) {
        return Promise.resolve({ data: { has_conflicts: false, conflicts: [] } })
      }
      return Promise.resolve({ data: { staff: mockStaff } })
    })

    render(
      <ScheduleEntryModal open={true} onClose={onClose} onSave={onSave} />,
    )

    const user = userEvent.setup()

    // Fill in required fields
    await user.type(screen.getByLabelText('Title'), 'Brake inspection')

    const startInput = screen.getByLabelText('Start Time')
    await user.clear(startInput)
    await user.type(startInput, '2025-06-15T09:00')

    const endInput = screen.getByLabelText('End Time')
    await user.clear(endInput)
    await user.type(endInput, '2025-06-15T10:00')

    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/api/v2/schedule',
        expect.objectContaining({
          title: 'Brake inspection',
          entry_type: 'job',
          recurrence: 'none',
        }),
      )
    })

    // Should call onSave and onClose after successful create
    await waitFor(() => {
      expect(onSave).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('calls PUT /api/v2/schedule/{id} on edit submit (Req 36.5)', async () => {
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'entry-1' },
    })
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/api/v2/schedule/templates') {
        return Promise.resolve({ data: { templates: [], total: 0 } })
      }
      if (url.includes('/conflicts')) {
        return Promise.resolve({ data: { has_conflicts: false, conflicts: [] } })
      }
      return Promise.resolve({ data: { staff: mockStaff } })
    })

    render(
      <ScheduleEntryModal
        open={true}
        onClose={onClose}
        onSave={onSave}
        entry={mockEntry}
      />,
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Update' }))

    await waitFor(() => {
      expect(apiClient.put).toHaveBeenCalledWith(
        '/api/v2/schedule/entry-1',
        expect.objectContaining({
          title: 'Oil change',
          entry_type: 'job',
        }),
      )
    })
  })

  it('displays conflict warning after save (Req 36.6)', async () => {
    const conflictData = {
      has_conflicts: true,
      conflicts: [
        {
          entry_id: 'conflict-1',
          title: 'Existing job',
          start_time: '2025-06-15T09:30:00Z',
          end_time: '2025-06-15T10:30:00Z',
          entry_type: 'job',
        },
      ],
    }

    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'entry-1' },
    })
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/api/v2/schedule/templates') {
        return Promise.resolve({ data: { templates: [], total: 0 } })
      }
      if (url.includes('/conflicts')) {
        return Promise.resolve({ data: conflictData })
      }
      return Promise.resolve({ data: { staff: mockStaff } })
    })

    render(
      <ScheduleEntryModal
        open={true}
        onClose={onClose}
        onSave={onSave}
        entry={mockEntry}
      />,
    )

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Update' }))

    // Should show conflict warning
    await waitFor(() => {
      expect(screen.getByText('⚠ Scheduling conflict detected')).toBeInTheDocument()
      expect(screen.getByText(/Existing job/)).toBeInTheDocument()
      expect(
        screen.getByText('The entry was saved, but it overlaps with existing entries.'),
      ).toBeInTheDocument()
    })

    // onSave should still be called (entry was saved)
    expect(onSave).toHaveBeenCalled()
    // onClose should NOT be called yet (conflict warning is showing)
    expect(onClose).not.toHaveBeenCalled()

    // Dismiss the conflict warning
    await user.click(screen.getByRole('button', { name: 'OK, close' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('does not render when open is false', () => {
    const { container } = render(
      <ScheduleEntryModal open={false} onClose={onClose} onSave={onSave} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('displays submit error on API failure', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'End time must be after start time' } },
    })

    render(
      <ScheduleEntryModal open={true} onClose={onClose} onSave={onSave} />,
    )

    const user = userEvent.setup()

    const startInput = screen.getByLabelText('Start Time')
    await user.clear(startInput)
    await user.type(startInput, '2025-06-15T09:00')

    const endInput = screen.getByLabelText('End Time')
    await user.clear(endInput)
    await user.type(endInput, '2025-06-15T10:00')

    await user.click(screen.getByRole('button', { name: 'Create' }))

    await waitFor(() => {
      expect(
        screen.getByText('End time must be after start time'),
      ).toBeInTheDocument()
    })
  })
})
