import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 19 — Booking Module — Task 26.10
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
import BookingList from '../pages/bookings/BookingList'
import BookingPage from '../pages/bookings/BookingPage'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const now = new Date()
const tomorrow = new Date(now)
tomorrow.setDate(tomorrow.getDate() + 1)
tomorrow.setHours(10, 0, 0, 0)

const mockBookings = [
  {
    id: 'bk-1',
    org_id: 'org-1',
    customer_name: 'Alice Johnson',
    customer_email: 'alice@example.com',
    customer_phone: '021-555-0001',
    staff_id: null,
    service_type: 'Consultation',
    start_time: tomorrow.toISOString(),
    end_time: new Date(tomorrow.getTime() + 3600000).toISOString(),
    status: 'confirmed',
    notes: null,
    created_at: now.toISOString(),
    updated_at: now.toISOString(),
  },
  {
    id: 'bk-2',
    org_id: 'org-1',
    customer_name: 'Bob Smith',
    customer_email: null,
    customer_phone: null,
    staff_id: null,
    service_type: 'Repair',
    start_time: new Date(tomorrow.getTime() + 7200000).toISOString(),
    end_time: new Date(tomorrow.getTime() + 10800000).toISOString(),
    status: 'pending',
    notes: null,
    created_at: now.toISOString(),
    updated_at: now.toISOString(),
  },
]

const mockListResponse = { bookings: mockBookings, total: 2 }
const emptyListResponse = { bookings: [], total: 0 }

const mockPageData = {
  org_name: 'Test Business',
  org_slug: 'test-business',
  logo_url: null,
  primary_colour: '#2563eb',
  services: [],
  booking_rules: {
    id: 'rule-1',
    org_id: 'org-1',
    service_type: null,
    duration_minutes: 60,
    min_advance_hours: 2,
    max_advance_days: 90,
    buffer_minutes: 15,
    available_days: [1, 2, 3, 4, 5],
    available_hours: { start: '09:00', end: '17:00' },
    max_per_day: null,
    created_at: now.toISOString(),
    updated_at: now.toISOString(),
  },
}

const mockSlots = {
  date: '2025-07-01',
  slots: [
    { start_time: '2025-07-01T09:00:00Z', end_time: '2025-07-01T10:00:00Z', available: true },
    { start_time: '2025-07-01T10:15:00Z', end_time: '2025-07-01T11:15:00Z', available: false },
    { start_time: '2025-07-01T11:30:00Z', end_time: '2025-07-01T12:30:00Z', available: true },
  ],
}

/* ------------------------------------------------------------------ */
/*  BookingList tests                                                  */
/* ------------------------------------------------------------------ */

describe('BookingList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders page heading', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingList />)
    expect(screen.getByRole('heading', { name: 'Bookings' })).toBeInTheDocument()
  })

  it('shows loading state', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<BookingList />)
    expect(screen.getByRole('status', { name: 'Loading bookings' })).toBeInTheDocument()
  })

  it('shows empty state when no bookings', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingList />)
    expect(await screen.findByText('No bookings found.')).toBeInTheDocument()
  })

  it('displays bookings in table with customer name and status', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockListResponse })
    render(<BookingList />)
    expect(await screen.findByText('Alice Johnson')).toBeInTheDocument()
    expect(screen.getByText('Bob Smith')).toBeInTheDocument()
    // Status text appears in both filter dropdown and badges, so use getAllByText
    expect(screen.getAllByText('Confirmed').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('Pending').length).toBeGreaterThanOrEqual(2)
  })

  it('has status filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingList />)
    expect(screen.getByLabelText('Status filter')).toBeInTheDocument()
  })

  it('has date filter inputs', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: emptyListResponse })
    render(<BookingList />)
    expect(screen.getByLabelText('Start date')).toBeInTheDocument()
    expect(screen.getByLabelText('End date')).toBeInTheDocument()
  })

  it('shows cancel button for pending/confirmed bookings', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockListResponse })
    render(<BookingList />)
    await screen.findByText('Alice Johnson')
    const cancelButtons = screen.getAllByText('Cancel')
    expect(cancelButtons.length).toBe(2) // Both pending and confirmed
  })

  it('shows error on API failure', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network'))
    render(<BookingList />)
    expect(await screen.findByText('Failed to load bookings.')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  BookingPage (public) tests                                         */
/* ------------------------------------------------------------------ */

describe('BookingPage', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading state initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<BookingPage orgSlug="test-business" />)
    expect(screen.getByRole('status', { name: 'Loading booking page' })).toBeInTheDocument()
  })

  it('displays org name in header after loading', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: mockPageData })
      .mockResolvedValueOnce({ data: mockSlots })
    render(<BookingPage orgSlug="test-business" />)
    expect(await screen.findByText('Test Business')).toBeInTheDocument()
    expect(screen.getByText('Book an appointment')).toBeInTheDocument()
  })

  it('shows date picker', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: mockPageData })
      .mockResolvedValueOnce({ data: mockSlots })
    render(<BookingPage orgSlug="test-business" />)
    await screen.findByText('Test Business')
    expect(screen.getByLabelText('Select Date')).toBeInTheDocument()
  })

  it('displays available time slots', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: mockPageData })
      .mockResolvedValueOnce({ data: mockSlots })
    render(<BookingPage orgSlug="test-business" />)
    await screen.findByText('Test Business')
    // Should show available slots (2 available out of 3)
    await waitFor(() => {
      const radioButtons = screen.getAllByRole('radio')
      expect(radioButtons.length).toBe(2) // Only available slots shown
    })
  })

  it('has required form fields', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: mockPageData })
      .mockResolvedValueOnce({ data: mockSlots })
    render(<BookingPage orgSlug="test-business" />)
    await screen.findByText('Test Business')
    expect(screen.getByLabelText(/Your Name/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Email/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Phone/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Notes/)).toBeInTheDocument()
  })

  it('submit button is disabled without name and slot', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: mockPageData })
      .mockResolvedValueOnce({ data: mockSlots })
    render(<BookingPage orgSlug="test-business" />)
    await screen.findByText('Test Business')
    const submitBtn = screen.getByRole('button', { name: 'Book Appointment' })
    expect(submitBtn).toBeDisabled()
  })

  it('shows confirmation after successful submission', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: mockPageData })
      .mockResolvedValueOnce({ data: mockSlots })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'bk-new' } })

    render(<BookingPage orgSlug="test-business" />)
    await screen.findByText('Test Business')

    const user = userEvent.setup()

    // Wait for slots to load
    await waitFor(() => {
      expect(screen.getAllByRole('radio').length).toBeGreaterThan(0)
    })

    // Select a slot
    const slotButtons = screen.getAllByRole('radio')
    await user.click(slotButtons[0])

    // Fill in name
    await user.type(screen.getByLabelText(/Your Name/), 'Jane Doe')

    // Submit
    const submitBtn = screen.getByRole('button', { name: 'Book Appointment' })
    await user.click(submitBtn)

    expect(await screen.findByText('Booking Confirmed')).toBeInTheDocument()
    expect(screen.getByText(/Thank you, Jane Doe/)).toBeInTheDocument()
  })

  it('shows error on failed org lookup', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Not found'))
    render(<BookingPage orgSlug="nonexistent" />)
    expect(await screen.findByText('Unable to load booking page.')).toBeInTheDocument()
  })
})
