import { render, screen, within, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 18 — Scheduling Module — Task 25.8
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, put: mockPut },
  }
})

import apiClient from '@/api/client'
import ScheduleCalendar from '../pages/schedule/ScheduleCalendar'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

// Use today's date so entries always appear in the current week view
const today = new Date()
today.setHours(9, 0, 0, 0)
const todayEnd = new Date(today)
todayEnd.setHours(11, 0, 0, 0)
const todayLunch = new Date(today)
todayLunch.setHours(12, 0, 0, 0)
const todayLunchEnd = new Date(today)
todayLunchEnd.setHours(13, 0, 0, 0)

const mockEntries = [
  {
    id: 'entry-1',
    org_id: 'org-1',
    staff_id: 'staff-1',
    job_id: 'job-1',
    booking_id: null,
    location_id: 'loc-1',
    title: 'Fix plumbing',
    description: 'Repair kitchen sink',
    start_time: today.toISOString(),
    end_time: todayEnd.toISOString(),
    entry_type: 'job',
    status: 'scheduled',
    notes: null,
  },
  {
    id: 'entry-2',
    org_id: 'org-1',
    staff_id: 'staff-1',
    job_id: null,
    booking_id: null,
    location_id: null,
    title: 'Lunch break',
    description: null,
    start_time: todayLunch.toISOString(),
    end_time: todayLunchEnd.toISOString(),
    entry_type: 'break',
    status: 'scheduled',
    notes: null,
  },
]

const emptyResponse = { data: { entries: [], total: 0 } }
const populatedResponse = { data: { entries: mockEntries, total: 2 } }

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('ScheduleCalendar', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading state initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ScheduleCalendar />)
    expect(screen.getByRole('status', { name: 'Loading schedule' })).toBeInTheDocument()
  })

  it('renders week view by default with grid', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(populatedResponse)
    render(<ScheduleCalendar />)
    const grid = await screen.findByRole('grid', { name: 'Week schedule view' })
    expect(grid).toBeInTheDocument()
  })

  it('displays schedule entries in the calendar', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(populatedResponse)
    render(<ScheduleCalendar />)
    expect(await screen.findByText('Fix plumbing')).toBeInTheDocument()
    expect(screen.getByText('Lunch break')).toBeInTheDocument()
  })

  it('switches to day view', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(populatedResponse)
    render(<ScheduleCalendar />)
    await screen.findByRole('grid', { name: 'Week schedule view' })

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('View'), 'day')

    await waitFor(() => {
      expect(screen.getByRole('grid', { name: 'Day schedule view' })).toBeInTheDocument()
    })
  })

  it('switches to month view', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(populatedResponse)
    render(<ScheduleCalendar />)
    await screen.findByRole('grid', { name: 'Week schedule view' })

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('View'), 'month')

    await waitFor(() => {
      expect(screen.getByRole('grid', { name: 'Month schedule view' })).toBeInTheDocument()
    })
  })

  it('navigates to previous period', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(emptyResponse)
    render(<ScheduleCalendar />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Previous period' }))

    // Should trigger a new API call with different date range
    await waitFor(() => {
      expect((apiClient.get as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
  })

  it('navigates to next period', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(emptyResponse)
    render(<ScheduleCalendar />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Next period' }))

    await waitFor(() => {
      expect((apiClient.get as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
  })

  it('has today button for quick navigation', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(emptyResponse)
    render(<ScheduleCalendar />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'Go to today' })).toBeInTheDocument()
  })

  it('renders staff filter input', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(emptyResponse)
    render(<ScheduleCalendar />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Staff')).toBeInTheDocument()
  })

  it('renders location filter input', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(emptyResponse)
    render(<ScheduleCalendar />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Location')).toBeInTheDocument()
  })

  it('entries are draggable for reschedule', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(populatedResponse)
    render(<ScheduleCalendar />)
    const entry = await screen.findByText('Fix plumbing')
    const draggableEl = entry.closest('[draggable]')
    expect(draggableEl).toBeTruthy()
    expect(draggableEl?.getAttribute('draggable')).toBe('true')
  })

  it('calls reschedule API on drop', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(populatedResponse)
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockEntries[0] })
    render(<ScheduleCalendar />)

    const entry = await screen.findByText('Fix plumbing')
    const draggableEl = entry.closest('[draggable]')!

    // Simulate drag start
    fireEvent.dragStart(draggableEl)

    // Find a grid cell to drop on
    const gridCells = screen.getAllByRole('gridcell')
    expect(gridCells.length).toBeGreaterThan(0)

    fireEvent.dragOver(gridCells[0])
    fireEvent.drop(gridCells[0])

    await waitFor(() => {
      expect(apiClient.put).toHaveBeenCalledWith(
        '/api/v2/schedule/entry-1/reschedule',
        expect.objectContaining({
          start_time: expect.any(String),
          end_time: expect.any(String),
        }),
      )
    })
  })

  it('renders entry type legend', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(emptyResponse)
    render(<ScheduleCalendar />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByText('job')).toBeInTheDocument()
    expect(screen.getByText('booking')).toBeInTheDocument()
    expect(screen.getByText('break')).toBeInTheDocument()
    expect(screen.getByText('other')).toBeInTheDocument()
  })
})
