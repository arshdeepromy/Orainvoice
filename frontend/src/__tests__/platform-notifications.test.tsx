import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Task 48.9, 48.10, 48.11
 * - Notification banner display and dismissal
 * - Maintenance countdown display
 * - NotificationManager CRUD UI
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import PlatformNotificationBanner from '../components/common/PlatformNotificationBanner'
import NotificationManager from '../pages/admin/NotificationManager'

/* ── Mock data ── */

const mockActiveNotifications = {
  notifications: [
    {
      id: 'notif-1',
      notification_type: 'info',
      title: 'New Feature Available',
      message: 'Check out our new reporting dashboard.',
      severity: 'info',
      published_at: '2025-01-15T10:00:00Z',
      expires_at: '2025-02-15T10:00:00Z',
      maintenance_start: null,
      maintenance_end: null,
    },
    {
      id: 'notif-2',
      notification_type: 'maintenance',
      title: 'Scheduled Maintenance',
      message: 'System will be down for upgrades.',
      severity: 'warning',
      published_at: '2025-01-15T10:00:00Z',
      expires_at: '2025-12-31T23:59:59Z',
      maintenance_start: '2025-12-31T22:00:00Z',
      maintenance_end: '2025-12-31T23:59:59Z',
    },
  ],
}

const mockAdminNotifications = {
  notifications: [
    {
      id: 'admin-1',
      notification_type: 'alert',
      title: 'Security Update',
      message: 'Critical security patch applied.',
      severity: 'critical',
      target_type: 'all',
      target_value: null,
      scheduled_at: null,
      published_at: '2025-01-15T10:00:00Z',
      expires_at: null,
      maintenance_start: null,
      maintenance_end: null,
      is_active: true,
      created_by: 'user-1',
      created_at: '2025-01-15T09:00:00Z',
      updated_at: '2025-01-15T10:00:00Z',
    },
    {
      id: 'admin-2',
      notification_type: 'feature',
      title: 'Coming Soon: POS Module',
      message: 'POS module launching next month.',
      severity: 'info',
      target_type: 'country',
      target_value: '"NZ"',
      scheduled_at: '2025-02-01T00:00:00Z',
      published_at: null,
      expires_at: null,
      maintenance_start: null,
      maintenance_end: null,
      is_active: true,
      created_by: 'user-1',
      created_at: '2025-01-15T09:00:00Z',
      updated_at: '2025-01-15T09:00:00Z',
    },
  ],
  total: 2,
}

/* ── PlatformNotificationBanner Tests ── */

describe('PlatformNotificationBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when no notifications', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: { notifications: [] } })

    const { container } = render(<PlatformNotificationBanner />)
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/api/v2/notifications/active')
    })
    expect(container.querySelector('[data-testid="platform-notification-banner"]')).not.toBeInTheDocument()
  })

  it('renders notification banners for active notifications', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockActiveNotifications })

    render(<PlatformNotificationBanner />)
    await waitFor(() => {
      expect(screen.getByText('New Feature Available')).toBeInTheDocument()
    })
    expect(screen.getByText('Scheduled Maintenance')).toBeInTheDocument()
  })

  it('dismisses notification on click and calls API', async () => {
    const user = userEvent.setup()
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    const mockPost = apiClient.post as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockActiveNotifications })
    mockPost.mockResolvedValue({ data: { status: 'dismissed' } })

    render(<PlatformNotificationBanner />)
    await waitFor(() => {
      expect(screen.getByText('New Feature Available')).toBeInTheDocument()
    })

    const dismissBtn = screen.getByTestId('dismiss-btn-notif-1')
    await user.click(dismissBtn)

    expect(mockPost).toHaveBeenCalledWith('/api/v2/notifications/dismiss', {
      notification_id: 'notif-1',
    })
    // Notification should be removed from UI
    expect(screen.queryByText('New Feature Available')).not.toBeInTheDocument()
  })

  it('displays maintenance countdown for maintenance notifications', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockActiveNotifications })

    render(<PlatformNotificationBanner />)
    await waitFor(() => {
      expect(screen.getByText('Scheduled Maintenance')).toBeInTheDocument()
    })
    // Maintenance notification should have countdown element
    expect(screen.getByTestId('maintenance-countdown')).toBeInTheDocument()
  })

  it('renders correct severity styling', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockActiveNotifications })

    render(<PlatformNotificationBanner />)
    await waitFor(() => {
      expect(screen.getByTestId('notification-banner-notif-1')).toBeInTheDocument()
    })

    // Info notification should have blue styling
    const infoBanner = screen.getByTestId('notification-banner-notif-1')
    expect(infoBanner.className).toContain('bg-blue-50')

    // Warning notification should have yellow styling
    const warningBanner = screen.getByTestId('notification-banner-notif-2')
    expect(warningBanner.className).toContain('bg-yellow-50')
  })

  it('has proper accessibility attributes', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockActiveNotifications })

    render(<PlatformNotificationBanner />)
    await waitFor(() => {
      expect(screen.getByRole('region', { name: 'Platform notifications' })).toBeInTheDocument()
    })
    // Each banner should have role="alert"
    const alerts = screen.getAllByRole('alert')
    expect(alerts.length).toBe(2)
  })

  it('handles API error gracefully', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockRejectedValue(new Error('Network error'))

    const { container } = render(<PlatformNotificationBanner />)
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalled()
    })
    // Should not crash — renders nothing
    expect(container.querySelector('[data-testid="platform-notification-banner"]')).not.toBeInTheDocument()
  })
})

