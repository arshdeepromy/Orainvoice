import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { MobileLayout } from '../MobileLayout'

// Mock child components
vi.mock('../AppHeader', () => ({
  AppHeader: () => <div data-testid="app-header">AppHeader</div>,
}))
vi.mock('../TabNavigator', () => ({
  TabNavigator: () => <div data-testid="tab-navigator">TabNavigator</div>,
}))

const mockUseAuth = vi.fn()
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

function renderWithRouter(
  ui: React.ReactElement,
  { route = '/' }: { route?: string } = {},
) {
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>)
}

describe('MobileLayout', () => {
  it('shows header and tabs when authenticated on a non-auth route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'salesperson' },
    })
    renderWithRouter(
      <MobileLayout>
        <div>Dashboard content</div>
      </MobileLayout>,
    )
    expect(screen.getByTestId('app-header')).toBeInTheDocument()
    expect(screen.getByTestId('tab-navigator')).toBeInTheDocument()
    expect(screen.getByText('Dashboard content')).toBeInTheDocument()
  })

  it('hides header and tabs on login route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <MobileLayout>
        <div>Login form</div>
      </MobileLayout>,
      { route: '/login' },
    )
    expect(screen.queryByTestId('app-header')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tab-navigator')).not.toBeInTheDocument()
    expect(screen.getByText('Login form')).toBeInTheDocument()
  })

  it('hides header and tabs on MFA route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <MobileLayout>
        <div>MFA form</div>
      </MobileLayout>,
      { route: '/mfa-verify' },
    )
    expect(screen.queryByTestId('app-header')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tab-navigator')).not.toBeInTheDocument()
  })

  it('hides header and tabs on forgot-password route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <MobileLayout>
        <div>Reset form</div>
      </MobileLayout>,
      { route: '/forgot-password' },
    )
    expect(screen.queryByTestId('app-header')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tab-navigator')).not.toBeInTheDocument()
  })

  it('hides header and tabs when not authenticated', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <MobileLayout>
        <div>Content</div>
      </MobileLayout>,
    )
    expect(screen.queryByTestId('app-header')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tab-navigator')).not.toBeInTheDocument()
  })

  it('hides tabs for kiosk users but shows header', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'kiosk' },
    })
    renderWithRouter(
      <MobileLayout>
        <div>Kiosk content</div>
      </MobileLayout>,
    )
    expect(screen.getByTestId('app-header')).toBeInTheDocument()
    expect(screen.queryByTestId('tab-navigator')).not.toBeInTheDocument()
  })

  it('renders children in the main content area', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'salesperson' },
    })
    renderWithRouter(
      <MobileLayout>
        <div>Page content</div>
      </MobileLayout>,
    )
    const main = screen.getByRole('main')
    expect(main).toBeInTheDocument()
    expect(main).toHaveTextContent('Page content')
  })
})
