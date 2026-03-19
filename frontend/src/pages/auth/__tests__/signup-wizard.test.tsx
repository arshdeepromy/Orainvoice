import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Unit tests for SignupWizard component.
 * Validates: Requirements 2.1, 2.3, 2.5, 2.6, 3.4, 3.5
 */

// --- Hoisted mocks ---

const { mockConfirmCardPayment } = vi.hoisted(() => ({
  mockConfirmCardPayment: vi.fn(),
}))

vi.mock('@stripe/stripe-js', () => ({
  loadStripe: vi.fn(() =>
    Promise.resolve({
      confirmCardPayment: mockConfirmCardPayment,
      elements: vi.fn(),
    }),
  ),
}))

vi.mock('@stripe/react-stripe-js', () => ({
  Elements: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="stripe-elements">{children}</div>
  ),
  CardElement: () => <div data-testid="stripe-card-element">Card Element</div>,
  useStripe: () => ({
    confirmCardPayment: mockConfirmCardPayment,
  }),
  useElements: () => ({
    getElement: () => ({ mock: true }),
  }),
}))

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import { SignupWizard } from '../SignupWizard'

// --- Helpers ---

const mockGet = apiClient.get as ReturnType<typeof vi.fn>
const mockPost = apiClient.post as ReturnType<typeof vi.fn>

const paidPlan = {
  id: 'plan-pro',
  name: 'Professional',
  monthly_price_nzd: 49,
  trial_duration: 0,
  trial_duration_unit: 'days',
}

const trialPlan = {
  id: 'plan-trial',
  name: 'Starter',
  monthly_price_nzd: 29,
  trial_duration: 14,
  trial_duration_unit: 'days',
}

function setupDefaultMocks() {
  // GET /auth/stripe-publishable-key
  mockGet.mockImplementation((url: string) => {
    if (url === '/auth/stripe-publishable-key') {
      return Promise.resolve({ data: { publishable_key: 'pk_test_123' } })
    }
    if (url === '/auth/plans') {
      return Promise.resolve({ data: { plans: [paidPlan, trialPlan] } })
    }
    return Promise.resolve({ data: {} })
  })
}

/** Build a paid-plan signup response */
function paidSignupResponse() {
  return {
    data: {
      message: 'Pending signup created',
      requires_payment: true,
      pending_signup_id: 'ps-123',
      stripe_client_secret: 'pi_secret_abc',
      payment_amount_cents: 4900,
      plan_name: 'Professional',
      admin_email: 'user@example.com',
    },
  }
}

