import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements AC-2, AC-5
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

vi.mock('@/components/ui/Spinner', () => ({
  Spinner: ({ label }: { label?: string }) => (
    <div data-testid="spinner">{label ?? 'Loading...'}</div>
  ),
}))

// Mock InboxBellBadge to avoid its polling side effects in dropdown tests
vi.mock('./InboxBellBadge', () => ({
  default: () => <span data-testid="badge-mock" />,
}))

import apiClient from '@/api/client'
import InboxBellDropdown from './InboxBellDropdown'

function mockInboxResponse(items: Array<Record<string, unknown>> = []) {
  return {
    data: {
      items,
      total: items.length,
      unread_count: items.filter((i) => !i.is_read).length,
    },
  }
}

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

describe('InboxBellDropdown', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: unread-count returns 0 (for badge mock), inbox returns items
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('unread-count')) {
        return Promise.resolve({ data: { count: 2 } })
      }
      return Promise.resolve(mockInboxResponse(sampleItems))
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  })

  it('fetches inbox items when the dropdown is opened', async () => {
    const user = userEvent.setup()
    render(<InboxBellDropdown />)

    const bellButton = screen.getByRole('button', { name: 'Notifications' })
    await user.click(bellButton)

    expect(await screen.findByText('Email failed: Invoice INV-001')).toBeInTheDocument()
    expect(screen.getByText('Restock needed: Brake Pad')).toBeInTheDocument()
    expect(apiClient.get).toHaveBeenCalledWith(
      '/notifications/inbox?limit=10',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('clicking an item with link_url calls mark-read and navigates', async () => {
    const user = userEvent.setup()
    render(<InboxBellDropdown />)

    // Open dropdown
    await user.click(screen.getByRole('button', { name: 'Notifications' }))
    await screen.findByText('Email failed: Invoice INV-001')

    // Click the item with link_url
    await user.click(screen.getByText('Email failed: Invoice INV-001'))

    expect(apiClient.post).toHaveBeenCalledWith('/notifications/inbox/notif-1/read')
    expect(mockNavigate).toHaveBeenCalledWith('/invoices/inv-001')
  })

  it('"Mark all as read" button calls the mark-all-read API', async () => {
    const user = userEvent.setup()
    render(<InboxBellDropdown />)

    // Open dropdown
    await user.click(screen.getByRole('button', { name: 'Notifications' }))
    await screen.findByText('Email failed: Invoice INV-001')

    // Click "Mark all as read"
    await user.click(screen.getByRole('button', { name: 'Mark all as read' }))

    expect(apiClient.post).toHaveBeenCalledWith('/notifications/inbox/mark-all-read')
  })

  it('shows "No new notifications" when inbox is empty', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('unread-count')) {
        return Promise.resolve({ data: { count: 0 } })
      }
      return Promise.resolve(mockInboxResponse([]))
    })

    const user = userEvent.setup()
    render(<InboxBellDropdown />)

    await user.click(screen.getByRole('button', { name: 'Notifications' }))

    expect(await screen.findByText('No new notifications')).toBeInTheDocument()
  })
})
