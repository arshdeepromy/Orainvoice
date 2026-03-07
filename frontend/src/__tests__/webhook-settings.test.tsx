import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 70.1-70.4
 * - 70.1: Configure webhook URLs for events (invoice.created, invoice.paid, invoice.overdue, payment.received, customer.created, vehicle.added)
 * - 70.2: HTTP POST with JSON payload on configured events
 * - 70.3: Webhook payload signing with shared secret
 * - 70.4: Retry up to 3 times with exponential backoff, log failures
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
import { WebhookSettings } from '../pages/settings/WebhookSettings'
import type { Webhook, WebhookDelivery } from '../pages/settings/WebhookSettings'

const mockWebhooks: Webhook[] = [
  {
    id: 'wh-1',
    url: 'https://example.com/hook1',
    event_types: ['invoice.created', 'invoice.paid'],
    is_active: true,
    secret: 'whsec_abc123',
    created_at: '2025-01-15T10:00:00Z',
  },
  {
    id: 'wh-2',
    url: 'https://example.com/hook2',
    event_types: ['customer.created'],
    is_active: false,
    secret: 'whsec_def456',
    created_at: '2025-01-10T08:00:00Z',
  },
]

const mockDeliveries: WebhookDelivery[] = [
  {
    id: 'del-1',
    webhook_id: 'wh-1',
    event_type: 'invoice.created',
    status: 'success',
    response_code: 200,
    attempt: 1,
    delivered_at: '2025-01-20T14:00:00Z',
  },
  {
    id: 'del-2',
    webhook_id: 'wh-1',
    event_type: 'invoice.paid',
    status: 'failed',
    response_code: 500,
    attempt: 3,
    delivered_at: '2025-01-20T14:05:00Z',
  },
]

function setupMocks(overrides: {
  webhooks?: Webhook[]
  deliveries?: WebhookDelivery[]
} = {}) {
  const webhooks = overrides.webhooks ?? mockWebhooks
  const deliveries = overrides.deliveries ?? mockDeliveries

  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/webhooks') return Promise.resolve({ data: webhooks })
    if (url === '/webhooks/deliveries') return Promise.resolve({ data: deliveries })
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'wh-new' } })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
}

