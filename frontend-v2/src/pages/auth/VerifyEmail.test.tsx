import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

/**
 * VerifyEmail page tests (Task 14).
 *
 * The api client is mocked so the auto-verify (POST /auth/verify-signup-email)
 * and the invitation set-password (POST /auth/verify-email) paths resolve
 * without a server. setAccessToken is mocked to assert the token is stored.
 * Covers: the missing-token invalid state, and the invitation flow where the
 * signup auto-verify fails (no type) → password form → submit → /setup.
 */

const { apiPost, setAccessToken } = vi.hoisted(() => ({
  apiPost: vi.fn(),
  setAccessToken: vi.fn(),
}))

let searchParamsString = ''

vi.mock('@/api/client', () => ({
  default: { post: apiPost },
  setAccessToken,
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useSearchParams: () => [new URLSearchParams(searchParamsString)],
  }
})

import { VerifyEmail } from './VerifyEmail'

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname}</div>
}

function renderVerify() {
  render(
    <MemoryRouter initialEntries={['/verify-email']}>
      <Routes>
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  searchParamsString = ''
})

describe('VerifyEmail — missing token', () => {
  it('shows the invalid-link message when no token is present', () => {
    searchParamsString = ''
    renderVerify()
    expect(screen.getByText('This verification link is invalid.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })
})

describe('VerifyEmail — invitation set-password flow', () => {
  beforeEach(() => {
    searchParamsString = 'token=invite-token-1'
    // No type → auto verify-signup-email is attempted and rejected, falling
    // through to the password form (no error shown for the no-type case).
    apiPost.mockImplementation((url: string) => {
      if (url === '/auth/verify-signup-email') {
        return Promise.reject({ response: { status: 400, data: { detail: 'not a signup token' } } })
      }
      if (url === '/auth/verify-email') {
        return Promise.resolve({ data: { access_token: 'at_123', refresh_token: 'rt_456', token_type: 'bearer', message: 'ok' } })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it('renders the password fields after the signup auto-verify falls through', async () => {
    renderVerify()
    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set password' })).toBeInTheDocument()
  })

  it('posts token + password, stores the access token, and navigates to /setup', async () => {
    const user = userEvent.setup()
    renderVerify()

    await user.type(await screen.findByLabelText('Password'), 'SecurePass10!')
    await user.type(screen.getByLabelText('Confirm password'), 'SecurePass10!')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/auth/verify-email', {
        token: 'invite-token-1',
        password: 'SecurePass10!',
      })
      expect(setAccessToken).toHaveBeenCalledWith('at_123')
    })
    expect(await screen.findByTestId('location')).toHaveTextContent('/setup')
  })
})