/* ── NotificationManager Tests ── */

describe('NotificationManager', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders notification list from API', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockAdminNotifications })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByText('Security Update')).toBeInTheDocument()
    })
    expect(screen.getByText('Coming Soon: POS Module')).toBeInTheDocument()
  })

  it('shows empty state when no notifications', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: { notifications: [], total: 0 } })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    })
  })

  it('opens create form when clicking Create button', async () => {
    const user = userEvent.setup()
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: { notifications: [], total: 0 } })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByTestId('create-notification-btn')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('create-notification-btn'))
    expect(screen.getByTestId('notification-form')).toBeInTheDocument()
    expect(screen.getByTestId('title-input')).toBeInTheDocument()
    expect(screen.getByTestId('message-input')).toBeInTheDocument()
  })

  it('submits create form and refreshes list', async () => {
    const user = userEvent.setup()
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    const mockPost = apiClient.post as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: { notifications: [], total: 0 } })
    mockPost.mockResolvedValue({ data: { id: 'new-1', title: 'Test' } })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByTestId('create-notification-btn')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('create-notification-btn'))
    await user.type(screen.getByTestId('title-input'), 'Test Notification')
    await user.type(screen.getByTestId('message-input'), 'Test message body')
    await user.click(screen.getByTestId('submit-btn'))

    expect(mockPost).toHaveBeenCalledWith(
      '/api/v2/admin/notifications',
      expect.objectContaining({
        title: 'Test Notification',
        message: 'Test message body',
        notification_type: 'info',
        severity: 'info',
        target_type: 'all',
      }),
    )
  })

  it('shows target value input when target type is not all', async () => {
    const user = userEvent.setup()
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: { notifications: [], total: 0 } })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByTestId('create-notification-btn')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('create-notification-btn'))

    // Initially target_type is 'all', so no target_value input
    expect(screen.queryByTestId('target-value-input')).not.toBeInTheDocument()

    // Change to 'country'
    await user.selectOptions(screen.getByTestId('target-type-select'), 'country')
    expect(screen.getByTestId('target-value-input')).toBeInTheDocument()
  })

  it('shows maintenance fields when type is maintenance', async () => {
    const user = userEvent.setup()
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: { notifications: [], total: 0 } })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByTestId('create-notification-btn')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('create-notification-btn'))

    // Initially no maintenance fields
    expect(screen.queryByTestId('maintenance-start-input')).not.toBeInTheDocument()

    // Change type to maintenance
    await user.selectOptions(screen.getByTestId('type-select'), 'maintenance')
    expect(screen.getByTestId('maintenance-start-input')).toBeInTheDocument()
    expect(screen.getByTestId('maintenance-end-input')).toBeInTheDocument()
  })

  it('displays severity and type badges correctly', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockAdminNotifications })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByText('Security Update')).toBeInTheDocument()
    })

    // Check badges exist
    expect(screen.getByText('alert')).toBeInTheDocument()
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('feature')).toBeInTheDocument()
  })

  it('shows publish button for unpublished notifications', async () => {
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: mockAdminNotifications })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByText('Coming Soon: POS Module')).toBeInTheDocument()
    })

    // admin-2 is unpublished (published_at is null), should have publish button
    expect(screen.getByTestId('publish-btn-admin-2')).toBeInTheDocument()
    // admin-1 is published, should NOT have publish button
    expect(screen.queryByTestId('publish-btn-admin-1')).not.toBeInTheDocument()
  })

  it('cancels form and hides it', async () => {
    const user = userEvent.setup()
    const mockGet = apiClient.get as ReturnType<typeof vi.fn>
    mockGet.mockResolvedValue({ data: { notifications: [], total: 0 } })

    render(<NotificationManager />)
    await waitFor(() => {
      expect(screen.getByTestId('create-notification-btn')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('create-notification-btn'))
    expect(screen.getByTestId('notification-form')).toBeInTheDocument()

    await user.click(screen.getByTestId('cancel-btn'))
    expect(screen.queryByTestId('notification-form')).not.toBeInTheDocument()
  })
})
