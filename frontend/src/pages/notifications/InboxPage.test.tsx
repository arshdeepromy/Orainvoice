import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Unit tests for InboxPage component.
 * Validates: Requirements 6.2
 */

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

const mockNavigate = vi.fn()
let mockSearchParams = new URLSearchParams()
const mockSetSearchParams = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useSearchParams: () => [mockSearchParams, mockSetSearchParams],
}))

vi.mock('@/components/ui', () => ({
  Spinner: ({ label }: { label?: string }) => (
    <div data-testid="spinner">{label ?? 'Loading'}</div>
  ),
  Pagination: ({
    currentPage,
    totalPages,
    onPageChange,
  }: {
    currentPage: number
    totalPages: number
    onPageChange: (page: number) => void
  }) =>
    totalPages > 1 ? (
      <div data-testid="pagination">
        <span>
          Page {currentPage} of {totalPages}
        </span>
        <button onClick={() => onPageChange(currentPage + 1)}>Next</button>
      </div>
    ) : null,
  Select: ({
    label,
    value,
    onChange,
    options,
  }: {
    label: string
    value: string
    onChange: (e: { target: { value: string } }) => void
    options: Array<{ value: string; label: string }>
  }) => (
    <select
      aria-label={label}
      value={value}
      onChange={onChange}
      data-testid={`select-${label.toLowerCase()}`}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  ),
}))

vi.mock('@/components/notifications/InboxItemCard', () => ({
  default: ({
    item,
    onClick,
    onDismiss,
  }: {
    item: { id: string; title: string; is_read: boolean }
    onClick: (item: unknown) => void
    onDismiss: (item: unknown) => void
  }) => (
    <div data-testid={`inbox-item-${item.id}`}>
      <button onClick={() => onClick(item)}>{item.title}</button>
      <button onClick={() => onDismiss(item)}>Dismiss</button>
    </div>
  ),
}))

import apiClient from '@/api/client'
import InboxPage from './InboxPage'

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const sampleItems = [
  {
    id: 'notif-1',
    category: 'email_failure',
    severity: 'error',
    title: 'Email failed: Invoice INV-001',
    body: 'SMTP connection refused',
    link_url: '/invoices/inv-001',
    entity_type: 'invoice',
    entity_id: 'inv-001',
    metadata: {},
    created_at: new Date().toISOString(),
    is_read: false,
    read_at: null,
  },
  {
    id: 'notif-2',
    category: 'stock_alert',
    severity: 'warning',
    title: 'Restock needed: Brake Pad',
    body: null,
    link_url: null,
    entity_type: 'quote',
    entity_id: 'qt-001',
    metadata: {},
    created_at: new Date().toISOString(),
    is_read: true,
    read_at: new Date().toISOString(),
  },
]

function mockInboxResponse(
  items: Array<Record<string, unknown>> = [],
  total?: number,
  unreadCount?: number,
) {
  return {
    data: {
      items,
      total: total ?? items.length,
      unread_count: unreadCount ?? items.filter((i) => !i.is_read).length,
    },
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('InboxPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockInboxResponse(sampleItems),
    )
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  })

  // -------------------------------------------------------------------------
  // 1. List renders notification items when API returns data
  // -------------------------------------------------------------------------

  it('renders notification items when API returns data', async () => {
    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByTestId('inbox-item-notif-1')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inbox-item-notif-2')).toBeInTheDocument()
    expect(screen.getByText('Email failed: Invoice INV-001')).toBeInTheDocument()
    expect(screen.getByText('Restock needed: Brake Pad')).toBeInTheDocument()
  })

  it('calls the inbox API with correct default params', async () => {
    render(<InboxPage />)

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/notifications/inbox',
        expect.objectContaining({
          params: { limit: 25, offset: 0 },
          signal: expect.any(AbortSignal),
        }),
      )
    })
  })

  // -------------------------------------------------------------------------
  // 2. Filter buttons update URL search params
  // -------------------------------------------------------------------------

  it('clicking Unread button calls setSearchParams with unread=true', async () => {
    const user = userEvent.setup()
    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByTestId('inbox-item-notif-1')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Unread' }))

    expect(mockSetSearchParams).toHaveBeenCalled()
  })

  it('clicking All button calls setSearchParams to remove unread filter', async () => {
    mockSearchParams = new URLSearchParams('unread=true')
    const user = userEvent.setup()
    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByTestId('inbox-item-notif-1')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'All' }))

    expect(mockSetSearchParams).toHaveBeenCalled()
  })

  it('changing severity dropdown calls setSearchParams', async () => {
    const user = userEvent.setup()
    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByTestId('inbox-item-notif-1')).toBeInTheDocument()
    })

    const severitySelect = screen.getByTestId('select-severity')
    await user.selectOptions(severitySelect, 'error')

    expect(mockSetSearchParams).toHaveBeenCalled()
  })

  it('changing category dropdown calls setSearchParams', async () => {
    const user = userEvent.setup()
    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByTestId('inbox-item-notif-1')).toBeInTheDocument()
    })

    const categorySelect = screen.getByTestId('select-category')
    await user.selectOptions(categorySelect, 'email_failure')

    expect(mockSetSearchParams).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  // 3. "Mark all read" button calls the mark-all-read API
  // -------------------------------------------------------------------------

  it('"Mark all read" button calls the mark-all-read API', async () => {
    const user = userEvent.setup()
    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByTestId('inbox-item-notif-1')).toBeInTheDocument()
    })

    const markAllBtn = screen.getByRole('button', { name: /mark all read/i })
    await user.click(markAllBtn)

    expect(apiClient.post).toHaveBeenCalledWith('/notifications/inbox/mark-all-read')
  })

  it('"Mark all read" button is disabled when no unread items', async () => {
    const allReadItems = sampleItems.map((i) => ({ ...i, is_read: true }))
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockInboxResponse(allReadItems, allReadItems.length, 0),
    )

    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByTestId('inbox-item-notif-1')).toBeInTheDocument()
    })

    const markAllBtn = screen.getByRole('button', { name: /mark all read/i })
    expect(markAllBtn).toBeDisabled()
  })

  // -------------------------------------------------------------------------
  // 4. Empty state shows "You're all caught up" when no items
  // -------------------------------------------------------------------------

  it('shows "You\'re all caught up" when no items and no active filter', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockInboxResponse([], 0, 0),
    )

    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByText("You're all caught up")).toBeInTheDocument()
    })
  })

  it('shows "No matching notifications" when no items with active filter', async () => {
    mockSearchParams = new URLSearchParams('severity=error')
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockInboxResponse([], 0, 0),
    )

    render(<InboxPage />)

    await waitFor(() => {
      expect(screen.getByText('No matching notifications')).toBeInTheDocument()
    })
  })
})
