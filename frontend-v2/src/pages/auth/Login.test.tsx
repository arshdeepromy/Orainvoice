import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

/**
 * Login page tests (Task 13).
 *
 * useAuth is mocked so the test drives the page's branches deterministically
 * (login → mfaRequired / success → setup-wizard progress check → navigate). The
 * api client is mocked so the post-login `/api/v2/setup-wizard/progress` check
 * and the NodeStatusIndicator `/ha/status` fetch resolve without a server.
 * Covers: structure, the happy-path login → navigate('/'), the credentials sent
 * (incl. "remember"), and the invalid-credentials error surfaced from useAuth.
 */

const { login, loginWithGoogle, loginWithPasskey, apiGet, apiPost } = vi.hoisted(() => ({
  login: vi.fn(),
  loginWithGoogle: vi.fn(),
  loginWithPasskey: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    login,
    loginWithGoogle,
    loginWithPasskey,
    isLoading: false,
    completeMfa: vi.fn(),
    completeFirebaseMfa: vi.fn(),
    mfaSessionToken: null,
    mfaMethods: [],
    mfaDefaultMethod: null,
  }),
}))

vi.mock('@/api/client', () => ({
  default: { get: apiGet, post: apiPost },
  setAccessToken: vi.fn(),
}))

import { Login } from './Login'

/** Surfaces the current router location so we can assert navigation targets. */
function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname}</div>
}

function renderLogin() {
  render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  // setup-wizard progress check → wizard already complete (go to dashboard);
  // NodeStatusIndicator /ha/status → reject so it renders nothing.
  apiGet.mockImplementation((url: string) => {
    if (url === '/api/v2/setup-wizard/progress') return Promise.resolve({ data: { wizard_completed: true } })
    return Promise.reject(new Error('no'))
  })
  apiPost.mockResolvedValue({ data: {} })
})

describe('Login — structure', () => {
  it('renders the sign-in heading, fields, and SSO + signup links', () => {
    renderLogin()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email address')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('Remember this device')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute('href', '/auth/password-reset')
    expect(screen.getByRole('button', { name: 'Sign in with Google' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in with Passkey' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start a free trial' })).toHaveAttribute('href', '/signup')
  })
})

describe('Login — happy path', () => {
  it('submits credentials and navigates to the dashboard on success', async () => {
    const user = userEvent.setup()
    login.mockResolvedValue({ mfaRequired: false })
    renderLogin()

    await user.type(screen.getByLabelText('Email address'), 'arsh@workshop.co.nz')
    await user.type(screen.getByLabelText('Password'), 'workshop2025')
    await user.click(screen.getByLabelText('Remember this device'))
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(login).toHaveBeenCalledWith({
      email: 'arsh@workshop.co.nz',
      password: 'workshop2025',
      remember: true,
    })
    expect(await screen.findByTestId('location')).toHaveTextContent('/')
  })
})

describe('Login — error handling', () => {
  it('shows the error message when credentials are invalid', async () => {
    const user = userEvent.setup()
    login.mockRejectedValue(new Error('Invalid email or password'))
    renderLogin()

    await user.type(screen.getByLabelText('Email address'), 'bad@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument()
  })
})
