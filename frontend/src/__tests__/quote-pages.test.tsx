import { render, screen, within, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 12.1, 12.2, 12.5, 12.6, 12.7
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
import QuoteList from '../pages/quotes/QuoteList'
import QuoteDetail from '../pages/quotes/QuoteDetail'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockQuotes = [
  {
    id: 'qt-1', quote_number: 'QT-00001', customer_id: 'cust-1',
    status: 'draft', total: '1500.00', currency: 'NZD',
    expiry_date: '2024-07-01', version_number: 1,
    created_at: '2024-06-01T10:00:00Z',
  },
  {
    id: 'qt-2', quote_number: 'QT-00002', customer_id: 'cust-2',
    status: 'sent', total: '3200.00', currency: 'NZD',
    expiry_date: '2024-07-15', version_number: 1,
    created_at: '2024-06-02T10:00:00Z',
  },
  {
    id: 'qt-3', quote_number: 'QT-00003', customer_id: 'cust-1',
    status: 'accepted', total: '800.00', currency: 'NZD',
    expiry_date: null, version_number: 2,
    created_at: '2024-06-03T10:00:00Z',
  },
]

const mockQuoteDetail = {
  id: 'qt-1',
  quote_number: 'QT-00001',
  customer_id: 'cust-1',
  project_id: null,
  status: 'draft',
  expiry_date: '2024-07-01',
  terms: 'Net 30',
  internal_notes: null,
  line_items: [
    { description: 'Plumbing work', quantity: '3', unit_price: '85.00', tax_rate: '15' },
    { description: 'Parts', quantity: '1', unit_price: '120.00', tax_rate: '15' },
  ],
  subtotal: '375.00',
  tax_amount: '56.25',
  total: '431.25',
  currency: 'NZD',
  version_number: 1,
  previous_version_id: null,
  converted_invoice_id: null,
  acceptance_token: 'abc123',
  created_at: '2024-06-01T10:00:00Z',
  updated_at: '2024-06-01T10:00:00Z',
}

/* ------------------------------------------------------------------ */
/*  QuoteList tests                                                    */
/* ------------------------------------------------------------------ */

describe('QuoteList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders loading state initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<QuoteList />)
    expect(screen.getByRole('status', { name: /loading quotes/i })).toBeTruthy()
  })

  it('renders quotes table after loading', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { quotes: mockQuotes, total: 3, page: 1, page_size: 20 },
    })
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByRole('table', { name: /quotes list/i })).toBeTruthy()
    })
    expect(screen.getByText('QT-00001')).toBeTruthy()
    expect(screen.getByText('QT-00002')).toBeTruthy()
    expect(screen.getByText('QT-00003')).toBeTruthy()
  })

  it('shows empty state when no quotes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { quotes: [], total: 0, page: 1, page_size: 20 },
    })
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText(/no quotes found/i)).toBeTruthy()
    })
  })

  it('filters by status', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { quotes: mockQuotes, total: 3, page: 1, page_size: 20 },
    })
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByRole('table')).toBeTruthy()
    })

    const select = screen.getByLabelText(/status/i)
    await userEvent.selectOptions(select, 'sent')

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        expect.stringContaining('status=sent'),
      )
    })
  })
})

/* ------------------------------------------------------------------ */
/*  QuoteDetail tests                                                  */
/* ------------------------------------------------------------------ */

describe('QuoteDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders loading state initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<QuoteDetail quoteId="qt-1" />)
    expect(screen.getByRole('status', { name: /loading quote/i })).toBeTruthy()
  })

  it('renders quote details after loading', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockQuoteDetail })
    render(<QuoteDetail quoteId="qt-1" />)
    await waitFor(() => {
      expect(screen.getByText(/QT-00001/)).toBeTruthy()
    })
    expect(screen.getByText(/draft/i)).toBeTruthy()
    expect(screen.getByText('Plumbing work')).toBeTruthy()
    expect(screen.getByText('Parts')).toBeTruthy()
  })

  it('shows send button for draft quotes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockQuoteDetail })
    render(<QuoteDetail quoteId="qt-1" />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /send/i })).toBeTruthy()
    })
  })

  it('shows convert button for accepted quotes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { ...mockQuoteDetail, status: 'accepted' },
    })
    render(<QuoteDetail quoteId="qt-1" />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /convert to invoice/i })).toBeTruthy()
    })
  })

  it('shows revise button for draft/sent/declined quotes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockQuoteDetail })
    render(<QuoteDetail quoteId="qt-1" />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create revision/i })).toBeTruthy()
    })
  })

  it('calls send API when send button clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockQuoteDetail })
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { ...mockQuoteDetail, status: 'sent' } })
    render(<QuoteDetail quoteId="qt-1" />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /send/i })).toBeTruthy()
    })
    await userEvent.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => {
      expect(apiClient.put).toHaveBeenCalledWith('/api/v2/quotes/qt-1/send')
    })
  })

  it('displays line items table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockQuoteDetail })
    render(<QuoteDetail quoteId="qt-1" />)
    await waitFor(() => {
      expect(screen.getByRole('table', { name: /quote line items/i })).toBeTruthy()
    })
  })

  it('displays totals', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockQuoteDetail })
    render(<QuoteDetail quoteId="qt-1" />)
    await waitFor(() => {
      expect(screen.getByText(/431\.25/)).toBeTruthy()
    })
  })
})
