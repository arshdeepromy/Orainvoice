import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

import { AppHeader } from '../AppHeader'

// Mock child components to isolate AppHeader tests
vi.mock('../BranchBadge', () => ({
  BranchBadge: () => <div data-testid="branch-badge">BranchBadge</div>,
}))
vi.mock('../OfflineIndicator', () => ({
  OfflineIndicator: () => <div data-testid="offline-indicator">OfflineIndicator</div>,
}))

const mockUseTenant = vi.fn()
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => mockUseTenant(),
}))

describe('AppHeader', () => {
  it('renders org name from branding', () => {
    mockUseTenant.mockReturnValue({
      branding: {
        name: 'Acme Plumbing',
        logo_url: null,
        primary_colour: '#2563eb',
        secondary_colour: '#1e40af',
      },
      isLoading: false,
      error: null,
    })
    render(<AppHeader />)
    expect(screen.getByText('Acme Plumbing')).toBeInTheDocument()
  })

  it('renders org logo when logo_url is provided', () => {
    mockUseTenant.mockReturnValue({
      branding: {
        name: 'Acme Plumbing',
        logo_url: 'https://example.com/logo.png',
        primary_colour: '#2563eb',
        secondary_colour: '#1e40af',
      },
      isLoading: false,
      error: null,
    })
    render(<AppHeader />)
    const img = screen.getByAltText('Acme Plumbing logo')
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('src', 'https://example.com/logo.png')
  })

  it('renders fallback initial when no logo_url', () => {
    mockUseTenant.mockReturnValue({
      branding: {
        name: 'Acme Plumbing',
        logo_url: null,
        primary_colour: '#2563eb',
        secondary_colour: '#1e40af',
      },
      isLoading: false,
      error: null,
    })
    render(<AppHeader />)
    expect(screen.getByText('A')).toBeInTheDocument()
  })

  it('renders default name when branding is null', () => {
    mockUseTenant.mockReturnValue({
      branding: null,
      isLoading: false,
      error: null,
    })
    render(<AppHeader />)
    expect(screen.getByText('OraInvoice')).toBeInTheDocument()
  })

  it('renders BranchBadge and OfflineIndicator', () => {
    mockUseTenant.mockReturnValue({
      branding: {
        name: 'Test Org',
        logo_url: null,
        primary_colour: '#2563eb',
        secondary_colour: '#1e40af',
      },
      isLoading: false,
      error: null,
    })
    render(<AppHeader />)
    expect(screen.getByTestId('branch-badge')).toBeInTheDocument()
    expect(screen.getByTestId('offline-indicator')).toBeInTheDocument()
  })
})
