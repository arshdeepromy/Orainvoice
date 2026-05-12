/**
 * Unit/component tests for QuoteDetail — PDF download, Print, and Copy Link features.
 * Validates Requirements 2, 3, 4, 5, 6 from the quote-pdf-print spec.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react'

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
    id: 'q-123',
    org_id: 'org-1',
    customer_id: 'cust-1',
    quote_number: 'QUO-0001',
    vehicle_rego: 'ABC123',
    vehicle_make: 'Toyota',
    vehicle_model: 'Hilux',
    vehicle_year: 2020,
    project_id: null,
    status: 'draft',
    valid_until: '2025-12-31',
    subtotal: '100.00',
    gst_amount: '15.00',
    total: '115.00',
    discount_type: null,
    discount_value: '0',
    discount_amount: '0',
    shipping_charges: '0',
    adjustment: '0',
    notes: null,
    terms: null,
    subject: 'Test Quote',
    acceptance_token: null,
    converted_invoice_id: null,
    line_items: [
      {
        id: 'li-1',
        item_type: 'parts',
        description: 'Brake pads',
        quantity: 2,
        unit_price: '50.00',
        hours: null,
        hourly_rate: null,
        is_gst_exempt: false,
        warranty_note: null,
        line_total: '100.00',
        sort_order: 1,
        catalogue_item_id: null,
        stock_item_id: null,
        gst_inclusive: false,
        inclusive_price: null,
        tax_rate: '15',
      },
    ],
    created_by: 'user-1',
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
    order_number: null,
    salesperson_id: null,
    salesperson_name: null,
    additional_vehicles: [],
    fluid_usage: [],
    attachment_count: 0,
    ...overrides,
  }
}

const STATUSES = ['draft', 'sent', 'accepted', 'declined', 'expired', 'converted'] as const

function fixtureForStatus(status: string) {
  const overrides: Record<string, unknown> = { status }
  if (status === 'sent' || status === 'accepted') {
    overrides.acceptance_token = 'tok_abc'
  }
  if (status === 'converted') {
    overrides.converted_invoice_id = 'inv-99'
    overrides.acceptance_token = 'tok_abc'
  }
  return makeQuote(overrides)
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mockFetchQuote(quote: ReturnType<typeof makeQuote>) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === `/quotes/${quote.id}`) {
      return Promise.resolve({ data: quote })
    }
    // Default: resolve empty for other calls
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
  // Provide a default clipboard mock
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  })
})

afterEach(() => {
  cleanup()
  // Remove any lingering print style tags
  document.querySelectorAll('style[data-quote-print="true"]').forEach((el) => el.remove())
})

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('QuoteDetail — PDF / Print / Copy Link', () => {
  // 8.1 Print button renders on every status
  describe('8.1 Print button renders on every status', () => {
    it.each(STATUSES)('renders Print button when status is %s', async (status) => {
      const quote = fixtureForStatus(status)
      await renderWithQuote(quote)
      expect(screen.getByText('Print')).toBeInTheDocument()
    })
  })

  // 8.2 Download PDF button renders on every status
  describe('8.2 Download PDF button renders on every status', () => {
    it.each(STATUSES)('renders Download PDF button when status is %s', async (status) => {
      const quote = fixtureForStatus(status)
      await renderWithQuote(quote)
      expect(screen.getByText('Download PDF')).toBeInTheDocument()
    })
  })

  // 8.3 Copy Link conditional visibility
  describe('8.3 Copy Link conditional visibility', () => {
    it('does not render Copy Link when acceptance_token is null', async () => {
      const quote = makeQuote({ status: 'draft', acceptance_token: null })
      await renderWithQuote(quote)
      expect(screen.queryByText('Copy Link')).not.toBeInTheDocument()
    })

    it('renders Copy Link when acceptance_token is present', async () => {
      const quote = makeQuote({ status: 'sent', acceptance_token: 'abc' })
      await renderWithQuote(quote)
      expect(screen.getByText('Copy Link')).toBeInTheDocument()
    })
  })

  // 8.4 Clicking Download PDF calls the correct endpoint
  describe('8.4 Clicking Download PDF calls the correct endpoint', () => {
    it('calls apiClient.get with /quotes/{id}/pdf and responseType blob', async () => {
      const quote = makeQuote({ status: 'sent', acceptance_token: 'tok' })
      const blob = new Blob(['%PDF-'], { type: 'application/pdf' })
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: any) => {
        if (url === `/quotes/${quote.id}`) {
          return Promise.resolve({ data: quote })
        }
        if (url === `/quotes/${quote.id}/pdf`) {
          return Promise.resolve({ data: blob })
        }
        return Promise.resolve({ data: {} })
      })

      await renderWithQuote(quote)

      // Reset mock call tracking after initial fetch
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockClear()
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: any) => {
        if (url === `/quotes/${quote.id}/pdf`) {
          return Promise.resolve({ data: blob })
        }
        return Promise.resolve({ data: {} })
      })

      await act(async () => {
        fireEvent.click(screen.getByText('Download PDF'))
      })

      expect(apiClient.get).toHaveBeenCalledWith(`/quotes/${quote.id}/pdf`, { responseType: 'blob' })
    })
  })

  // 8.5 downloading state flips the label
  describe('8.5 downloading state flips label during fetch', () => {
    it('shows Downloading… and disabled while fetch is pending, then reverts', async () => {
      const quote = makeQuote({ status: 'draft' })
      let resolveDownload!: (value: unknown) => void
      const downloadPromise = new Promise((resolve) => {
        resolveDownload = resolve
      })

      ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url === `/quotes/${quote.id}`) {
          return Promise.resolve({ data: quote })
        }
        if (url === `/quotes/${quote.id}/pdf`) {
          return downloadPromise
        }
        return Promise.resolve({ data: {} })
      })

      await act(async () => {
        render(<QuoteDetail quoteId={quote.id as string} />)
      })

      // Click Download PDF — starts the never-resolving fetch
      // Use fireEvent without wrapping in act so the pending promise keeps the state mid-flight
      fireEvent.click(screen.getByText('Download PDF'))

      // Allow microtask for setDownloading(true) to flush
      await act(async () => {
        await Promise.resolve()
      })

      // Should now show "Downloading…" and be disabled
      const downloadingBtn = screen.getByText('Downloading…')
      expect(downloadingBtn).toBeInTheDocument()
      expect(downloadingBtn.closest('button')).toBeDisabled()

      // Resolve the download
      const blob = new Blob(['%PDF-'], { type: 'application/pdf' })
      await act(async () => {
        resolveDownload({ data: blob })
      })

      // Should revert to "Download PDF"
      await waitFor(() => {
        expect(screen.getByText('Download PDF')).toBeInTheDocument()
      })
    })
  })

  // 8.6 API failure renders error banner
  describe('8.6 API failure renders error banner', () => {
    it('shows error banner on 500 response', async () => {
      const quote = makeQuote({ status: 'sent', acceptance_token: 'tok' })

      ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url === `/quotes/${quote.id}`) {
          return Promise.resolve({ data: quote })
        }
        if (url === `/quotes/${quote.id}/pdf`) {
          return Promise.reject({ response: { status: 500 } })
        }
        return Promise.resolve({ data: {} })
      })

      await renderWithQuote(quote)

      await act(async () => {
        fireEvent.click(screen.getByText('Download PDF'))
      })

      await waitFor(() => {
        expect(screen.getByText('Failed to download PDF. Please try again.')).toBeInTheDocument()
      })
    })

    it('shows error banner on network failure (no response object)', async () => {
      const quote = makeQuote({ status: 'draft' })

      ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url === `/quotes/${quote.id}`) {
          return Promise.resolve({ data: quote })
        }
        if (url === `/quotes/${quote.id}/pdf`) {
          return Promise.reject(new Error('Network Error'))
        }
        return Promise.resolve({ data: {} })
      })

      await renderWithQuote(quote)

      await act(async () => {
        fireEvent.click(screen.getByText('Download PDF'))
      })

      await waitFor(() => {
        expect(screen.getByText('Failed to download PDF. Please try again.')).toBeInTheDocument()
      })
    })
  })

  // 8.7 Print style tag present after mount
  describe('8.7 Print style tag is present after mount', () => {
    it('injects exactly one style[data-quote-print="true"] into document.head', async () => {
      const quote = makeQuote({ status: 'draft' })
      await renderWithQuote(quote)

      const styleTags = document.querySelectorAll('style[data-quote-print="true"]')
      expect(styleTags.length).toBe(1)
    })
  })

  // 8.8 Print style tag removed after unmount (including mid-download)
  describe('8.8 Print style tag removed after unmount', () => {
    it('removes style tag on unmount even during a pending download', async () => {
      const quote = makeQuote({ status: 'draft' })
      const downloadPromise = new Promise(() => {}) // never resolves

      ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url === `/quotes/${quote.id}`) {
          return Promise.resolve({ data: quote })
        }
        if (url === `/quotes/${quote.id}/pdf`) {
          return downloadPromise
        }
        return Promise.resolve({ data: {} })
      })

      let unmountFn: () => void
      await act(async () => {
        const { unmount } = render(<QuoteDetail quoteId={quote.id as string} />)
        unmountFn = unmount
      })

      // Style tag should be present
      expect(document.querySelectorAll('style[data-quote-print="true"]').length).toBe(1)

      // Start a download (never resolves)
      await act(async () => {
        fireEvent.click(screen.getByText('Download PDF'))
      })

      // Style tag still present during download
      expect(document.querySelectorAll('style[data-quote-print="true"]').length).toBe(1)

      // Unmount
      act(() => {
        unmountFn!()
      })

      // Style tag should be gone
      expect(document.querySelectorAll('style[data-quote-print="true"]').length).toBe(0)
    })
  })

  // 8.9 Copy Link click writes exact URL
  describe('8.9 Copy Link writes exact URL to clipboard', () => {
    it('calls navigator.clipboard.writeText with the correct share URL', async () => {
      const quote = makeQuote({ status: 'sent', acceptance_token: 'tok_xyz' })
      await renderWithQuote(quote)

      await act(async () => {
        fireEvent.click(screen.getByText('Copy Link'))
      })

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        `${window.location.origin}/api/v1/public/quotes/view/tok_xyz`
      )
    })
  })

  // 8.10 Copied label flips for 2s then reverts
  describe('8.10 Copied label flips for 2s', () => {
    it('shows Copied! then reverts to Copy Link after 2000ms', async () => {
      vi.useFakeTimers()

      const quote = makeQuote({ status: 'sent', acceptance_token: 'tok_abc' })
      await renderWithQuote(quote)

      await act(async () => {
        fireEvent.click(screen.getByText('Copy Link'))
      })

      // Should show "Copied!"
      expect(screen.getByText('Copied!')).toBeInTheDocument()
      expect(screen.queryByText('Copy Link')).not.toBeInTheDocument()

      // Advance timers by 2000ms
      await act(async () => {
        vi.advanceTimersByTime(2000)
      })

      // Should revert to "Copy Link"
      expect(screen.getByText('Copy Link')).toBeInTheDocument()
      expect(screen.queryByText('Copied!')).not.toBeInTheDocument()

      vi.useRealTimers()
    })
  })

  // 8.11 Clipboard rejection shows banner
  describe('8.11 Clipboard rejection shows banner', () => {
    it('shows error banner and no Copied! label when clipboard rejects', async () => {
      const quote = makeQuote({ status: 'sent', acceptance_token: 'tok_fail' })

      Object.assign(navigator, {
        clipboard: {
          writeText: vi.fn().mockRejectedValue(new Error('Permission denied')),
        },
      })

      await renderWithQuote(quote)

      await act(async () => {
        fireEvent.click(screen.getByText('Copy Link'))
      })

      await waitFor(() => {
        expect(
          screen.getByText('Could not copy link to clipboard. Please copy manually.')
        ).toBeInTheDocument()
      })

      // "Copied!" should never appear
      expect(screen.queryByText('Copied!')).not.toBeInTheDocument()
    })
  })
})
