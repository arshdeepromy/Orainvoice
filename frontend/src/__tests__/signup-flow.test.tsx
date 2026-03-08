import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 6.1, 6.2, 6.3, 6.4
 */

// --- Mocks ---

const { mockConfirmCardSetup } = vi.hoisted(() => ({
  mockConfirmCardSetup: vi.fn(),
}))

vi.mock('@stripe/stripe-js', () => ({
  loadStripe: vi.fn(() =>
    Promise.resolve({
      confirmCardSetup: mockConfirmCardSetup,
      elements: vi.fn(),
    }),
  ),
}))

vi.mock('@stripe/react-stripe-js', () => ({
  Elements: ({ children }: { children: React.ReactNode }) => <div data-testid="stripe-elements">{children}</div>,
  CardElement: () => <div data-testid="stripe-card-element">Card Element</div>,
  useStripe: () => ({
    confirmCardSetup: mockConfirmCardSetup,
  }),
  useElements: () => ({
    getElement: () => ({ mock: true }),
  }),
}))

const { mockSetAccessToken, mockNavigate } = vi.hoisted(() => ({
  mockSetAccessToken: vi.fn(),
  mockNavigate: vi.fn(),
}))

let mockSearchParams = new URLSearchParams()

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
    setAccessToken: mockSetAccessToken,
  }
})

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useSearchParams: () => [mockSearchParams],
  }
})

import apiClient from '@/api/client'
import { Signup } from '../pages/auth/Signup'
import { VerifyEmail } from '../pages/auth/VerifyEmail'

const mockPlans = [
  { id: 'plan-starter', name: 'Starter', monthly_price_nzd: 29 },
  { id: 'plan-pro', name: 'Professional', monthly_price_nzd: 79 },
]

function mockPlansSuccess(plans = mockPlans) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { plans },
  })
}

function mockPlansEmpty() {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { plans: [] },
  })
}

function mockPlansError() {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
}

function mockSignupSuccess() {
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: {
      message: 'Signup successful',
      organisation_id: 'org-1',
      organisation_name: 'Test Org',
      plan_id: 'plan-starter',
      admin_user_id: 'user-1',
      admin_email: 'test@example.com',
      trial_ends_at: '2025-08-01T00:00:00Z',
      stripe_setup_intent_client_secret: 'seti_secret_123',
      signup_token: 'token_abc',
    },
  })
}

function mockSignup400(detail: string) {
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
    response: { status: 400, data: { detail } },
  })
}

async function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Organisation name'), 'My Business')
  await user.type(screen.getByLabelText('Email address'), 'admin@example.com')
  await user.type(screen.getByLabelText('First name'), 'Jane')
  await user.type(screen.getByLabelText('Last name'), 'Smith')
  await user.selectOptions(screen.getByLabelText('Plan'), 'plan-starter')
}

