import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 49 — Customer Portal Enhancements, Task 46.11
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

vi.mock('react-router-dom', () => ({
  useParams: () => ({ token: 'test-token-123' }),
}))

import apiClient from '@/api/client'

// ---------------------------------------------------------------------------
// QuoteAcceptance tests
// ---------------------------------------------------------------------------

import { QuoteAcceptance } from '../pages/portal/QuoteAcceptance'

const mockQuotes = [
  {
    id: 'q1',
    quote_number: 'QT-001',
    status: 'sent',
    expiry_date: '2025-12-31',
    terms: null,
    line_items: [
      { description: 'Brake service', quantity: 1, unit_price: 150, total: 150 },
    ],
    subtotal: 150,
    tax_amount: 22.5,
    total: 172.5,
    currency: 'NZD',
    acceptance_token: 'abc123',
    accepted_at: null,
    created_at: '2025-01-15T10:00:00Z',
  },
  {
    id: 'q2',
    quote_number: 'QT-002',
    status: 'accepted',
    expiry_date: null,
    terms: null,
    line_items: [],
    subtotal: 200,
    tax_amount: 30,
    total: 230,
    currency: 'NZD',
    acceptance_token: null,
    accepted_at: '2025-01-10T10:00:00Z',
    created_at: '2025-01-05T10:00:00Z',
  },
]

describe('QuoteAcceptance', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders quotes and shows Accept button for sent quotes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { quotes: mockQuotes },
    })

    render(<QuoteAcceptance token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('QT-001')).toBeInTheDocument()
    })

    expect(screen.getByText('QT-002')).toBeInTheDocument()
    expect(screen.getByText('Accept Quote')).toBeInTheDocument()
    expect(screen.getByText('Accepted')).toBeInTheDocument()
  })

  it('calls accept endpoint when Accept button is clicked', async () => {
    const user = userEvent.setup()
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { quotes: mockQuotes },
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { quote_id: 'q1', status: 'accepted' },
    })

    render(<QuoteAcceptance token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('Accept Quote')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Accept Quote'))

    expect(apiClient.post).toHaveBeenCalledWith('/portal/test-token/quotes/q1/accept')
  })

  it('shows empty state when no quotes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { quotes: [] },
    })

    render(<QuoteAcceptance token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('No quotes found.')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// LoyaltyBalance tests
// ---------------------------------------------------------------------------

import { LoyaltyBalance } from '../pages/portal/LoyaltyBalance'

const mockLoyaltyData = {
  total_points: 750,
  current_tier: { name: 'Silver', threshold_points: 500, discount_percent: 5 },
  next_tier: { name: 'Gold', threshold_points: 1000, discount_percent: 10 },
  points_to_next_tier: 250,
  transactions: [
    { transaction_type: 'earn', points: 500, balance_after: 500, reference_type: 'invoice', created_at: '2025-01-10T10:00:00Z' },
    { transaction_type: 'redeem', points: -50, balance_after: 450, reference_type: 'invoice', created_at: '2025-01-12T10:00:00Z' },
  ],
}

describe('LoyaltyBalance', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders loyalty points, tier, and transactions', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: mockLoyaltyData,
    })

    render(<LoyaltyBalance token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('750')).toBeInTheDocument()
    })

    expect(screen.getAllByText('Silver').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Gold').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('250 points to go')).toBeInTheDocument()
    expect(screen.getByText('earn')).toBeInTheDocument()
    expect(screen.getByText('redeem')).toBeInTheDocument()
  })

  it('shows "at the top" when no next tier', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { ...mockLoyaltyData, next_tier: null, points_to_next_tier: null },
    })

    render(<LoyaltyBalance token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText("You're at the top!")).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// PoweredByFooter tests
// ---------------------------------------------------------------------------

import { PoweredByFooter } from '../pages/portal/PoweredByFooter'

describe('PoweredByFooter', () => {
  it('renders Powered By text when show_powered_by is true', () => {
    render(
      <PoweredByFooter
        poweredBy={{
          platform_name: 'OraInvoice',
          logo_url: null,
          signup_url: 'https://orainvoice.com/signup',
          website_url: 'https://orainvoice.com',
          show_powered_by: true,
        }}
      />
    )

    expect(screen.getByText('OraInvoice')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'OraInvoice' })
    expect(link).toHaveAttribute('href', expect.stringContaining('utm_source=portal'))
  })

  it('renders nothing when show_powered_by is false', () => {
    const { container } = render(
      <PoweredByFooter
        poweredBy={{
          platform_name: 'OraInvoice',
          logo_url: null,
          signup_url: null,
          website_url: null,
          show_powered_by: false,
        }}
      />
    )

    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when poweredBy is null', () => {
    const { container } = render(<PoweredByFooter poweredBy={null} />)
    expect(container.innerHTML).toBe('')
  })
})

// ---------------------------------------------------------------------------
// AssetHistory tests
// ---------------------------------------------------------------------------

import { AssetHistory } from '../pages/portal/AssetHistory'

const mockAssets = [
  {
    id: 'a1',
    asset_type: 'vehicle',
    identifier: 'ABC123',
    make: 'Toyota',
    model: 'Corolla',
    year: 2020,
    description: null,
    serial_number: null,
    service_history: [
      {
        reference_type: 'job',
        reference_id: 'j1',
        reference_number: 'JOB-001',
        description: 'Oil change',
        date: '2025-01-10T10:00:00Z',
        status: 'completed',
      },
    ],
  },
]

describe('AssetHistory', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders assets with service history', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { assets: mockAssets },
    })

    render(<AssetHistory token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('ABC123')).toBeInTheDocument()
    })

    expect(screen.getByText('vehicle')).toBeInTheDocument()
    expect(screen.getByText('Toyota Corolla 2020')).toBeInTheDocument()
    expect(screen.getByText('JOB-001')).toBeInTheDocument()
  })

  it('shows empty state when no assets', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { assets: [] },
    })

    render(<AssetHistory token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('No assets found.')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// BookingManager tests
// ---------------------------------------------------------------------------

import { BookingManager } from '../pages/portal/BookingManager'

const mockBookings = [
  {
    id: 'b1',
    service_type: 'Oil Change',
    start_time: '2025-02-01T09:00:00Z',
    end_time: '2025-02-01T10:00:00Z',
    status: 'confirmed',
    notes: null,
    created_at: '2025-01-15T10:00:00Z',
  },
]

describe('BookingManager', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders bookings list', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { bookings: mockBookings },
    })

    render(<BookingManager token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('Oil Change')).toBeInTheDocument()
    })

    expect(screen.getByText('Confirmed')).toBeInTheDocument()
  })

  it('shows New Booking button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { bookings: [] },
    })

    render(<BookingManager token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('New Booking')).toBeInTheDocument()
    })
  })

  it('shows date picker when New Booking is clicked', async () => {
    const user = userEvent.setup()
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { bookings: [] },
    })

    render(<BookingManager token="test-token" />)

    await waitFor(() => {
      expect(screen.getByText('New Booking')).toBeInTheDocument()
    })

    await user.click(screen.getByText('New Booking'))

    expect(screen.getByText('Select a date')).toBeInTheDocument()
  })
})
