import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 48.1-48.5
 * - 48.1: Dedicated Integrations section with separate config page per integration
 * - 48.2: Connection test button on each integration page
 * - 48.3: Carjam config: API key, endpoint URL, per-lookup cost, global rate limit
 * - 48.4: Stripe config: platform account, webhook endpoint, signing secret
 * - 48.5: Credentials stored encrypted, never returned in API responses (masked display)
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  }
})

import apiClient from '@/api/client'
import { Integrations } from '../pages/admin/Integrations'

function mockIntegrationConfig(name: string, fields: Record<string, string> = {}, isVerified = false) {
  return {
    name,
    is_verified: isVerified,
    updated_at: '2025-06-20T10:00:00Z',
    fields,
  }
}

function setupMocks(overrides: Record<string, ReturnType<typeof mockIntegrationConfig>> = {}) {
  const configs: Record<string, ReturnType<typeof mockIntegrationConfig>> = {
    carjam: mockIntegrationConfig('carjam', {
      api_key: '***masked***',
      endpoint_url: 'https://api.carjam.co.nz/v2',
      per_lookup_cost: '0.50',
      global_rate_limit: '60',
    }, true),
    stripe: mockIntegrationConfig('stripe', {
      platform_account: 'acct_123456',
      webhook_endpoint: 'https://workshoppro.co.nz/api/v1/payments/stripe/webhook',
      signing_secret: '***masked***',
    }, true),
    smtp: mockIntegrationConfig('smtp', {
      api_key: '***masked***',
      domain: 'mail.workshoppro.co.nz',
      from_name: 'WorkshopPro NZ',
      reply_to: 'support@workshoppro.co.nz',
    }, false),
    twilio: mockIntegrationConfig('twilio', {
      account_sid: 'AC1234567890',
      auth_token: '***masked***',
      sender_number: '+6421000000',
    }, false),
    ...overrides,
  }

  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    const match = url.match(/\/admin\/integrations\/(\w+)$/)
    if (match && configs[match[1]]) {
      return Promise.resolve({ data: configs[match[1]] })
    }
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { success: true, message: 'Connection successful' },
  })
}