describe('Webhook settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<WebhookSettings />)
    expect(screen.getByRole('status', { name: 'Loading webhook settings' })).toBeInTheDocument()
  })

  it('shows error banner when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<WebhookSettings />)
    expect(await screen.findByText(/couldn't load your webhook settings/i)).toBeInTheDocument()
  })

  // 70.1: Webhook list displays configured webhooks with URL, events, status
  it('displays webhook list with URL, event types, and status', async () => {
    setupMocks()
    render(<WebhookSettings />)
    expect(await screen.findByText('https://example.com/hook1')).toBeInTheDocument()
    expect(screen.getByText('https://example.com/hook2')).toBeInTheDocument()
    expect(screen.getByText('invoice.created')).toBeInTheDocument()
    expect(screen.getByText('invoice.paid')).toBeInTheDocument()
    expect(screen.getByText('customer.created')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  // 70.1: Edit and delete actions on webhook list
  it('shows edit and delete buttons for each webhook', async () => {
    setupMocks()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    expect(editButtons).toHaveLength(2)
    expect(deleteButtons).toHaveLength(2)
  })

  // 70.1: Create webhook modal with event type multi-select
  it('opens create webhook modal with event type checkboxes', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    expect(screen.getByText('Create webhook', { selector: 'h2' })).toBeInTheDocument()
    expect(screen.getByLabelText('Webhook URL')).toBeInTheDocument()
    // All 6 event types from requirement 70.1
    expect(screen.getByLabelText('Invoice created')).toBeInTheDocument()
    expect(screen.getByLabelText('Invoice paid')).toBeInTheDocument()
    expect(screen.getByLabelText('Invoice overdue')).toBeInTheDocument()
    expect(screen.getByLabelText('Payment received')).toBeInTheDocument()
    expect(screen.getByLabelText('Customer created')).toBeInTheDocument()
    expect(screen.getByLabelText('Vehicle added')).toBeInTheDocument()
    expect(screen.getByLabelText('Active')).toBeInTheDocument()
  })

  // 70.1: Create webhook calls POST /webhooks
  it('submits create webhook form with selected events', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    await user.type(screen.getByLabelText('Webhook URL'), 'https://new.example.com/hook')
    await user.click(screen.getByLabelText('Invoice created'))
    await user.click(screen.getByLabelText('Payment received'))
    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Create webhook' }))

    expect(apiClient.post).toHaveBeenCalledWith('/webhooks', {
      url: 'https://new.example.com/hook',
      event_types: ['invoice.created', 'payment.received'],
      is_active: true,
    })
  })

  // 70.1: Edit webhook opens modal pre-filled
  it('opens edit modal pre-filled with webhook data', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    await user.click(editButtons[0])

    expect(screen.getByText('Edit webhook')).toBeInTheDocument()
    expect(screen.getByLabelText('Webhook URL')).toHaveValue('https://example.com/hook1')
    // Pre-selected event types
    expect(screen.getByLabelText('Invoice created')).toBeChecked()
    expect(screen.getByLabelText('Invoice paid')).toBeChecked()
    expect(screen.getByLabelText('Invoice overdue')).not.toBeChecked()
  })

  // 70.1: Edit webhook calls PUT /webhooks/:id
  it('submits edit webhook form with PUT request', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    await user.click(editButtons[0])

    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(apiClient.put).toHaveBeenCalledWith('/webhooks/wh-1', {
      url: 'https://example.com/hook1',
      event_types: ['invoice.created', 'invoice.paid'],
      is_active: true,
    })
  })

  // 70.1: Delete webhook calls DELETE /webhooks/:id
  it('calls delete API when delete button is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    await user.click(deleteButtons[0])

    expect(apiClient.delete).toHaveBeenCalledWith('/webhooks/wh-1')
  })

  // 70.4: Delivery log shows status, response code, attempt count
  it('displays delivery log with status, response code, and attempt', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')

    // Switch to delivery log tab
    await user.click(screen.getByRole('tab', { name: 'Delivery log' }))

    expect(screen.getByText('200')).toBeInTheDocument()
    expect(screen.getByText('500')).toBeInTheDocument()
    // Check attempt numbers
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText('1')).toBeInTheDocument()
    expect(within(panel).getByText('3')).toBeInTheDocument()
  })

  // 70.4: Failed deliveries show warning banner
  it('shows warning banner when there are failed deliveries', async () => {
    setupMocks()
    render(<WebhookSettings />)
    expect(await screen.findByText(/Delivery failures detected/)).toBeInTheDocument()
  })

  it('does not show warning banner when all deliveries succeeded', async () => {
    const successOnly = mockDeliveries.filter((d) => d.status === 'success')
    setupMocks({ deliveries: successOnly })
    render(<WebhookSettings />)
    await screen.findByText('Webhook settings')
    expect(screen.queryByText(/Delivery failures detected/)).not.toBeInTheDocument()
  })

  // Empty states
  it('shows empty state when no webhooks configured', async () => {
    setupMocks({ webhooks: [], deliveries: [] })
    render(<WebhookSettings />)
    expect(await screen.findByText(/No webhooks configured/)).toBeInTheDocument()
  })

  it('shows empty state when no delivery history', async () => {
    setupMocks({ deliveries: [] })
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('tab', { name: 'Delivery log' }))
    expect(screen.getByText(/No delivery history yet/)).toBeInTheDocument()
  })

  // Validation: URL required
  it('shows validation error when URL is empty', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    // Try to submit without filling URL
    await user.click(screen.getByLabelText('Invoice created'))
    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Create webhook' }))

    expect(screen.getByText('URL is required')).toBeInTheDocument()
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  // Validation: at least one event type required
  it('shows validation error when no event types selected', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookSettings />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    await user.type(screen.getByLabelText('Webhook URL'), 'https://valid.example.com/hook')
    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Create webhook' }))

    expect(screen.getByText('Select at least one event type')).toBeInTheDocument()
    expect(apiClient.post).not.toHaveBeenCalled()
  })
})
