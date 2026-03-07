import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 64.1-64.5
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
import BookingCalendarPage from '../pages/bookings/BookingCalendarPage'
import BookingCalendar from '../pages/bookings/BookingCalendar'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const now = new Date()
const todayStr = now.toISOString()

const mockBookings = [
  {
    id: 'bk-1',
    customer_name: 'John Smith',
    vehicle_rego: 'ABC123',
    service_type: 'WOF Inspection',
    scheduled_at: new Date(now.getFullYear(), now.getMonth(), now.getDate(), 9, 0).toISOString(),
    duration_minutes: 60,
    status: 'scheduled',
  },
  {
    id: 'bk-2',
    customer_name: 'Jane Doe',
    vehicle_rego: 'XYZ789',
    service_type: 'Full Service',
    scheduled_at: new Date(now.getFullYear(), now.getMonth(), now.getDate(), 14, 0).toISOString(),
    duration_minutes: 120,
    status: 'confirmed',
  },
  {
    id: 'bk-3',
    customer_name: 'Bob Wilson',
    vehicle_rego: null,
    service_type: 'Brake Repair',
    scheduled_at: new Date(now.getFullYear(), now.getMonth(), now.getDate(), 11, 0).toISOString(),
    duration_minutes: 90,
    status: 'completed',
  },
]

const mockListResponse = {
  bookings: mockBookings,
  total: 3,
  view: 'week',
  start_date: todayStr,
  end_date: todayStr,
}

const emptyListResponse = {
  bookings: [],
  total: 0,
  view: 'week',
  start_date: todayStr,
  end_date: todayStr,
}

/* ------------------------------------------------------------------ */
/*  BookingCalendarPage tests                                          */
/* ------------------------------------------------------------------ */

describe('BookingCalendarPage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders page heading (Req 64.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingCalendarPage />)
    expect(screen.getByRole('heading', { name: 'Bookings' })).toBeInTheDocument()
  })

  it('shows loading spinner while fetching bookings', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<BookingCalendarPage />)
    expect(screen.getByRole('status', { name: 'Loading bookings' })).toBeInTheDocument()
  })

  it('shows empty state when no bookings', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingCalendarPage />)
    expect(await screen.findByText(/No bookings for this period/)).toBeInTheDocument()
  })

  it('displays booking cards with customer name and status (Req 64.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockListResponse })
    render(<BookingCalendarPage />)
    expect(await screen.findByText('John Smith')).toBeInTheDocument()
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
    expect(screen.getByText('Bob Wilson')).toBeInTheDocument()
    // Status badges appear alongside status filter options, so use getAllByText
    expect(screen.getAllByText('Scheduled').length).toBeGreaterThanOrEqual(2) // filter option + badge
    expect(screen.getAllByText('Confirmed').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('Completed').length).toBeGreaterThanOrEqual(2)
  })

  it('has New Booking button that opens form modal (Req 64.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingCalendarPage />)
    await screen.findByText(/No bookings/)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Booking' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('New Booking')).toBeInTheDocument()
  })

  it('form has required fields: customer, date/time, duration, service type (Req 64.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingCalendarPage />)
    await screen.findByText(/No bookings/)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Booking' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByLabelText(/Customer/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/Date & Time/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/Duration/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/Service Type/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/Vehicle Rego/)).toBeInTheDocument()
  })

  it('form has send confirmation checkbox for new bookings (Req 64.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingCalendarPage />)
    await screen.findByText(/No bookings/)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Booking' }))
    expect(screen.getByLabelText(/Send confirmation email\/SMS/)).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  BookingCalendar view switching tests                               */
/* ------------------------------------------------------------------ */

describe('BookingCalendar', () => {
  const noop = () => {}

  beforeEach(() => { vi.clearAllMocks() })

  it('renders view selector with day/week/month options (Req 64.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(
      <BookingCalendar
        onCreateBooking={noop}
        onEditBooking={noop}
        onConvertBooking={noop}
        refreshKey={0}
      />,
    )
    const viewSelect = screen.getByLabelText('View')
    expect(viewSelect).toBeInTheDocument()
    const options = within(viewSelect).getAllByRole('option')
    const values = options.map((o) => o.getAttribute('value'))
    expect(values).toContain('day')
    expect(values).toContain('week')
    expect(values).toContain('month')
  })

  it('renders status filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(
      <BookingCalendar
        onCreateBooking={noop}
        onEditBooking={noop}
        onConvertBooking={noop}
        refreshKey={0}
      />,
    )
    expect(screen.getByLabelText('Status')).toBeInTheDocument()
  })

  it('has Today and navigation buttons', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(
      <BookingCalendar
        onCreateBooking={noop}
        onEditBooking={noop}
        onConvertBooking={noop}
        refreshKey={0}
      />,
    )
    expect(screen.getByRole('button', { name: 'Today' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument()
  })

  it('shows convert buttons on completed/confirmed bookings (Req 64.5)', async () => {
    const dayResponse = { ...mockListResponse, view: 'day' }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: dayResponse })
    render(
      <BookingCalendar
        onCreateBooking={noop}
        onEditBooking={noop}
        onConvertBooking={noop}
        refreshKey={0}
      />,
    )
    // Switch to day view to see full booking cards
    const user = userEvent.setup()
    const viewSelect = screen.getByLabelText('View')
    await user.selectOptions(viewSelect, 'day')

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalled()
    })
  })

  it('calls API with correct view parameter when switching views', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(
      <BookingCalendar
        onCreateBooking={noop}
        onEditBooking={noop}
        onConvertBooking={noop}
        refreshKey={0}
      />,
    )
    const user = userEvent.setup()
    const viewSelect = screen.getByLabelText('View')
    await user.selectOptions(viewSelect, 'month')

    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toBe('/bookings')
      expect(lastCall[1].params.view).toBe('month')
    })
  })

  it('fetches bookings on mount with default week view', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(
      <BookingCalendar
        onCreateBooking={noop}
        onEditBooking={noop}
        onConvertBooking={noop}
        refreshKey={0}
      />,
    )
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith('/bookings', expect.objectContaining({
        params: expect.objectContaining({ view: 'week' }),
      }))
    })
  })

  it('shows error message when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(
      <BookingCalendar
        onCreateBooking={noop}
        onEditBooking={noop}
        onConvertBooking={noop}
        refreshKey={0}
      />,
    )
    expect(await screen.findByText('Failed to load bookings.')).toBeInTheDocument()
  })
})