/** Build a trial-plan signup response */
function trialSignupResponse() {
  return {
    data: {
      message: 'Signup successful',
      requires_payment: false,
      payment_amount_cents: 0,
      organisation_id: 'org-1',
      admin_email: 'user@example.com',
      plan_name: 'Starter',
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  setupDefaultMocks()
})

// --- Helper to fill and submit the signup form ---

async function fillAndSubmitForm(user: ReturnType<typeof userEvent.setup>) {
  // Wait for plans to load
  await waitFor(() => {
    expect(screen.getByText('Professional')).toBeInTheDocument()
  })

  // Fill form fields
  await user.type(screen.getByLabelText(/organisation name/i), 'Test Org')
  await user.type(screen.getByLabelText(/first name/i), 'Jane')
  await user.type(screen.getByLabelText(/last name/i), 'Doe')
  await user.type(screen.getByLabelText(/email/i), 'user@example.com')

  const passwordFields = screen.getAllByLabelText(/password/i)
  await user.type(passwordFields[0], 'Test1234!')
  await user.type(passwordFields[1], 'Test1234!')

  return user
}

async function selectPlan(user: ReturnType<typeof userEvent.setup>, planName: string) {
  const planLabel = screen.getByText(planName).closest('label')!
  const radio = within(planLabel).getByRole('radio')
  await user.click(radio)
}

// --- Tests ---

describe('SignupWizard', () => {
  it('renders step indicator with 3 steps by default', async () => {
    render(<SignupWizard />)

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: /signup progress/i })).toBeInTheDocument()
    })

    // Default is 3 steps (paid plan assumed)
    expect(screen.getByText('Account details')).toBeInTheDocument()
    expect(screen.getByText('Payment')).toBeInTheDocument()
    expect(screen.getByText('Confirmation')).toBeInTheDocument()
  })

  it('shows SignupForm on initial render', async () => {
    render(<SignupWizard />)

    await waitFor(() => {
      expect(screen.getByText('Create your account')).toBeInTheDocument()
    })
  })

  it('transitions to payment step after paid plan signup', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(paidSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Professional')

    // Verify CAPTCHA
    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    // Submit form
    await user.click(screen.getByRole('button', { name: /sign up/i }))

    // Should transition to payment step
    await waitFor(() => {
      expect(screen.getByText('Complete payment')).toBeInTheDocument()
    })
  })

  it('transitions directly to confirmation step for trial plan signup', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(trialSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Starter')

    // Verify CAPTCHA
    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    // Submit form
    await user.click(screen.getByRole('button', { name: /start free trial/i }))

    // Should skip payment and go to confirmation
    await waitFor(() => {
      expect(screen.getByText('Check your email')).toBeInTheDocument()
    })
  })

  it('shows 2 steps in indicator for trial plans after signup', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(trialSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Starter')

    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /start free trial/i }))

    // After trial signup, step indicator should show 2 steps (no Payment step)
    await waitFor(() => {
      expect(screen.getByText('Check your email')).toBeInTheDocument()
    })

    // Should NOT have a "Payment" step label
    expect(screen.queryByText('Payment')).not.toBeInTheDocument()
    // Should have Account details and Confirmation
    expect(screen.getByText('Account details')).toBeInTheDocument()
    expect(screen.getByText('Confirmation')).toBeInTheDocument()
  })

  it('payment step displays plan name and formatted amount', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(paidSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Professional')

    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /sign up/i }))

    // Wait for payment step
    await waitFor(() => {
      expect(screen.getByText('Complete payment')).toBeInTheDocument()
    })

    // Verify plan name and amount are displayed within the payment step
    const paymentStep = screen.getByTestId('payment-step')
    const planNameMatches = within(paymentStep).getAllByText(/professional/i)
    expect(planNameMatches.length).toBeGreaterThanOrEqual(1)
    const amountMatches = within(paymentStep).getAllByText(/\$49\.00 NZD/)
    expect(amountMatches.length).toBeGreaterThanOrEqual(1)
  })

  it('displays Stripe error message on payment failure', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(paidSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      return Promise.resolve({ data: {} })
    })

    mockConfirmCardPayment.mockResolvedValue({
      error: { message: 'Your card was declined.' },
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Professional')

    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /sign up/i }))

    // Wait for payment step
    await waitFor(() => {
      expect(screen.getByText('Complete payment')).toBeInTheDocument()
    })

    // Click pay button
    await user.click(screen.getByRole('button', { name: /pay.*and activate/i }))

    // Should display the Stripe error inline
    await waitFor(() => {
      expect(screen.getByText('Your card was declined.')).toBeInTheDocument()
    })

    // Should still be on payment step (not navigated away)
    expect(screen.getByText('Complete payment')).toBeInTheDocument()
  })

  it('shows retry button when confirm-payment backend call fails', async () => {
    mockPost.mockImplementation((url: string, body?: unknown) => {
      if (url === '/auth/signup') return Promise.resolve(paidSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      if (url === '/auth/signup/confirm-payment') {
        return Promise.reject({
          response: { data: { detail: 'Server error. Please try again.' } },
        })
      }
      return Promise.resolve({ data: {} })
    })

    // Stripe payment succeeds
    mockConfirmCardPayment.mockResolvedValue({
      paymentIntent: { id: 'pi_test_123', status: 'succeeded' },
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Professional')

    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /sign up/i }))

    await waitFor(() => {
      expect(screen.getByText('Complete payment')).toBeInTheDocument()
    })

    // Click pay button — Stripe succeeds but confirm-payment fails
    await user.click(screen.getByRole('button', { name: /pay.*and activate/i }))

    // Should show error and a Retry button
    await waitFor(() => {
      expect(screen.getByText('Server error. Please try again.')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('transitions to confirmation after payment success', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(paidSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      if (url === '/auth/signup/confirm-payment') {
        return Promise.resolve({ data: { message: 'Account created' } })
      }
      return Promise.resolve({ data: {} })
    })

    mockConfirmCardPayment.mockResolvedValue({
      paymentIntent: { id: 'pi_test_123', status: 'succeeded' },
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Professional')

    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /sign up/i }))

    await waitFor(() => {
      expect(screen.getByText('Complete payment')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /pay.*and activate/i }))

    // Should transition to confirmation step
    await waitFor(() => {
      expect(screen.getByText('Check your email')).toBeInTheDocument()
    })

    // Confirmation shows the user's email
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
  })

  it('resets to form with warning message when session expires on payment step', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(paidSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      if (url === '/auth/signup/confirm-payment') {
        return Promise.reject({
          response: { data: { detail: 'Invalid or expired signup session. Please start over.' } },
        })
      }
      return Promise.resolve({ data: {} })
    })

    mockConfirmCardPayment.mockResolvedValue({
      paymentIntent: { id: 'pi_test_123', status: 'succeeded' },
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Professional')

    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /sign up/i }))

    await waitFor(() => {
      expect(screen.getByText('Complete payment')).toBeInTheDocument()
    })

    // Click pay — Stripe succeeds but confirm-payment returns session expired
    await user.click(screen.getByRole('button', { name: /pay.*and activate/i }))

    // Should reset to form step and show the expiry warning
    await waitFor(() => {
      expect(screen.getByText('Create your account')).toBeInTheDocument()
    })

    expect(screen.getByText(/invalid or expired signup session/i)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('confirmation step shows user email', async () => {
    mockPost.mockImplementation((url: string) => {
      if (url === '/auth/signup') return Promise.resolve(trialSignupResponse())
      if (url === '/auth/verify-captcha') return Promise.resolve({ data: {} })
      return Promise.resolve({ data: {} })
    })

    const user = userEvent.setup()
    render(<SignupWizard />)

    await fillAndSubmitForm(user)
    await selectPlan(user, 'Starter')

    const captchaInput = screen.getByPlaceholderText('Enter code')
    await user.type(captchaInput, 'AB12CD')
    await user.click(screen.getByRole('button', { name: /verify/i }))

    await waitFor(() => {
      expect(screen.getByText(/verified/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /start free trial/i }))

    await waitFor(() => {
      expect(screen.getByText('Check your email')).toBeInTheDocument()
    })

    expect(screen.getByText('user@example.com')).toBeInTheDocument()
  })
})
