import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'

/**
 * MfaVerify page tests (Task 14).
 *
 * useAuth is mocked so the test drives the page's MFA state deterministically
 * (mfaPending gating, available methods, completeMfa). The api client is mocked
 * so the SMS/email challenge-send and passkey paths resolve without a server.
 * Covers: structure (heading + OTP inputs), the totp submit → completeMfa(code,
 * 'totp') → navigate('/'), and the mfaPending=false → redirect to /login guard.
 */

const { completeMfa, completeFirebaseMfa, apiPost } = vi.hoisted(() => ({
  completeMfa: vi.fn(),
  completeFirebaseMfa: vi.fn(),
  apiPost: vi.fn(),
}))

let authState: Record<string, unknown> = {}

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    completeMfa,
    completeFirebaseMfa,
    mfaPending: true,
    mfaSessionToken: 'mfa-token-1',
    mfaMethods: ['totp'],
    mfaDefaultMethod: 'totp',
    ...authState,
  }),
}))

vi.mock('@/api/client', () => ({
  default: { post: apiPost },
  setAccessToken: vi.fn(),
}))

import { MfaVerify } from './MfaVerify'

function LocationProbe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname}</div>
}

function renderMfa() {
  render(
    <MemoryRouter initialEntries={['/mfa-verify']}>
      <Routes>
        <Route path="/mfa-verify" element={<MfaVerify />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  authState = {}
  apiPost.mockResolvedValue({ data: {} })
})

describe('MfaVerify — structure', () => {
  it('renders the heading and the six OTP inputs', () => {
    renderMfa()
    expect(screen.getByRole('heading', { name: 'Two-factor authentication' })).toBeInTheDocument()
    for (let i = 1; i <= 6; i++) {
      expect(screen.getByLabelText(`Digit ${i}`)).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Verify' })).toBeInTheDocument()
  })
})

describe('MfaVerify — happy path', () => {
  it('submits the 6-digit code via completeMfa and navigates to /', async () => {
    const user = userEvent.setup()
    completeMfa.mockResolvedValue(undefined)
    renderMfa()

    const code = ['1', '2', '3', '4', '5', '6']
    for (let i = 0; i < 6; i++) {
      await user.type(screen.getByLabelText(`Digit ${i + 1}`), code[i])
    }
    await user.click(screen.getByRole('button', { name: 'Verify' }))

    expect(completeMfa).toHaveBeenCalledWith('123456', 'totp')
    expect(await screen.findByTestId('location')).toHaveTextContent('/')
  })

  it('shows a validation error when fewer than 6 digits are entered', async () => {
    const user = userEvent.setup()
    renderMfa()
    await user.type(screen.getByLabelText('Digit 1'), '1')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByText('Please enter all 6 digits')).toBeInTheDocument()
    expect(completeMfa).not.toHaveBeenCalled()
  })
})

describe('MfaVerify — gating', () => {
  it('redirects to /login when there is no pending MFA', async () => {
    authState = { mfaPending: false }
    renderMfa()
    expect(await screen.findByTestId('location')).toHaveTextContent('/login')
  })
})
