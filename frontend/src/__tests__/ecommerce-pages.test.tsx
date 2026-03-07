import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — Ecommerce Module, Task 39.16
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import WooCommerceSetup from '../pages/ecommerce/WooCommerceSetup'
import SkuMappings from '../pages/ecommerce/SkuMappings'
import ApiKeys from '../pages/ecommerce/ApiKeys'

const mockSyncLogs = {
  logs: [
    {
      id: 'log-1', direction: 'inbound', entity_type: 'order',
      entity_id: 'WC-1001', status: 'completed', error_details: null,
      retry_count: 0, created_at: '2025-01-15T10:00:00Z',
    },
  ],
  total: 1,
}

const mockMappings = {
  mappings: [
    {
      id: 'map-1', external_sku: 'WC-SKU-001',
      internal_product_id: 'prod-1', platform: 'woocommerce',
      created_at: '2025-01-15T10:00:00Z',
    },
  ],
  total: 1,
}

const mockCredentials = {
  credentials: [
    {
      id: 'cred-1', name: 'Zapier Integration',
      scopes: ['read', 'write'], rate_limit_per_minute: 100,
      is_active: true, last_used_at: null,
      created_at: '2025-01-15T10:00:00Z',
    },
  ],
  total: 1,
}

// ---------------------------------------------------------------------------
// WooCommerceSetup tests
// ---------------------------------------------------------------------------

describe('WooCommerceSetup', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows connection form initially', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { logs: [], total: 0 } })
    render(<WooCommerceSetup />)
    expect(await screen.findByRole('form', { name: 'Connect WooCommerce store' })).toBeInTheDocument()
  })

  it('submits connection form', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { logs: [], total: 0 } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'conn-1' } })
    render(<WooCommerceSetup />)

    const user = userEvent.setup()
    await screen.findByRole('form', { name: 'Connect WooCommerce store' })

    await user.type(screen.getByLabelText('Store URL'), 'https://shop.example.com')
    await user.type(screen.getByLabelText('Consumer Key'), 'ck_test')
    await user.type(screen.getByLabelText('Consumer Secret'), 'cs_test')
    await user.click(screen.getByRole('button', { name: 'Connect Store' }))

    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/v2/ecommerce/woocommerce/connect',
      expect.objectContaining({ store_url: 'https://shop.example.com' }),
    )
  })

  it('shows sync log table when logs exist', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSyncLogs })
    render(<WooCommerceSetup />)

    const table = await screen.findByRole('grid', { name: 'Sync log' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(2) // header + 1 data row
  })

  it('shows empty sync log message', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { logs: [], total: 0 } })
    render(<WooCommerceSetup />)
    expect(await screen.findByText('No sync activity yet')).toBeInTheDocument()
  })

  it('shows error on connection failure', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { logs: [], total: 0 } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: 'Invalid credentials' } },
    })
    render(<WooCommerceSetup />)

    const user = userEvent.setup()
    await screen.findByRole('form', { name: 'Connect WooCommerce store' })

    await user.type(screen.getByLabelText('Store URL'), 'https://shop.example.com')
    await user.type(screen.getByLabelText('Consumer Key'), 'bad')
    await user.type(screen.getByLabelText('Consumer Secret'), 'bad')
    await user.click(screen.getByRole('button', { name: 'Connect Store' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid credentials')
    })
  })
})

// ---------------------------------------------------------------------------
// SkuMappings tests
// ---------------------------------------------------------------------------

describe('SkuMappings', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading state', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<SkuMappings />)
    expect(screen.getByRole('status', { name: 'Loading SKU mappings' })).toBeInTheDocument()
  })

  it('displays mappings table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockMappings })
    render(<SkuMappings />)

    const table = await screen.findByRole('grid', { name: 'SKU mappings list' })
    expect(within(table).getAllByRole('row')).toHaveLength(2)
  })

  it('shows empty state', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { mappings: [], total: 0 } })
    render(<SkuMappings />)
    expect(await screen.findByText('No SKU mappings configured')).toBeInTheDocument()
  })

  it('shows create form when Add Mapping clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { mappings: [], total: 0 } })
    render(<SkuMappings />)
    await screen.findByText('No SKU mappings configured')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add Mapping' }))
    expect(screen.getByRole('form', { name: 'Create SKU mapping' })).toBeInTheDocument()
  })

  it('submits new mapping', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { mappings: [], total: 0 } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new-map' } })
    render(<SkuMappings />)
    await screen.findByText('No SKU mappings configured')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add Mapping' }))
    await user.type(screen.getByLabelText('External SKU'), 'EXT-001')
    await user.click(screen.getByRole('button', { name: 'Save Mapping' }))

    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/v2/ecommerce/sku-mappings',
      expect.objectContaining({ external_sku: 'EXT-001' }),
    )
  })
})

// ---------------------------------------------------------------------------
// ApiKeys tests
// ---------------------------------------------------------------------------

describe('ApiKeys', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading state', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ApiKeys />)
    expect(screen.getByRole('status', { name: 'Loading API keys' })).toBeInTheDocument()
  })

  it('displays credentials table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockCredentials })
    render(<ApiKeys />)

    const table = await screen.findByRole('grid', { name: 'API credentials list' })
    expect(within(table).getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('Zapier Integration')).toBeInTheDocument()
  })

  it('shows empty state', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { credentials: [], total: 0 } })
    render(<ApiKeys />)
    expect(await screen.findByText('No API keys configured')).toBeInTheDocument()
  })

  it('creates new API key and shows it', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { credentials: [], total: 0 } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'new-cred', api_key: 'ora_test_key_abc123', name: 'Test Key', scopes: ['read', 'write'], rate_limit_per_minute: 100, is_active: true, last_used_at: null, created_at: '2025-01-15T10:00:00Z' },
    })
    render(<ApiKeys />)
    await screen.findByText('No API keys configured')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Create API Key' }))
    await user.type(screen.getByLabelText('Key Name'), 'Test Key')
    await user.click(screen.getByRole('button', { name: 'Generate Key' }))

    await waitFor(() => {
      expect(screen.getByTestId('new-key-display')).toBeInTheDocument()
    })
    expect(screen.getByText('ora_test_key_abc123')).toBeInTheDocument()
  })

  it('revokes an API key', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockCredentials })
    ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({})
    render(<ApiKeys />)

    await screen.findByRole('grid', { name: 'API credentials list' })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Revoke' }))

    expect(apiClient.delete).toHaveBeenCalledWith('/api/v2/ecommerce/api-keys/cred-1')
  })
})
