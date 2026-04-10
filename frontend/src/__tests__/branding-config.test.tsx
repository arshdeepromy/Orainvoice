import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 1 — Platform Rebranding
 * 44.12: Frontend tests for branding configuration
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, put: mockPut },
  }
})

import apiClient from '@/api/client'
import { BrandingConfig } from '../pages/admin/BrandingConfig'
import type { PlatformBranding } from '../pages/admin/BrandingConfig'

function makeBranding(overrides: Partial<PlatformBranding> = {}): PlatformBranding {
  return {
    id: 'branding-001',
    platform_name: 'OraInvoice',
    logo_url: '/assets/logo/orainvoice-logo.svg',
    primary_colour: '#2563EB',
    secondary_colour: '#1E40AF',
    website_url: 'https://orainvoice.com',
    signup_url: 'https://orainvoice.com/signup',
    support_email: 'support@orainvoice.com',
    terms_url: 'https://orainvoice.com/terms',
    auto_detect_domain: true,
    platform_theme: 'default',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-06-01T00:00:00Z',
    ...overrides,
  }
}

function setupMocks(branding: PlatformBranding = makeBranding()) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/branding') return Promise.resolve({ data: branding })
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: branding })
}

describe('Branding Configuration page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the branding configuration form with all fields', async () => {
    setupMocks()
    render(<BrandingConfig />)

    expect(await screen.findByText('Platform Branding')).toBeInTheDocument()
    expect(screen.getByLabelText('Platform name')).toHaveValue('OraInvoice')
    expect(screen.getByLabelText('Logo URL')).toHaveValue('/assets/logo/orainvoice-logo.svg')
    expect(screen.getByLabelText('Primary colour')).toHaveValue('#2563eb')
    expect(screen.getByLabelText('Secondary colour')).toHaveValue('#1e40af')
    expect(screen.getByLabelText('Signup URL')).toHaveValue('https://orainvoice.com/signup')
    expect(screen.getByLabelText('Website URL')).toHaveValue('https://orainvoice.com')
    expect(screen.getByLabelText('Support email')).toHaveValue('support@orainvoice.com')
    expect(screen.getByLabelText('Terms URL')).toHaveValue('https://orainvoice.com/terms')
  })

  it('shows loading state while fetching branding', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<BrandingConfig />)

    expect(screen.getByRole('status', { name: /loading branding/i })).toBeInTheDocument()
  })

  it('shows error when branding fails to load', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<BrandingConfig />)

    expect(await screen.findByText(/could not load branding configuration/i)).toBeInTheDocument()
  })

  it('displays branding preview with platform name and colours', async () => {
    setupMocks()
    render(<BrandingConfig />)

    await screen.findByText('Platform Branding')

    const preview = screen.getByRole('region', { name: /branding preview/i })
    expect(within(preview).getByText('OraInvoice')).toBeInTheDocument()
    expect(within(preview).getByText('Powered by OraInvoice')).toBeInTheDocument()
  })

  it('displays logo in preview when logo_url is set', async () => {
    setupMocks()
    render(<BrandingConfig />)

    await screen.findByText('Platform Branding')

    const preview = screen.getByRole('region', { name: /branding preview/i })
    const logo = within(preview).getByAltText('OraInvoice')
    expect(logo).toBeInTheDocument()
    expect(logo).toHaveAttribute('src', '/assets/logo/orainvoice-logo.svg')
  })

  it('calls PUT API with updated branding when Save is clicked', async () => {
    const branding = makeBranding()
    setupMocks(branding)
    const user = userEvent.setup()
    render(<BrandingConfig />)

    await screen.findByText('Platform Branding')

    const nameInput = screen.getByLabelText('Platform name')
    await user.clear(nameInput)
    await user.type(nameInput, 'MyBrand')

    await user.click(screen.getByRole('button', { name: 'Save branding' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/branding', expect.objectContaining({
      platform_name: 'MyBrand',
    }))
  })

  it('shows success message after saving', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<BrandingConfig />)

    await screen.findByText('Platform Branding')
    await user.click(screen.getByRole('button', { name: 'Save branding' }))

    expect(await screen.findByText('Branding saved successfully')).toBeInTheDocument()
  })

  it('auto-detect domain checkbox toggles correctly', async () => {
    setupMocks(makeBranding({ auto_detect_domain: true }))
    const user = userEvent.setup()
    render(<BrandingConfig />)

    await screen.findByText('Platform Branding')

    const checkbox = screen.getByLabelText(/auto-detect domain/i)
    expect(checkbox).toBeChecked()

    await user.click(checkbox)
    expect(checkbox).not.toBeChecked()
  })

  it('preview updates when platform name is changed', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<BrandingConfig />)

    await screen.findByText('Platform Branding')

    const nameInput = screen.getByLabelText('Platform name')
    await user.clear(nameInput)
    await user.type(nameInput, 'NewBrand')

    const preview = screen.getByRole('region', { name: /branding preview/i })
    expect(within(preview).getByText('NewBrand')).toBeInTheDocument()
    expect(within(preview).getByText('Powered by NewBrand')).toBeInTheDocument()
  })
})