describe('Admin Integrations page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // 48.1: Tabbed layout with all four integrations
  it('renders tabs for all four integrations', async () => {
    setupMocks()
    render(<Integrations />)

    expect(screen.getByRole('tab', { name: 'Carjam' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Stripe' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'SMTP / Email' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Twilio' })).toBeInTheDocument()
  })

  // 48.1: Default tab is Carjam
  it('shows Carjam tab as active by default', async () => {
    setupMocks()
    render(<Integrations />)

    const carjamTab = screen.getByRole('tab', { name: 'Carjam' })
    expect(carjamTab).toHaveAttribute('aria-selected', 'true')
  })

  // 48.3: Carjam fields — API key, endpoint URL, per-lookup cost, global rate limit
  it('displays Carjam configuration fields', async () => {
    setupMocks()
    render(<Integrations />)

    expect(await screen.findByText('Carjam')).toBeInTheDocument()
    // Endpoint URL should be visible (non-credential field)
    expect(await screen.findByLabelText('Endpoint URL')).toHaveValue('https://api.carjam.co.nz/v2')
    expect(screen.getByLabelText('Per-lookup cost (NZD)')).toHaveValue(0.5)
    expect(screen.getByLabelText('Global rate limit (calls/min)')).toHaveValue(60)
  })

  // 48.5: Credential fields show masked values
  it('shows masked value for credential fields', async () => {
    setupMocks()
    render(<Integrations />)

    // API key should be masked with a Change button
    expect(await screen.findByText('••••••••')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change' })).toBeInTheDocument()
    expect(screen.getByText('Credential is set. Click Change to update.')).toBeInTheDocument()
  })

  // 48.5: Clicking Change reveals an editable password field
  it('reveals editable field when Change is clicked on masked credential', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByText('••••••••')
    await user.click(screen.getByRole('button', { name: 'Change' }))

    // Now the API key input should be visible and editable
    const apiKeyInput = screen.getByLabelText('API key')
    expect(apiKeyInput).toHaveValue('')
    expect(apiKeyInput).toHaveAttribute('type', 'password')
  })

  // 48.1: Verified badge shown for verified integrations
  it('shows Verified badge for verified integrations', async () => {
    setupMocks()
    render(<Integrations />)

    expect(await screen.findByText('Verified')).toBeInTheDocument()
  })

  // 48.1: Not verified badge for unverified integrations
  it('shows Not verified badge for unverified integrations', async () => {
    setupMocks({
      carjam: mockIntegrationConfig('carjam', {}, false),
    })
    render(<Integrations />)

    expect(await screen.findByText('Not verified')).toBeInTheDocument()
  })

  // 48.2: Save configuration calls PUT endpoint
  it('saves configuration via PUT endpoint', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByLabelText('Endpoint URL')

    // Modify a non-credential field
    const endpointInput = screen.getByLabelText('Endpoint URL')
    await user.clear(endpointInput)
    await user.type(endpointInput, 'https://new-api.carjam.co.nz/v3')

    await user.click(screen.getByRole('button', { name: 'Save configuration' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/integrations/carjam', expect.objectContaining({
      endpoint_url: 'https://new-api.carjam.co.nz/v3',
    }))
  })

  // 48.5: Unchanged masked credentials are not sent in save payload
  it('does not send masked credential values when saving', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByLabelText('Endpoint URL')

    await user.click(screen.getByRole('button', { name: 'Save configuration' }))

    const putCall = (apiClient.put as ReturnType<typeof vi.fn>).mock.calls[0]
    const payload = putCall[1] as Record<string, string>
    // api_key should NOT be in the payload since it's still masked
    expect(payload).not.toHaveProperty('api_key')
  })

  // 48.2: Test connection button calls test endpoint
  it('calls test endpoint when Test connection is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByLabelText('Endpoint URL')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(apiClient.post).toHaveBeenCalledWith('/admin/integrations/carjam/test')
  })

  // 48.2: Successful test shows success banner
  it('shows success banner after successful connection test', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByLabelText('Endpoint URL')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    // The AlertBanner title and the toast are separate — check the banner via role
    const banner = await screen.findByRole('status')
    expect(banner).toHaveTextContent('Connection successful')
  })

  // 48.2: Failed test shows error banner
  it('shows error banner after failed connection test', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: { success: false, message: 'Invalid API key' },
    })
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByLabelText('Endpoint URL')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText('Connection failed')).toBeInTheDocument()
    // The detail message appears in the AlertBanner body
    const alerts = screen.getAllByText('Invalid API key')
    expect(alerts.length).toBeGreaterThanOrEqual(1)
  })

  // 48.4: Stripe tab shows correct fields
  it('displays Stripe configuration fields when Stripe tab is selected', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByText('Carjam')
    await user.click(screen.getByRole('tab', { name: 'Stripe' }))

    expect(await screen.findByLabelText('Platform account ID')).toHaveValue('acct_123456')
    expect(screen.getByLabelText('Webhook endpoint URL')).toHaveValue(
      'https://workshoppro.co.nz/api/v1/payments/stripe/webhook',
    )
  })

  // 48.1: SMTP tab shows correct fields
  it('displays SMTP configuration fields when SMTP tab is selected', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByText('Carjam')
    await user.click(screen.getByRole('tab', { name: 'SMTP / Email' }))

    expect(await screen.findByLabelText('Sending domain')).toHaveValue('mail.workshoppro.co.nz')
    expect(screen.getByLabelText('From name')).toHaveValue('WorkshopPro NZ')
    expect(screen.getByLabelText('Reply-to address')).toHaveValue('support@workshoppro.co.nz')
  })

  // 48.1: Twilio tab shows correct fields
  it('displays Twilio configuration fields when Twilio tab is selected', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByText('Carjam')
    await user.click(screen.getByRole('tab', { name: 'Twilio' }))

    expect(await screen.findByLabelText('Account SID')).toHaveValue('AC1234567890')
    expect(screen.getByLabelText('Sender phone number')).toHaveValue('+6421000000')
  })

  // Error state: shows error banner when config fails to load
  it('shows error banner when configuration fails to load', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<Integrations />)

    expect(await screen.findByText(/Could not load Carjam configuration/)).toBeInTheDocument()
  })

  // Loading state
  it('shows loading spinner while fetching configuration', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<Integrations />)

    expect(screen.getByRole('status', { name: /Loading Carjam configuration/ })).toBeInTheDocument()
  })

  // 48.2: Test connection failure from network error
  it('shows error banner when test connection throws network error', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('Network error'))
    const user = userEvent.setup()
    render(<Integrations />)

    await screen.findByLabelText('Endpoint URL')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText('Connection failed')).toBeInTheDocument()
    expect(screen.getByText(/check credentials/)).toBeInTheDocument()
  })
})
