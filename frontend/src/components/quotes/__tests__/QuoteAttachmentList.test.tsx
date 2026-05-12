/**
 * Component tests for QuoteAttachmentList (Tasks 19.4, 19.5).
 * - Delete affordance only when isDraft=true
 * - No delete button when isDraft=false
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '@testing-library/react'

// ─── Mocks ───────────────────────────────────────────────────────────────────

vi.mock('../../../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import apiClient from '../../../api/client'
import QuoteAttachmentList from '../QuoteAttachmentList'

// ─── Fixtures ────────────────────────────────────────────────────────────────

const mockAttachments = [
  { id: 'att-1', file_name: 'photo.jpg', file_size: 1024, mime_type: 'image/jpeg', created_at: '2026-05-12T10:00:00Z' },
  { id: 'att-2', file_name: 'invoice.pdf', file_size: 2048, mime_type: 'application/pdf', created_at: '2026-05-12T11:00:00Z' },
]

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('QuoteAttachmentList — Delete Affordance (Task 19.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { attachments: mockAttachments, total: 2 },
    })
  })
  afterEach(cleanup)

  it('renders delete buttons when isDraft=true', async () => {
    render(<QuoteAttachmentList quoteId="q-1" isDraft={true} />)
    await waitFor(() => {
      expect(screen.getByText('photo.jpg')).toBeTruthy()
    })
    // Should have delete buttons (× characters)
    const deleteButtons = screen.getAllByTitle('Delete attachment')
    expect(deleteButtons.length).toBe(2)
  })

  it('does not render delete buttons when isDraft=false', async () => {
    render(<QuoteAttachmentList quoteId="q-1" isDraft={false} />)
    await waitFor(() => {
      expect(screen.getByText('photo.jpg')).toBeTruthy()
    })
    // Should NOT have delete buttons
    expect(screen.queryAllByTitle('Delete attachment').length).toBe(0)
  })
})

describe('QuoteAttachmentList — Conditional Mount (Task 19.5)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(cleanup)

  it('returns null when no attachments are returned', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { attachments: [], total: 0 },
    })
    const { container } = render(<QuoteAttachmentList quoteId="q-empty" isDraft={true} />)
    await waitFor(() => {
      // Component should render nothing when empty
      expect(container.innerHTML).toBe('')
    })
  })

  it('renders attachment list when attachments exist', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { attachments: mockAttachments, total: 2 },
    })
    render(<QuoteAttachmentList quoteId="q-1" isDraft={true} />)
    await waitFor(() => {
      expect(screen.getByText('photo.jpg')).toBeTruthy()
      expect(screen.getByText('invoice.pdf')).toBeTruthy()
    })
    // Verify the count is shown
    expect(screen.getByText('(2)')).toBeTruthy()
  })

  it('calls GET /quotes/{id}/attachments on mount', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { attachments: [], total: 0 },
    })
    render(<QuoteAttachmentList quoteId="q-fetch-test" isDraft={true} />)
    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/quotes/q-fetch-test/attachments',
        expect.objectContaining({ signal: expect.any(AbortSignal) })
      )
    })
  })
})