describe('SignupPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Req 1.1: Form fields render correctly
  it('renders all form fields when plans are loaded', async () => {
    mockPlansSuccess()
    render(<Signup />)

    expect(await screen.findByLabelText('Organisation name')).toBeInTheDocument()
    expect(screen.getByLabelText('Email address')).toBeInTheDocument()
    expect(screen.getByLabelText('First name')).toBeInTheDocument()
    expect(screen.getByLabelText('Last name')).toBeInTheDocument()
    expect(screen.getByLabelText('Plan')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign up' })).toBeInTheDocument()
  })

  // Req 6.1, 6.2: Plan selector renders fetched plans
  it('renders fetched plans in the plan selector', async () => {
    mockPlansSuccess()
    render(<Signup />)

    const select = await screen.findByLabelText('Plan')
    expect(select).toBeInTheDocument()

    const options = select.querySelectorAll('option')
    // "Select a plan" + 2 plans
    expect(options).toHaveLength(3)
    expect(options[1].textContent).toContain('Starter')
    expect(options[1].textContent).toContain('$29')
    expect(options[2].textContent).toContain('Professional')
    expect(options[2].textContent).toContain('$79')
  })

  // Req 1.6, 1.7, 1.8, 6.3: Form validation prevents submission with invalid data
  it('shows validation errors when submitting empty form', async () => {
    mockPlansSuccess()
    const user = userEvent.setup()
    render(<Signup />)

    await screen.findByLabelText('Organisation name')
    await user.click(screen.getByRole('button', { name: 'Sign up' }))

    expect(await screen.findByText(/organisation name must be/i)).toBeInTheDocument()
    expect(screen.getByText(/valid email/i)).toBeInTheDocument()
    expect(screen.getByText(/first name must be/i)).toBeInTheDocument()
    expect(screen.getByText(/last name must be/i)).toBeInTheDocument()
    expect(screen.getByText('Please select a plan')).toBeInTheDocument()
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  // Req 1.2: API call on valid submission
  it('calls signup API with correct payload on valid submission', async () => {
    mockPlansSuccess()
    mockSignupSuccess()
    const user = userEvent.setup()
    render(<Signup />)

    await screen.findByLabelText('Organisation name')
    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'Sign up' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/auth/signup', {
        org_name: 'My Business',
        admin_email: 'admin@example.com',
        admin_first_name: 'Jane',
        admin_last_name: 'Smith',
        plan_id: 'plan-starter',
      })
    })
  })

  // Req 1.3: Transition to Stripe step on success
  it('transitions to Stripe card collection step on successful signup', async () => {
    mockPlansSuccess()
    mockSignupSuccess()
    const user = userEvent.setup()
    render(<Signup />)

    await screen.findByLabelText('Organisation name')
    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'Sign up' }))

    expect(await screen.findByText('Payment details')).toBeInTheDocument()
    expect(screen.getByTestId('stripe-elements')).toBeInTheDocument()
    expect(screen.getByTestId('stripe-card-element')).toBeInTheDocument()
  })

  // Req 1.4: Error display on API 400
  it('displays API error message on 400 response', async () => {
    mockPlansSuccess()
    mockSignup400('Organisation name already taken')
    const user = userEvent.setup()
    render(<Signup />)

    await screen.findByLabelText('Organisation name')
    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'Sign up' }))

    expect(await screen.findByText('Organisation name already taken')).toBeInTheDocument()
  })

  // Req 1.5: Loading state during submission
  it('disables submit button during submission', async () => {
    mockPlansSuccess()
    // Make the post hang to observe loading state
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()
    render(<Signup />)

    await screen.findByLabelText('Organisation name')
    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'Sign up' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sign up' })).toBeDisabled()
    })
  })

  // Req 6.4: Empty plans shows unavailable message
  it('shows unavailable message when no plans are returned', async () => {
    mockPlansEmpty()
    render(<Signup />)

    expect(await screen.findByText(/signup is temporarily unavailable/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign up' })).not.toBeInTheDocument()
  })

  // Plans fetch error shows retry
  it('shows error and retry button when plans fetch fails', async () => {
    mockPlansError()
    render(<Signup />)

    expect(await screen.findByText(/unable to load plans/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  // Loading spinner while fetching plans
  it('shows loading spinner while fetching plans', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<Signup />)

    expect(screen.getByRole('status', { name: 'Loading plans' })).toBeInTheDocument()
  })
})

/**
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
 */
describe('VerifyEmailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams('token=valid-token-123')
  })

  // Req 3.1: Password fields render
  it('renders password and confirm password fields when token is present', () => {
    render(<VerifyEmail />)

    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set password' })).toBeInTheDocument()
  })

  // Req 3.3: Missing token shows error
  it('shows invalid link error when token is missing', () => {
    mockSearchParams = new URLSearchParams()
    render(<VerifyEmail />)

    expect(screen.getByText('This verification link is invalid.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  // Req 3.2, 3.4: API call with token and password
  it('calls verify-email API with token and password on valid submission', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { access_token: 'at_123', refresh_token: 'rt_456', token_type: 'bearer', message: 'ok' },
    })
    const user = userEvent.setup()
    render(<VerifyEmail />)

    await user.type(screen.getByLabelText('Password'), 'SecurePass10')
    await user.type(screen.getByLabelText('Confirm password'), 'SecurePass10')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/auth/verify-email', {
        token: 'valid-token-123',
        password: 'SecurePass10',
      })
    })
  })

  // Req 3.5: Token storage and redirect on success
  it('stores tokens and redirects to /setup on success', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { access_token: 'at_123', refresh_token: 'rt_456', token_type: 'bearer', message: 'ok' },
    })
    const user = userEvent.setup()
    render(<VerifyEmail />)

    await user.type(screen.getByLabelText('Password'), 'SecurePass10')
    await user.type(screen.getByLabelText('Confirm password'), 'SecurePass10')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    await waitFor(() => {
      expect(mockSetAccessToken).toHaveBeenCalledWith('at_123')
      expect(mockNavigate).toHaveBeenCalledWith('/setup')
    })
  })

  // Req 3.6: Error display on API 400
  it('displays error message on 400 response', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { status: 400, data: { detail: 'Token has expired' } },
    })
    const user = userEvent.setup()
    render(<VerifyEmail />)

    await user.type(screen.getByLabelText('Password'), 'SecurePass10')
    await user.type(screen.getByLabelText('Confirm password'), 'SecurePass10')
    await user.click(screen.getByRole('button', { name: 'Set password' }))

    expect(await screen.findByText('Token has expired')).toBeInTheDocument()
  })
})
