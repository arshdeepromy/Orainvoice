import { render, screen, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Phase 6 frontend tests for the unified email-providers admin page.
 *
 * Validates: Requirements 17.1, 17.2, 17.3, 17.5
 * - 17.1: Multi-active banner — singular vs plural rendering, no-active warning
 * - 17.2: Failover preview line — only shown when more than one provider is active
 * - 17.3: Priority slider visible whenever credentials_set, with helper text
 *         "Will apply when activated" when not yet active
 * - 17.5: Disable last-deactivate button with explanatory tooltip; the 409
 *         from the backend stays the authoritative guard
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
import { EmailProviders } from './EmailProviders'

interface ProviderRow {
  id: string
  provider_key: string
  display_name: string
  description: string | null
  smtp_host: string | null
  smtp_port: number | null
  smtp_encryption: 'none' | 'tls' | 'ssl' | null
  priority: number
  is_active: boolean
  credentials_set: boolean
  config: Record<string, unknown>
  setup_guide: string | null
  created_at: string
  updated_at: string
}

function makeProvider(overrides: Partial<ProviderRow> = {}): ProviderRow {
  return {
    id: overrides.provider_key ?? 'brevo',
    provider_key: 'brevo',
    display_name: 'Brevo (Sendinblue)',
    description: 'Transactional email via Brevo',
    smtp_host: 'smtp-relay.brevo.com',
    smtp_port: 587,
    smtp_encryption: 'tls',
    priority: 1,
    is_active: false,
    credentials_set: false,
    config: {},
    setup_guide: null,
    created_at: '2026-05-27T10:00:00Z',
    updated_at: '2026-05-27T10:00:00Z',
    ...overrides,
  }
}

function mockListResponse(providers: ProviderRow[], activeProviderKeys: string[]) {
  return {
    data: {
      providers,
      active_provider: activeProviderKeys[0] ?? null,
      active_providers: activeProviderKeys,
    },
  }
}

describe('EmailProviders admin page — Phase 6 multi-active UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // 17.1: Singular banner when exactly one provider is active.
  it('renders the singular "Active Provider" banner with one active provider', async () => {
    const providers: ProviderRow[] = [
      makeProvider({
        id: 'brevo',
        provider_key: 'brevo',
        display_name: 'Brevo (Sendinblue)',
        is_active: true,
        credentials_set: true,
        priority: 1,
      }),
    ]
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockListResponse(providers, ['brevo']),
    )

    render(<EmailProviders />)

    await waitFor(() => {
      expect(screen.getByText(/Active Provider:/)).toBeInTheDocument()
    })
    // Plural and the failover preview must NOT appear with a single active provider.
    expect(screen.queryByText(/Active Providers \(/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Send order:/)).not.toBeInTheDocument()
    // Display name appears at least in the banner; the row may also render it.
    expect(screen.getAllByText(/Brevo \(Sendinblue\)/).length).toBeGreaterThanOrEqual(1)
  })

  // 17.1 + 17.2: Plural banner + failover preview line with three active providers.
  it('renders the plural "Active Providers" banner and the failover preview with three active providers', async () => {
    const providers: ProviderRow[] = [
      makeProvider({
        id: 'brevo',
        provider_key: 'brevo',
        display_name: 'Brevo',
        is_active: true,
        credentials_set: true,
        priority: 1,
      }),
      makeProvider({
        id: 'sendgrid',
        provider_key: 'sendgrid',
        display_name: 'SendGrid',
        is_active: true,
        credentials_set: true,
        priority: 2,
      }),
      makeProvider({
        id: 'mailgun',
        provider_key: 'mailgun',
        display_name: 'Mailgun',
        is_active: true,
        credentials_set: true,
        priority: 3,
      }),
    ]
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockListResponse(providers, ['brevo', 'sendgrid', 'mailgun']),
    )

    render(<EmailProviders />)

    await waitFor(() => {
      expect(screen.getByText(/Active Providers \(3\):/)).toBeInTheDocument()
    })

    // Banner contents — names joined by ", " in priority order.
    const banner = screen.getByText(/Active Providers \(3\):/).closest('div')!
    expect(within(banner).getByText(/Brevo, SendGrid, Mailgun/)).toBeInTheDocument()

    // Failover preview line uses the arrow separator between display names.
    const sendOrderLabel = screen.getByText(/Send order:/)
    const sendOrderRow = sendOrderLabel.closest('div')!
    expect(sendOrderRow.textContent).toMatch(/1\.\s*Brevo/)
    expect(sendOrderRow.textContent).toMatch(/2\.\s*SendGrid/)
    expect(sendOrderRow.textContent).toMatch(/3\.\s*Mailgun/)
    expect(sendOrderRow.textContent).toContain('→')
  })

  // 17.3: Priority slider stays visible (and shows helper text) when credentials
  // are set but the provider is not yet active.
  it('shows priority slider with "Will apply when activated" helper text when credentials_set && !is_active', async () => {
    const providers: ProviderRow[] = [
      makeProvider({
        id: 'brevo',
        provider_key: 'brevo',
        display_name: 'Brevo',
        is_active: false,
        credentials_set: true,
        priority: 2,
      }),
    ]
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockListResponse(providers, []),
    )

    render(<EmailProviders />)

    // Expand the row so the configuration panel is visible.
    const expandButton = await screen.findByRole('button', { name: /expand/i })
    expandButton.click()

    expect(
      await screen.findByText(/Priority \(lower = higher priority/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Will apply when activated/)).toBeInTheDocument()
  })

  // 17.5: When the provider is the only active one, the Deactivate button must
  // be disabled and carry the explanatory tooltip in the title attribute.
  it('disables the Deactivate button on the last active provider and shows an explanatory tooltip', async () => {
    const providers: ProviderRow[] = [
      makeProvider({
        id: 'brevo',
        provider_key: 'brevo',
        display_name: 'Brevo',
        is_active: true,
        credentials_set: true,
        priority: 1,
      }),
    ]
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockListResponse(providers, ['brevo']),
    )

    render(<EmailProviders />)

    // Wait for the row to render, then expand it so the action buttons appear.
    const expandButton = await screen.findByRole('button', { name: /expand/i })
    expandButton.click()

    const deactivateButton = await screen.findByRole('button', {
      name: /deactivate/i,
    })
    expect(deactivateButton).toBeDisabled()
    expect(deactivateButton.getAttribute('title') ?? '').toMatch(
      /^Activate another provider/,
    )
  })
})
