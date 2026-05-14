import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

const mockGetInbox = vi.fn()
const mockMarkRead = vi.fn()

vi.mock('@/api/inbox', () => ({
  getInbox: (...args: unknown[]) => mockGetInbox(...args),
  markRead: (...args: unknown[]) => mockMarkRead(...args),
}))

// PullRefresh: pass-through wrapper so children render without gesture logic
vi.mock('@/components/gestures/PullRefresh', () => ({
  PullRefresh: ({ children }: { children: ReactNode }) => <div data-testid="pull-refresh">{children}</div>,
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

const mockNotifications = [
  {
    id: 'notif-1',
    category: 'email_failure',
    severity: 'error',
    title: 'Failed to email Invoice INV-0042',
    body: 'SMTP connection refused',
    link_url: '/invoices/inv-1',
    entity_type: 'invoice',
    entity_id: 'inv-1',
    metadata: {},
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(), // 5 min ago
    is_read: false,
    read_at: null,
  },
  {
    id: 'notif-2',
    category: 'stock_alert',
    severity: 'warning',
    title: 'Restock needed: Brake Pad #BP-04',
    body: 'Quantity required: 4. On hand: 0.',
    link_url: '/inventory?search=BP-04',
    entity_type: 'quote',
    entity_id: 'quote-1',
    metadata: {},
    created_at: new Date(Date.now() - 2 * 3600_000).toISOString(), // 2 hours ago
    is_read: true,
    read_at: new Date(Date.now() - 1 * 3600_000).toISOString(),
  },
  {
    id: 'notif-3',
    category: 'system',
    severity: 'info',
    title: 'New branch added: Auckland Central',
    body: null,
    link_url: null,
    entity_type: null,
    entity_id: null,
    metadata: {},
    created_at: new Date(Date.now() - 24 * 3600_000).toISOString(), // 1 day ago
    is_read: false,
    read_at: null,
  },
]

// ---------------------------------------------------------------------------
// Tests — NotificationsScreen
// ---------------------------------------------------------------------------

describe('NotificationsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockMarkRead.mockResolvedValue(true)
  })

  it('renders notification items when API returns data', async () => {
    mockGetInbox.mockResolvedValue({
      items: mockNotifications,
      total: 3,
      unread_count: 2,
    })

    const { default: NotificationsScreen } = await import('../NotificationsScreen')
    render(<NotificationsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Failed to email Invoice INV-0042')).toBeInTheDocument()
    })
    expect(screen.getByText('Restock needed: Brake Pad #BP-04')).toBeInTheDocument()
    expect(screen.getByText('New branch added: Auckland Central')).toBeInTheDocument()
  })

  it('filter chips change the active filter state', async () => {
    mockGetInbox.mockResolvedValue({
      items: mockNotifications,
      total: 3,
      unread_count: 2,
    })

    const user = userEvent.setup()
    const { default: NotificationsScreen } = await import('../NotificationsScreen')
    render(<NotificationsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Failed to email Invoice INV-0042')).toBeInTheDocument()
    })

    // Click the "Unread" filter chip
    const unreadChip = screen.getByTestId('filter-unread-unread')
    await user.click(unreadChip)

    // Verify getInbox was called again with unread_only param
    await waitFor(() => {
      const calls = mockGetInbox.mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toMatchObject({ unread_only: true })
    })

    // Click the "Error" severity filter chip
    const errorChip = screen.getByTestId('filter-severity-error')
    await user.click(errorChip)

    // Verify getInbox was called with severity param
    await waitFor(() => {
      const calls = mockGetInbox.mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[0]).toMatchObject({ severity: 'error' })
    })
  })

  it('tapping an item marks it as read', async () => {
    mockGetInbox.mockResolvedValue({
      items: mockNotifications,
      total: 3,
      unread_count: 2,
    })

    const user = userEvent.setup()
    const { default: NotificationsScreen } = await import('../NotificationsScreen')
    render(<NotificationsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Failed to email Invoice INV-0042')).toBeInTheDocument()
    })

    // Tap the first unread notification item
    const firstItem = screen.getByText('Failed to email Invoice INV-0042')
    await user.click(firstItem)

    // markRead should have been called with the notification id
    expect(mockMarkRead).toHaveBeenCalledWith('notif-1')
    // Should navigate to the link_url
    expect(mockNavigate).toHaveBeenCalledWith('/invoices/inv-1')
  })

  it('empty state shows "You\'re all caught up"', async () => {
    mockGetInbox.mockResolvedValue({
      items: [],
      total: 0,
      unread_count: 0,
    })

    const { default: NotificationsScreen } = await import('../NotificationsScreen')
    render(<NotificationsScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText("You're all caught up")).toBeInTheDocument()
    })
  })
})
