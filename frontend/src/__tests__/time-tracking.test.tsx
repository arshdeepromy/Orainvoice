import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * Validates: Requirements 13.2, 13.5
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import TimeSheet from '../pages/time-tracking/TimeSheet'
import HeaderTimer from '../components/timer/HeaderTimer'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockTimesheet = {
  week_start: '2024-06-10',
  week_end: '2024-06-16',
  days: [
    {
      date: '2024-06-10',
      entries: [
        {
          id: 'te-1', description: 'Plumbing repair',
          start_time: '2024-06-10T09:00:00Z',
          end_time: '2024-06-10T11:00:00Z',
          duration_minutes: 120, is_billable: true,
          hourly_rate: '85.00', is_invoiced: false,
          job_id: null, project_id: null,
        },
      ],
      total_minutes: 120,
      billable_minutes: 120,
    },
    { date: '2024-06-11', entries: [], total_minutes: 0, billable_minutes: 0 },
    { date: '2024-06-12', entries: [], total_minutes: 0, billable_minutes: 0 },
    { date: '2024-06-13', entries: [], total_minutes: 0, billable_minutes: 0 },
    { date: '2024-06-14', entries: [], total_minutes: 0, billable_minutes: 0 },
    { date: '2024-06-15', entries: [], total_minutes: 0, billable_minutes: 0 },
    { date: '2024-06-16', entries: [], total_minutes: 0, billable_minutes: 0 },
  ],
  weekly_total_minutes: 120,
  weekly_billable_minutes: 120,
}

/* ------------------------------------------------------------------ */
/*  TimeSheet tests                                                    */
/* ------------------------------------------------------------------ */

describe('TimeSheet', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders loading state initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<TimeSheet />)
    expect(screen.getByRole('status', { name: /loading timesheet/i })).toBeTruthy()
  })

  it('renders weekly timesheet after loading', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockTimesheet })
    render(<TimeSheet />)
    await waitFor(() => {
      expect(screen.getByRole('table', { name: /weekly timesheet/i })).toBeTruthy()
    })
    expect(screen.getByText('Plumbing repair')).toBeTruthy()
    expect(screen.getByText('2024-06-10')).toBeTruthy()
  })

  it('displays weekly totals', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockTimesheet })
    render(<TimeSheet />)
    await waitFor(() => {
      expect(screen.getByText(/Weekly Total/i)).toBeTruthy()
    })
    // 120 minutes = 2h 0m
    expect(screen.getAllByText('2h 0m').length).toBeGreaterThan(0)
  })

  it('navigates to previous week', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockTimesheet })
    render(<TimeSheet />)
    await waitFor(() => {
      expect(screen.getByRole('table')).toBeTruthy()
    })
    await userEvent.click(screen.getByRole('button', { name: /previous week/i }))
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledTimes(2)
    })
  })

  it('navigates to next week', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockTimesheet })
    render(<TimeSheet />)
    await waitFor(() => {
      expect(screen.getByRole('table')).toBeTruthy()
    })
    await userEvent.click(screen.getByRole('button', { name: /next week/i }))
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledTimes(2)
    })
  })
})

/* ------------------------------------------------------------------ */
/*  HeaderTimer tests                                                  */
/* ------------------------------------------------------------------ */

describe('HeaderTimer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('renders start button when no timer active', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: null })
    render(<HeaderTimer />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /start timer/i })).toBeTruthy()
    })
  })

  it('starts timer on click', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: null })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        id: 'te-new',
        start_time: new Date().toISOString(),
        description: 'Test task',
      },
    })
    render(<HeaderTimer />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /start timer/i })).toBeTruthy()
    })
    await userEvent.click(screen.getByRole('button', { name: /start timer/i }))
    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/api/v2/time-entries/timer/start', {})
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /stop timer/i })).toBeTruthy()
    })
  })

  it('stops timer on click', async () => {
    const startTime = new Date().toISOString()
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'te-active', start_time: startTime, description: 'Running' },
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { entry: { id: 'te-active' }, duration_minutes: 30 },
    })
    render(<HeaderTimer />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /stop timer/i })).toBeTruthy()
    })
    await userEvent.click(screen.getByRole('button', { name: /stop timer/i }))
    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/api/v2/time-entries/timer/stop')
    })
  })

  it('persists timer state to localStorage', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'te-persist', start_time: '2024-06-15T09:00:00Z', description: 'Persisted' },
    })
    render(<HeaderTimer />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /stop timer/i })).toBeTruthy()
    })
    const stored = localStorage.getItem('orainvoice_active_timer')
    expect(stored).toBeTruthy()
    const parsed = JSON.parse(stored!)
    expect(parsed.entryId).toBe('te-persist')
  })

  it('displays elapsed time', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'te-elapsed', start_time: new Date(Date.now() - 3661000).toISOString(), description: null },
    })
    render(<HeaderTimer />)
    await waitFor(() => {
      const elapsed = screen.getByLabelText(/elapsed time/i)
      expect(elapsed).toBeTruthy()
      // Should show at least 01:01:xx
      expect(elapsed.textContent).toMatch(/01:01/)
    })
  })
})
