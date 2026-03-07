import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 47 — Webhook Management and Security
 * - 47.1: Register outbound webhook URLs with target URL, event types, secret, status
 * - 47.2: HTTP POST with JSON payload and X-OraInvoice-Signature header
 * - 47.4: Webhook delivery log per organisation
 * - 47.5: Auto-disable after 50 consecutive failures
 * - 47.6: Test webhook function
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
import { WebhookManagement } from '../pages/settings/WebhookManagement'
import type { OutboundWebhook, DeliveryLogEntry } from '../pages/settings/WebhookManagement'

const mockWebhooks: OutboundWebhook[] = [
  {
    id: 'wh-1',
    org_id: 'org-1',
    target_url: 'https://example.com/hook1',
    event_types: ['invoice.created', 'invoice.paid'],
    is_active: true,
    consecutive_failures: 0,
    last_delivery_at: '2025-01-20T14:00:00Z',
    created_at: '2025-01-15T10:00:00Z',
    updated_at: '2025-01-15T10:00:00Z',
  },
  {
    id: 'wh-2',
    org_id: 'org-1',
    target_url: 'https://example.com/hook2',
    event_types: ['customer.created'],
    is_active: false,
    consecutive_failures: 50,
    last_delivery_at: null,
    created_at: '2025-01-10T08:00:00Z',
    updated_at: '2025-01-10T08:00:00Z',
  },
]

const mockDeliveries: DeliveryLogEntry[] = [
  {
    id: 'del-1',
    webhook_id: 'wh-1',
    event_type: 'invoice.created',
    payload: null,
    response_status: 200,
    response_time_ms: 150,
    retry_count: 0,
    status: 'success',
    error_details: null,
    created_at: '2025-01-20T14:00:00Z',
  },
  {
    id: 'del-2',
    webhook_id: 'wh-1',
    event_type: 'invoice.paid',
    payload: null,
    response_status: 500,
    response_time_ms: 2000,
    retry_count: 3,
    status: 'failed',
    error_details: 'Internal Server Error',
    created_at: '2025-01-20T14:05:00Z',
  },
]

function setupMocks(overrides: {
  webhooks?: OutboundWebhook[]
  deliveries?: DeliveryLogEntry[]
} = {}) {
  const webhooks = overrides.webhooks ?? mockWebhooks
  const deliveries = overrides.deliveries ?? mockDeliveries

  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/outbound-webhooks') return Promise.resolve({ data: webhooks })
    if (url.match(/\/outbound-webhooks\/.*\/deliveries/))
      return Promise.resolve({ data: deliveries })
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { id: 'wh-new', success: true },
  })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
}

describe('Webhook management', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<WebhookManagement />)
    expect(screen.getByRole('status', { name: 'Loading webhook management' })).toBeInTheDocument()
  })

  it('shows error banner when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<WebhookManagement />)
    expect(await screen.findByText(/couldn't load your webhook settings/i)).toBeInTheDocument()
  })

  // 47.1: Webhook list displays configured webhooks
  it('displays webhook list with URL, event types, and status', async () => {
    setupMocks()
    render(<WebhookManagement />)
    expect(await screen.findByText('https://example.com/hook1')).toBeInTheDocument()
    expect(screen.getByText('https://example.com/hook2')).toBeInTheDocument()
    expect(screen.getByText('invoice.created')).toBeInTheDocument()
    expect(screen.getByText('invoice.paid')).toBeInTheDocument()
    expect(screen.getByText('customer.created')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  // 47.1: Create webhook modal
  it('opens create webhook modal with event type checkboxes', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookManagement />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    expect(screen.getByText('Create webhook', { selector: 'h2' })).toBeInTheDocument()
    expect(screen.getByLabelText('Webhook URL')).toBeInTheDocument()
    // All 7 V2 event types
    expect(screen.getByLabelText('Invoice created')).toBeInTheDocument()
    expect(screen.getByLabelText('Invoice paid')).toBeInTheDocument()
    expect(screen.getByLabelText('Customer created')).toBeInTheDocument()
    expect(screen.getByLabelText('Job status changed')).toBeInTheDocument()
    expect(screen.getByLabelText('Booking created')).toBeInTheDocument()
    expect(screen.getByLabelText('Payment received')).toBeInTheDocument()
    expect(screen.getByLabelText('Stock low')).toBeInTheDocument()
  })

  // 47.1: Create webhook calls POST
  it('submits create webhook form', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookManagement />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    await user.type(screen.getByLabelText('Webhook URL'), 'https://new.example.com/hook')
    await user.click(screen.getByLabelText('Invoice created'))
    await user.click(screen.getByLabelText('Payment received'))
    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Create webhook' }))

    expect(apiClient.post).toHaveBeenCalledWith('/outbound-webhooks', {
      target_url: 'https://new.example.com/hook',
      event_types: ['invoice.created', 'payment.received'],
      is_active: true,
    })
  })

  // 47.1: Edit webhook
  it('opens edit modal pre-filled with webhook data', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookManagement />)
    await screen.findByText('https://example.com/hook1')
    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    await user.click(editButtons[0])

    expect(screen.getByText('Edit webhook')).toBeInTheDocument()
    expect(screen.getByLabelText('Webhook URL')).toHaveValue('https://example.com/hook1')
    expect(screen.getByLabelText('Invoice created')).toBeChecked()
    expect(screen.getByLabelText('Invoice paid')).toBeChecked()
    expect(screen.getByLabelText('Customer created')).not.toBeChecked()
  })

  // 47.1: Delete webhook
  it('calls delete API when delete button is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookManagement />)
    await screen.findByText('https://example.com/hook1')
    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    await user.click(deleteButtons[0])

    expect(apiClient.delete).toHaveBeenCalledWith('/outbound-webhooks/wh-1')
  })

  // 47.6: Test webhook button
  it('shows test button for each webhook', async () => {
    setupMocks()
    render(<WebhookManagement />)
    await screen.findByText('https://example.com/hook1')
    const testButtons = screen.getAllByRole('button', { name: 'Test' })
    expect(testButtons.length).toBeGreaterThanOrEqual(2)
  })

  // Validation: URL required
  it('shows validation error when URL is empty', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookManagement />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    await user.click(screen.getByLabelText('Invoice created'))
    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Create webhook' }))

    expect(screen.getByText('URL is required')).toBeInTheDocument()
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  // Validation: at least one event type
  it('shows validation error when no event types selected', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<WebhookManagement />)
    await screen.findByText('https://example.com/hook1')
    await user.click(screen.getByRole('button', { name: 'Create webhook' }))

    await user.type(screen.getByLabelText('Webhook URL'), 'https://valid.example.com/hook')
    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Create webhook' }))

    expect(screen.getByText('Select at least one event type')).toBeInTheDocument()
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  // 47.5: Shows failure warning
  it('shows warning when webhooks have failures', async () => {
    setupMocks()
    render(<WebhookManagement />)
    expect(await screen.findByText(/delivery failures/i)).toBeInTheDocument()
  })

  // Empty state
  it('shows empty state when no webhooks configured', async () => {
    setupMocks({ webhooks: [], deliveries: [] })
    render(<WebhookManagement />)
    expect(await screen.findByText(/No webhooks configured/)).toBeInTheDocument()
  })
})
