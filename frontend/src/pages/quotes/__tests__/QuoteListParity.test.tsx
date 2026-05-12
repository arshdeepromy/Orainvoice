/**
 * Component tests for QuoteList parity features (Tasks 19.1, 19.2, 19.6, 19.7).
 * - CP-6: Attachment badge visibility
 * - CP-7: No "Print POS Receipt" menu item
 * - PDF download action
 * - Print quote action
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'

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
}))

vi.mock('../../../contexts/BranchContext', () => ({
  useBranch: () => ({ branches: [], selectedBranchId: null }),
}))

import apiClient from '../../../api/client'
import QuoteList from '../QuoteList'

// ─── Fixtures ────────────────────────────────────────────────────────────────

function makeQuote(overrides: Record<string, unknown> = {}) {
  return {
    id: 'q-1',
    quote_number: 'QT-0001',
    customer_name: 'John Doe',
    vehicle_rego: 'ABC123',
    status: 'draft',
    total: '115.00',
    valid_until: '2026-12-31',
    created_at: '2026-05-12T10:00:00Z',
    branch_id: null,
    attachment_count: 0,
    ...overrides,
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function setupApiResponse(quotes: Record<string, unknown>[]) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { quotes, total: quotes.length },
  })
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('QuoteList — Attachment Badge (CP-6)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(cleanup)

  it('shows 📎 badge when attachment_count > 0', async () => {
    setupApiResponse([makeQuote({ id: 'q-1', attachment_count: 3 })])
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText('📎 3')).toBeTruthy()
    })
  })

  it('does not show 📎 badge when attachment_count is 0', async () => {
    setupApiResponse([makeQuote({ id: 'q-2', attachment_count: 0 })])
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText('QT-0001')).toBeTruthy()
    })
    expect(screen.queryByText(/📎/)).toBeNull()
  })

  it('does not show 📎 badge when attachment_count is null/undefined', async () => {
    setupApiResponse([makeQuote({ id: 'q-3', attachment_count: undefined })])
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText('QT-0001')).toBeTruthy()
    })
    expect(screen.queryByText(/📎/)).toBeNull()
  })
})

describe('QuoteList — No POS Receipt (CP-7)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(cleanup)

  it('never renders a "Print POS Receipt" menu item', async () => {
    setupApiResponse([makeQuote({ id: 'q-4', status: 'draft' })])
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText('QT-0001')).toBeTruthy()
    })
    // Assert no element matches /print pos receipt/i anywhere in the document
    const allText = document.body.textContent ?? ''
    expect(allText.toLowerCase()).not.toContain('print pos receipt')
  })

  it('renders "PDF" and "Print" buttons', async () => {
    setupApiResponse([makeQuote({ id: 'q-5' })])
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText('QT-0001')).toBeTruthy()
    })
    expect(screen.getByTitle('Download PDF')).toBeTruthy()
    expect(screen.getByTitle('Print Quote')).toBeTruthy()
  })
})

describe('QuoteList — PDF Download (Task 19.6)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(cleanup)

  it('calls apiClient.get with /quotes/{id}/pdf and responseType blob on PDF click', async () => {
    setupApiResponse([makeQuote({ id: 'q-pdf-1', quote_number: 'QT-0099' })])
    const mockBlob = new Blob(['fake-pdf'], { type: 'application/pdf' })
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: Record<string, unknown>) => {
      if (url === '/quotes/q-pdf-1/pdf') {
        return Promise.resolve({ data: mockBlob })
      }
      return Promise.resolve({ data: { quotes: [makeQuote({ id: 'q-pdf-1', quote_number: 'QT-0099' })], total: 1 } })
    })

    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText('QT-0099')).toBeTruthy()
    })

    const pdfBtn = screen.getByTitle('Download PDF')
    fireEvent.click(pdfBtn)

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith('/quotes/q-pdf-1/pdf', { responseType: 'blob' })
    })
  })
})

describe('QuoteList — Print Quote (Task 19.7)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(cleanup)

  it('navigates to /quotes/{id}?print=1 on Print click', async () => {
    setupApiResponse([makeQuote({ id: 'q-print-1' })])
    render(<QuoteList />)
    await waitFor(() => {
      expect(screen.getByText('QT-0001')).toBeTruthy()
    })

    const printBtn = screen.getByTitle('Print Quote')
    fireEvent.click(printBtn)

    expect(mockNavigate).toHaveBeenCalledWith('/quotes/q-print-1?print=1')
  })
})
