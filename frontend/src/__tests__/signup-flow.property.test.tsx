import { render, screen, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as fc from 'fast-check'

// Feature: public-signup-flow, Property 3: Signup page error message passthrough
// **Validates: Requirements 1.4, 2.4**

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

let mockSearchParams = new URLSearchParams('token=test-token')

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

function mockPlansSuccess() {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { plans: mockPlans },
  })
}

function mockSignup400(detail: string) {
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
    response: { status: 400, data: { detail } },
  })
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Organisation name'), 'My Business')
  await user.type(screen.getByLabelText('Email address'), 'admin@example.com')
  await user.type(screen.getByLabelText('First name'), 'Jane')
  await user.type(screen.getByLabelText('Last name'), 'Smith')
  await user.selectOptions(screen.getByLabelText('Plan'), 'plan-starter')
  await user.click(screen.getByRole('button', { name: 'Sign up' }))
}

describe('Property 3: Signup page error message passthrough', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it(
    'displays the exact API error detail message for any non-empty string',
    async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.trim().length > 0),
          async (errorMessage) => {
            vi.clearAllMocks()
            mockPlansSuccess()
            mockSignup400(errorMessage)

            const user = userEvent.setup()
            const { unmount } = render(<Signup />)

            await screen.findByLabelText('Organisation name')
            await fillAndSubmit(user)

            await waitFor(() => {
              expect(screen.getByText(errorMessage)).toBeInTheDocument()
            })

            unmount()
          },
        ),
        { numRuns: 10 },
      )
    },
    60_000,
  )
})

// Feature: public-signup-flow, Property 7: Plan display completeness
// **Validates: Requirements 6.2**

describe('Property 7: Plan display completeness', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const planArb = fc.record({
    id: fc.stringMatching(/^[a-z][a-z0-9-]{0,19}$/).filter((s) => s.length > 0),
    name: fc
      .string({ minLength: 1, maxLength: 50 })
      .filter((s) => s.trim().length > 0),
    monthly_price_nzd: fc.integer({ min: 1, max: 9999 }),
  })

  it(
    'renders every plan name and formatted price for any non-empty plan list',
    async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.array(planArb, { minLength: 1, maxLength: 5 }).chain((plans) => {
            // Ensure unique ids
            const seen = new Set<string>()
            const unique = plans.filter((p) => {
              if (seen.has(p.id)) return false
              seen.add(p.id)
              return true
            })
            return unique.length > 0 ? fc.constant(unique) : fc.constant([plans[0]] as typeof plans)
          }),
          async (plans: Array<{ id: string; name: string; monthly_price_nzd: number }>) => {
            vi.clearAllMocks()
            ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
              data: { plans },
            })

            const { unmount } = render(<Signup />)

            // Wait for plans to load and form to appear
            await waitFor(() => {
              expect(screen.getByLabelText('Plan')).toBeInTheDocument()
            })

            const selectEl = screen.getByLabelText('Plan')

            for (const plan of plans) {
              // Each plan should appear as an option with "Name — $Price/mo"
              const expectedText = `${plan.name} — $${plan.monthly_price_nzd}/mo`
              const options = Array.from(selectEl.querySelectorAll('option'))
              const found = options.some((opt) => opt.textContent === expectedText)
              expect(found).toBe(true)
            }

            unmount()
          },
        ),
        { numRuns: 15 },
      )
    },
    60_000,
  )
})


// Feature: public-signup-flow, Property 4: Verify page error message passthrough
// **Validates: Requirements 3.6**

describe('Property 4: Verify page error message passthrough', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams('token=valid-token-abc')
  })

  it(
    'displays the exact API error detail message for any non-empty string',
    async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.trim().length > 0),
          async (errorMessage) => {
            cleanup()
            vi.clearAllMocks()
            mockSearchParams = new URLSearchParams('token=valid-token-abc')

            ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
              response: { status: 400, data: { detail: errorMessage } },
            })

            const user = userEvent.setup()
            render(<VerifyEmail />)

            await user.type(screen.getByLabelText('Password'), 'SecurePass10')
            await user.type(screen.getByLabelText('Confirm password'), 'SecurePass10')
            await user.click(screen.getByRole('button', { name: 'Set password' }))

            await waitFor(() => {
              expect(screen.getByText(errorMessage)).toBeInTheDocument()
            })

            cleanup()
          },
        ),
        { numRuns: 10 },
      )
    },
    60_000,
  )
})
