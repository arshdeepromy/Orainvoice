import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 68.1-68.6
 * - 68.1: Xero OAuth connect from organisation settings
 * - 68.2: MYOB OAuth connect from organisation settings
 * - 68.3: Auto-sync invoices to connected accounting software
 * - 68.4: Auto-sync payments to connected accounting software
 * - 68.5: Auto-sync credit notes to connected accounting software
 * - 68.6: Failed sync logging, warning display, and manual retry
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import { AccountingIntegrations } from '../pages/settings/AccountingIntegrations'

const mockXeroConnected = {
  provider: 'xero' as const,
  connected: true,
  account_name: 'My Workshop Ltd',
  connected_at: '2025-01-10T09:00:00Z',
  last_sync_at: '2025-01-20T14:30:00Z',
  sync_status: 'success' as const,
  error_message: null,
}

const mockXeroDisconnected = {
  provider: 'xero' as const,
  connected: false,
  account_name: null,
  connected_at: null,
  last_sync_at: null,
  sync_status: 'idle' as const,
  error_message: null,
}

const mockMyobDisconnected = {
  provider: 'myob' as const,
  connected: false,
  account_name: null,
  connected_at: null,
  last_sync_at: null,
  sync_status: 'idle' as const,
  error_message: null,
}

const mockMyobFailed = {
  provider: 'myob' as const,
  connected: true,
  account_name: 'Workshop MYOB',
  connected_at: '2025-01-05T08:00:00Z',
  last_sync_at: '2025-01-19T10:00:00Z',
  sync_status: 'failed' as const,
  error_message: 'Token expired. Please reconnect.',
}

const mockSyncLog = [
  {
    id: 'sync-1',
    provider: 'xero' as const,
    entity_type: 'invoice' as const,
    entity_id: 'inv-1',
    entity_ref: 'INV-0042',
    status: 'success' as const,
    error_message: null,
    synced_at: '2025-01-20T14:30:00Z',
  },
  {
    id: 'sync-2',
    provider: 'xero' as const,
    entity_type: 'payment' as const,
    entity_id: 'pay-1',
    entity_ref: 'PAY-0015',
    status: 'success' as const,
    error_message: null,
    synced_at: '2025-01-20T14:31:00Z',
  },
  {
    id: 'sync-3',
    provider: 'myob' as const,
    entity_type: 'credit_note' as const,
    entity_id: 'cn-1',
    entity_ref: 'CN-0003',
    status: 'failed' as const,
    error_message: 'MYOB API timeout',
    synced_at: '2025-01-19T10:00:00Z',
  },
]

import type { SyncLogEntry } from '../pages/settings/AccountingIntegrations'

interface MockConnection {
  provider: 'xero' | 'myob'
  connected: boolean
  account_name: string | null
  connected_at: string | null
  last_sync_at: string | null
  sync_status: 'idle' | 'syncing' | 'success' | 'failed'
  error_message: string | null
}

function setupMocks(overrides: {
  xero?: MockConnection
  myob?: MockConnection
  sync_log?: SyncLogEntry[]
} = {}) {
  const data = {
    xero: overrides.xero ?? mockXeroDisconnected,
    myob: overrides.myob ?? mockMyobDisconnected,
    sync_log: overrides.sync_log ?? [],
  }
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/org/integrations/accounting') return Promise.resolve({ data })
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { redirect_url: 'https://oauth.example.com/authorize' },
  })
}

