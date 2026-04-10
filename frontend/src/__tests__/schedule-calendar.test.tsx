import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Staff Roster View — ScheduleCalendar component
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return { default: { get: mockGet } }
})

import apiClient from '@/api/client'
import ScheduleCalendar from '../pages/schedule/ScheduleCalendar'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const today = new Date()
today.setHours(9, 0, 0, 0)
const todayEnd = new Date(today)
todayEnd.setHours(11, 0, 0, 0)

const mockStaff = {
  data: {
    staff: [
      {
        id: 'staff-1', name: 'John Smith', first_name: 'John', last_name: 'Smith',
        position: 'Mechanic', is_active: true, shift_start: '08:00', shift_end: '17:00',
        availability_schedule: { monday: { start: '08:00', end: '17:00' }, tuesday: { start: '08:00', end: '17:00' } },
      },
      {
        id: 'staff-2', name: 'Jane Doe', first_name: 'Jane', last_name: 'Doe',
        position: 'Electrician', is_active: true, shift_start: '09:00', shift_end: '17:00',
        availability_schedule: {},
      },
    ],
    total: 2,
  },
}

const mockEntries = {
  data: {
    entries: [
      {
        id: 'entry-1', staff_id: 'staff-1', job_id: 'job-1', booking_id: null,
        title: 'Fix brakes', description: 'Brake pad replacement',
        start_time: today.toISOString(), end_time: todayEnd.toISOString(),
        entry_type: 'job', status: 'scheduled',
      },
    ],
    total: 1,
  },
}

const emptyEntries = { data: { entries: [], total: 0 } }

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('ScheduleCalendar — Staff Roster', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading state initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ScheduleCalendar />)
    expect(screen.getByText('Loading roster…')).toBeInTheDocument()
  })

  it('renders staff names as column headers', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(mockStaff)
      .mockResolvedValueOnce(emptyEntries)
    render(<ScheduleCalendar />)
    expect(await screen.findByText('John Smith')).toBeInTheDocument()
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
  })

  it('shows staff positions', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(mockStaff)
      .mockResolvedValueOnce(emptyEntries)
    render(<ScheduleCalendar />)
    expect(await screen.findByText('Mechanic')).toBeInTheDocument()
    expect(screen.getByText('Electrician')).toBeInTheDocument()
  })

  it('displays schedule entries', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(mockStaff)
      .mockResolvedValueOnce(mockEntries)
    render(<ScheduleCalendar />)
    expect(await screen.findByText('Fix brakes')).toBeInTheDocument()
  })

  it('has staff filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(mockStaff)
      .mockResolvedValueOnce(emptyEntries)
    render(<ScheduleCalendar />)
    await screen.findByText('John Smith')
    expect(screen.getByText('All Staff')).toBeInTheDocument()
  })

  it('renders entry type legend', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(mockStaff)
      .mockResolvedValueOnce(emptyEntries)
    render(<ScheduleCalendar />)
    await screen.findByText('John Smith')
    expect(screen.getByText('job')).toBeInTheDocument()
    expect(screen.getByText('booking')).toBeInTheDocument()
    expect(screen.getByText('break')).toBeInTheDocument()
    expect(screen.getByText('other')).toBeInTheDocument()
  })

  it('has Today button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(mockStaff)
      .mockResolvedValueOnce(emptyEntries)
    render(<ScheduleCalendar />)
    await screen.findByText('John Smith')
    expect(screen.getByText('Today')).toBeInTheDocument()
  })
})
