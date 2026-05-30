/**
 * Integration tests for QuoteDetail cancel workflow (Task 9.4).
 *
 * Tests:
 * - Cancel button visibility by status (visible for issued/sent, hidden for others)
 * - Cancelled state display: red badge, reason text, date, user name
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, act } from '@testing-library/react'

// ─── Mocks ───────────────────────────────────────────────────────────────────

vi.mock('../../../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))

vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))

import apiClient from '../../../api/client'
import QuoteDetail from '../QuoteDetail'

// ─── Fixtures ────────────────────────────────────────────────────────────────

function makeQuote(overrides: Record<string, unknown> = {}) {
  return {
    id: 'q-cancel-test',
    org_id: 'org-1',
    customer_id: 'cust-1',
    quote_number: 'QUO-0042',
    vehicle_rego: 'XYZ789',
    vehicle_make: 'Honda',
    vehicle_model: 'Civic',
    vehicle_year: 2022,
    project_id: null,
    status: 'draft',
    valid_until: '2025-12-31',
    subtotal: '200.00',
    gst_amount: '30.00',
    total: '230.00',
    discount_type: null,
    discount_value: '0',
    discount_amount: '0',
    shipping_charges: '0',
    adjustment: '0',
    notes: null,
    terms: null,
    subject: null,
    acceptance_token: null,
    converted_invoice_id: null,
    line_items: [
      {
        id: 'li-1',
        item_type: 'service',
        description: 'Brake service',
        quantity: 1,
        unit_price: '200.00',
        hours: null,
        hourly_rate: null,
        is_gst_exempt: false,
        warranty_note: null,
        line_total: '200.00',
        sort_order: 1,
        catalogue_item_id: null,
        stock_item_id: null,
        gst_inclusive: false,
        inclusive_price: null,
        tax_rate: '15',
      },
    ],
    created_by: 'user-1',
    created_at: '2025-06-01T10:00:00Z',
    updated_at: '2025-06-01T10:00:00Z',
    order_number: null,
    salesperson_id: null,
    salesperson_name: null,
    additional_vehicles: [],
    fluid_usage: [],
    attachment_count: 0,
    cancel_reason: null,
    cancelled_at: null,
    cancelled_by: null,
    cancelled_by_name: null,
    ...overrides,
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mockFetchQuote(quote: ReturnType<typeof makeQuote>) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === `/quotes/${quote.id}`) {
      return Promise.resolve({ data: quote })
    }
    return Promise.resolve({ data: {} })
  })
}

async function renderWithQuote(quote: ReturnType<typeof makeQuote>) {
  mockFetchQuote(quote)
  let result: ReturnType<typeof render>
  await act(async () => {
    result = render(<QuoteDetail quoteId={quote.id as string} />)
  })
  return result!
}

// ─── Setup / Teardown ────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
  document.querySelectorAll('style[data-quote-print="true"]').forEach((el) => el.remove())
})

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('QuoteDetail — Cancel button visibility by status', () => {
  it('shows Cancel Quote button when status is "issued"', async () => {
    const quote = makeQuote({ status: 'issued' })
    await renderWithQuote(quote)
    expect(screen.getByText('Cancel Quote')).toBeInTheDocument()
  })

  it('shows Cancel Quote button when status is "sent"', async () => {
    const quote = makeQuote({ status: 'sent' })
    await renderWithQuote(quote)
    expect(screen.getByText('Cancel Quote')).toBeInTheDocument()
  })

  it('does NOT show Cancel Quote button when status is "draft"', async () => {
    const quote = makeQuote({ status: 'draft' })
    await renderWithQuote(quote)
    expect(screen.queryByText('Cancel Quote')).not.toBeInTheDocument()
  })

  it('does NOT show Cancel Quote button when status is "accepted"', async () => {
    const quote = makeQuote({ status: 'accepted' })
    await renderWithQuote(quote)
    expect(screen.queryByText('Cancel Quote')).not.toBeInTheDocument()
  })

  it('does NOT show Cancel Quote button when status is "declined"', async () => {
    const quote = makeQuote({ status: 'declined' })
    await renderWithQuote(quote)
    expect(screen.queryByText('Cancel Quote')).not.toBeInTheDocument()
  })

  it('does NOT show Cancel Quote button when status is "expired"', async () => {
    const quote = makeQuote({ status: 'expired' })
    await renderWithQuote(quote)
    expect(screen.queryByText('Cancel Quote')).not.toBeInTheDocument()
  })

  it('does NOT show Cancel Quote button when status is "cancelled"', async () => {
    const quote = makeQuote({
      status: 'cancelled',
      cancel_reason: 'Already cancelled',
      cancelled_at: '2025-06-10T12:00:00Z',
      cancelled_by_name: 'Admin User',
    })
    await renderWithQuote(quote)
    // The "Cancel Quote" button in the action toolbar should not be present
    // (there may be a "Cancelled" badge text, but not the button)
    const cancelButtons = screen.queryAllByText('Cancel Quote')
    // Filter to only buttons (not modal text)
    const actionButtons = cancelButtons.filter(
      (el) => el.tagName === 'BUTTON' || el.closest('button')
    )
    expect(actionButtons.length).toBe(0)
  })
})

describe('QuoteDetail — Cancelled state display', () => {
  const cancelledQuote = makeQuote({
    status: 'cancelled',
    cancel_reason: 'Customer requested different scope',
    cancelled_at: '2025-06-15T14:30:00Z',
    cancelled_by: 'user-42',
    cancelled_by_name: 'Jane Smith',
  })

  it('displays a "Cancelled" badge when quote is cancelled', async () => {
    await renderWithQuote(cancelledQuote)
    // The cancellation banner has a "Cancelled" badge
    const badges = screen.getAllByText(/cancelled/i)
    // At least one should be the red badge in the banner
    const badgeEl = badges.find(
      (el) => el.classList.contains('text-red-700') || el.closest('.bg-red-100')
    )
    expect(badgeEl).toBeTruthy()
  })

  it('displays the cancellation reason text', async () => {
    await renderWithQuote(cancelledQuote)
    expect(screen.getByText('Customer requested different scope')).toBeInTheDocument()
  })

  it('displays the cancellation date', async () => {
    await renderWithQuote(cancelledQuote)
    // The date is formatted using en-NZ locale (e.g. "15 Jun 2025" or "16 Jun 2025" depending on TZ)
    expect(screen.getByText(/Cancelled on \d{2} \w{3} 2025/)).toBeInTheDocument()
  })

  it('displays the name of the user who cancelled', async () => {
    await renderWithQuote(cancelledQuote)
    expect(screen.getByText(/Jane Smith/)).toBeInTheDocument()
  })

  it('shows Delete button for cancelled quotes', async () => {
    await renderWithQuote(cancelledQuote)
    expect(screen.getByText('Delete')).toBeInTheDocument()
  })
})
