import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { KonstaShell } from '../KonstaShell'

const mockUseAuth = vi.fn()
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({
    selectedBranchId: null,
    branches: [],
    selectBranch: vi.fn(),
    isLoading: false,
    isBranchLocked: false,
  }),
}))

function renderWithRouter(
  ui: React.ReactElement,
  { route = '/' }: { route?: string } = {},
) {
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>)
}

describe('KonstaShell', () => {
  it('shows navbar and tabbar when authenticated on a non-auth route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'salesperson' },
    })
    renderWithRouter(
      <KonstaShell>
        <div>Dashboard content</div>
      </KonstaShell>,
    )
    expect(screen.getByTestId('konsta-navbar')).toBeInTheDocument()
    expect(screen.getByTestId('konsta-tabbar')).toBeInTheDocument()
    expect(screen.getByText('Dashboard content')).toBeInTheDocument()
  })

  it('hides navbar and tabbar on /login route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Login form</div>
      </KonstaShell>,
      { route: '/login' },
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
    expect(screen.getByText('Login form')).toBeInTheDocument()
  })

  it('hides navbar and tabbar on /login/mfa route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>MFA form</div>
      </KonstaShell>,
      { route: '/login/mfa' },
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })

  it('hides navbar and tabbar on /forgot-password route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Reset form</div>
      </KonstaShell>,
      { route: '/forgot-password' },
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })

  it('hides navbar and tabbar on /signup route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Signup form</div>
      </KonstaShell>,
      { route: '/signup' },
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })

  it('hides navbar and tabbar on /reset-password route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Reset password form</div>
      </KonstaShell>,
      { route: '/reset-password' },
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })

  it('hides navbar and tabbar on /verify-email route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Verify email</div>
      </KonstaShell>,
      { route: '/verify-email' },
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })

  it('hides navbar and tabbar when not authenticated on non-auth route', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Content</div>
      </KonstaShell>,
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })

  it('hides tabbar for kiosk users but shows navbar', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'kiosk' },
    })
    renderWithRouter(
      <KonstaShell>
        <div>Kiosk content</div>
      </KonstaShell>,
    )
    expect(screen.getByTestId('konsta-navbar')).toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })

  it('renders children in the main content area when authenticated', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      user: { role: 'salesperson' },
    })
    renderWithRouter(
      <KonstaShell>
        <div>Page content</div>
      </KonstaShell>,
    )
    const main = screen.getByRole('main')
    expect(main).toBeInTheDocument()
    expect(main).toHaveTextContent('Page content')
  })

  it('renders children directly on auth routes without main wrapper', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Login content</div>
      </KonstaShell>,
      { route: '/login' },
    )
    // Children are rendered but not inside a <main> element
    expect(screen.getByText('Login content')).toBeInTheDocument()
    expect(screen.queryByRole('main')).not.toBeInTheDocument()
  })

  it('handles /login sub-routes as auth routes', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      user: null,
    })
    renderWithRouter(
      <KonstaShell>
        <div>Login sub-route</div>
      </KonstaShell>,
      { route: '/login/mfa' },
    )
    expect(screen.queryByTestId('konsta-navbar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('konsta-tabbar')).not.toBeInTheDocument()
  })
})
