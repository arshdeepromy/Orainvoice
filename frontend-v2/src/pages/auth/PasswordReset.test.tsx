import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

/**
 * PasswordResetRequest + PasswordResetComplete tests (Task 14).
 *
 * The api client is mocked so the reset-request / reset POSTs resolve without a
 * server. Covers the anti-enumeration confirmation (Req 4.4) on request, and
 * the verbatim validation (≥12 chars, match) + POST payload on complete.
 */

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }))

let searchParamsString = ''

vi.mock('@/api/client', () => ({
  default: { post: apiPost },
  setAccessToken: vi.fn(),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useSearchParams: () => [new URLSearchParams(searchParamsString)],
  }
})

import { PasswordResetRequest } from './PasswordResetRequest'
import { PasswordResetComplete } from './PasswordResetComplete'

beforeEach(() => {
  vi.clearAllMocks()
  searchParamsString = ''
  apiPost.mockResolvedValue({ data: {} })
})

describe('PasswordResetRequest', () => {
  it('posts the email and shows the check-your-email confirmation', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><PasswordResetRequest /></MemoryRouter>)

    await user.type(screen.getByLabelText('Email address'), 'arsh@workshop.co.nz')
    await user.click(screen.getByRole('button', { name: 'Send reset link' }))

    expect(apiPost).toHaveBeenCalledWith('/auth/password/reset-request', { email: 'arsh@workshop.co.nz' })
    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument()
  })

  it('shows the same confirmation even when the request fails (anti-enumeration)', async () => {
    const user = userEvent.setup()
    apiPost.mockRejectedValue({ response: { status: 404 } })
    render(<MemoryRouter><PasswordResetRequest /></MemoryRouter>)

    await user.type(screen.getByLabelText('Email address'), 'missing@workshop.co.nz')
    await user.click(screen.getByRole('button', { name: 'Send reset link' }))

    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument()
  })
})

describe('PasswordResetComplete', () => {
  it('rejects passwords shorter than 12 characters without calling the API', async () => {
    searchParamsString = 'token=reset-token-1'
    const user = userEvent.setup()
    render(<MemoryRouter><PasswordResetComplete /></MemoryRouter>)

    await user.type(screen.getByLabelText('New password'), 'short')
    await user.type(screen.getByLabelText('Confirm password'), 'short')
    await user.click(screen.getByRole('button', { name: 'Reset password' }))

    expect(await screen.findByText('Password must be at least 12 characters')).toBeInTheDocument()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('posts token + new_password and shows the success state', async () => {
    searchParamsString = 'token=reset-token-1'
    const user = userEvent.setup()
    render(<MemoryRouter><PasswordResetComplete /></MemoryRouter>)

    await user.type(screen.getByLabelText('New password'), 'SuperSecret123!')
    await user.type(screen.getByLabelText('Confirm password'), 'SuperSecret123!')
    await user.click(screen.getByRole('button', { name: 'Reset password' }))

    expect(apiPost).toHaveBeenCalledWith('/auth/password/reset', {
      token: 'reset-token-1',
      new_password: 'SuperSecret123!',
    })
    expect(await screen.findByRole('heading', { name: 'Password updated' })).toBeInTheDocument()
  })
})