describe('Accounting integration settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<AccountingIntegrations />)
    expect(screen.getByRole('status', { name: 'Loading accounting integrations' })).toBeInTheDocument()
  })

  it('shows error banner when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<AccountingIntegrations />)
    expect(await screen.findByText(/couldn't load your accounting integration settings/i)).toBeInTheDocument()
  })

  // 68.1: Xero OAuth connect button
  it('displays Xero connect button when not connected', async () => {
    setupMocks()
    render(<AccountingIntegrations />)
    expect(await screen.findByRole('button', { name: 'Connect Xero' })).toBeInTheDocument()
    const badges = screen.getAllByText('Not connected')
    expect(badges.length).toBeGreaterThanOrEqual(1)
  })

  // 68.2: MYOB OAuth connect button
  it('displays MYOB connect button when not connected', async () => {
    setupMocks()
    render(<AccountingIntegrations />)
    expect(await screen.findByRole('button', { name: 'Connect MYOB' })).toBeInTheDocument()
  })

  // 68.1: Xero connection status when connected
  it('shows Xero connection details when connected', async () => {
    setupMocks({ xero: mockXeroConnected })
    render(<AccountingIntegrations />)
    expect(await screen.findByText('My Workshop Ltd')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disconnect Xero' })).toBeInTheDocument()
  })

  // 68.1: Xero OAuth connect triggers redirect
  it('initiates Xero OAuth flow on connect click', async () => {
    setupMocks()
    const user = userEvent.setup()
    // Mock window.location
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { ...originalLocation, href: '' },
    })

    render(<AccountingIntegrations />)
    const btn = await screen.findByRole('button', { name: 'Connect Xero' })
    await user.click(btn)

    expect(apiClient.post).toHaveBeenCalledWith('/org/integrations/accounting/xero/connect')

    // Restore
    Object.defineProperty(window, 'location', { writable: true, value: originalLocation })
  })

  // 68.2: MYOB OAuth connect triggers redirect
  it('initiates MYOB OAuth flow on connect click', async () => {
    setupMocks()
    const user = userEvent.setup()
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { ...originalLocation, href: '' },
    })

    render(<AccountingIntegrations />)
    const btn = await screen.findByRole('button', { name: 'Connect MYOB' })
    await user.click(btn)

    expect(apiClient.post).toHaveBeenCalledWith('/org/integrations/accounting/myob/connect')

    Object.defineProperty(window, 'location', { writable: true, value: originalLocation })
  })

  // 68.6: Failed sync warning banner
  it('shows warning banner when there are failed syncs', async () => {
    setupMocks({ sync_log: mockSyncLog })
    render(<AccountingIntegrations />)
    expect(await screen.findByText(/Sync failures detected/)).toBeInTheDocument()
  })

  it('does not show warning banner when all syncs succeeded', async () => {
    const successOnly = mockSyncLog.filter((e) => e.status === 'success')
    setupMocks({ sync_log: successOnly })
    render(<AccountingIntegrations />)
    await screen.findByText('Accounting integrations')
    expect(screen.queryByText(/Sync failures detected/)).not.toBeInTheDocument()
  })

  // 68.3, 68.4, 68.5: Sync log shows invoices, payments, credit notes
  it('displays sync log with invoice, payment, and credit note entries', async () => {
    setupMocks({ sync_log: mockSyncLog })
    render(<AccountingIntegrations />)
    expect(await screen.findByText('INV-0042')).toBeInTheDocument()
    expect(screen.getByText('PAY-0015')).toBeInTheDocument()
    expect(screen.getByText('CN-0003')).toBeInTheDocument()
    expect(screen.getByText('invoice')).toBeInTheDocument()
    expect(screen.getByText('payment')).toBeInTheDocument()
    expect(screen.getByText('credit note')).toBeInTheDocument()
  })

  // 68.6: Manual retry for failed syncs
  it('shows retry button only for failed sync entries', async () => {
    setupMocks({ sync_log: mockSyncLog })
    render(<AccountingIntegrations />)
    await screen.findByText('INV-0042')
    const retryButtons = screen.getAllByRole('button', { name: 'Retry' })
    expect(retryButtons).toHaveLength(1) // only the failed entry
  })

  it('calls retry API when retry button is clicked', async () => {
    setupMocks({ sync_log: mockSyncLog })
    const user = userEvent.setup()
    render(<AccountingIntegrations />)
    const retryBtn = await screen.findByRole('button', { name: 'Retry' })
    await user.click(retryBtn)
    expect(apiClient.post).toHaveBeenCalledWith('/org/integrations/accounting/sync/sync-3/retry')
  })

  // 68.6: Failed connection shows error message
  it('shows sync error message on failed connection', async () => {
    setupMocks({ myob: mockMyobFailed })
    render(<AccountingIntegrations />)
    expect(await screen.findByText('Token expired. Please reconnect.')).toBeInTheDocument()
    expect(screen.getByText('Sync failed')).toBeInTheDocument()
  })

  it('shows disconnect button for connected MYOB', async () => {
    setupMocks({ myob: mockMyobFailed })
    render(<AccountingIntegrations />)
    expect(await screen.findByRole('button', { name: 'Disconnect MYOB' })).toBeInTheDocument()
  })

  it('calls disconnect API when disconnect is clicked', async () => {
    setupMocks({ xero: mockXeroConnected })
    const user = userEvent.setup()
    render(<AccountingIntegrations />)
    const btn = await screen.findByRole('button', { name: 'Disconnect Xero' })
    await user.click(btn)
    expect(apiClient.post).toHaveBeenCalledWith('/org/integrations/accounting/xero/disconnect')
  })

  it('shows empty state when no sync activity', async () => {
    setupMocks({ sync_log: [] })
    render(<AccountingIntegrations />)
    expect(await screen.findByText(/No sync activity yet/)).toBeInTheDocument()
  })
})
