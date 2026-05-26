/**
 * Unit tests for PublicPaymentScreen — partial-payment banner and label.
 *
 * Validates: Requirements 6.3, 6.5
 *
 * Scenarios covered:
 * - When `is_partial_payment` is true, the partial banner appears and the
 *   "Amount Due" label is replaced with "Amount Due (Partial)".
 * - When `is_partial_payment` is false (default), the banner is absent and
 *   the label remains "Amount Due".
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

/* ------------------------------------------------------------------ */
/*  Mocks (must be declared before imports that use them)              */
/* ------------------------------------------------------------------ */

vi.mock('react-router-dom', () => ({
  useParams: () => ({ token: 'tok_test' }),
}))

// Konsta UI primitives — render plain divs so the test focuses on the
// content and doesn't depend on Konsta's internals.
vi.mock('konsta/react', () => ({
  Page: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  Block: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  Card: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  Button: ({ children, ...props }: any) => (
    <button onClick={props.onClick} disabled={props.disabled} type={props.type}>
      {children}
    </button>
  ),
}))

vi.mock('@stripe/stripe-js', () => ({
  loadStripe: vi.fn(() =>
    Promise.resolve({
      confirmPayment: vi.fn(),
      elements: vi.fn(),
    }),
  ),
}))

vi.mock('@stripe/react-stripe-js', () => ({
  Elements: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="stripe-elements">{children}</div>
  ),
  PaymentElement: () => <div data-testid="stripe-payment-element">PaymentElement</div>,
  useStripe: () => ({ confirmPayment: vi.fn() }),
  useElements: () => ({ getElement: () => ({ mock: true }) }),
}))

const { mockAxiosGet, mockAxiosPost } = vi.hoisted(() => ({
  mockAxiosGet: vi.fn(),
  mockAxiosPost: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    get: mockAxiosGet,
    post: mockAxiosPost,
    isAxiosError: () => false,
  },
}))

/* ------------------------------------------------------------------ */
/*  Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import PublicPaymentScreen from '../PublicPaymentScreen'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function buildPaymentPageData(overrides: Record<string, unknown> = {}) {
  return {
    org_name: 'Test Workshop',
    org_logo_url: null,
    org_primary_colour: '#2563eb',
    invoice_number: 'INV-2026-001',
    issue_date: '2026-01-10',
    due_date: '2026-02-10',
    currency: 'NZD',
    line_items: [],
    subtotal: 174,
    gst_amount: 26,
    total: 200,
    amount_paid: 0,
    balance_due: 200,
    status: 'issued',
    client_secret: 'pi_test_123_secret_abc',
    connected_account_id: 'acct_test_123',
    publishable_key: 'pk_test_123',
    is_paid: false,
    is_payable: true,
    error_message: null,
    surcharge_enabled: false,
    surcharge_rates: {},
    is_partial_payment: false,
    ...overrides,
  }
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('PublicPaymentScreen (mobile) — partial-payment banner and label', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the partial-payment banner and "Amount Due (Partial)" label when is_partial_payment is true', async () => {
    mockAxiosGet.mockResolvedValue({
      data: buildPaymentPageData({ is_partial_payment: true, balance_due: 100 }),
    })

    render(<PublicPaymentScreen />)

    await waitFor(() => {
      expect(screen.getByTestId('stripe-payment-element')).toBeInTheDocument()
    })

    // Banner text is present
    expect(
      screen.getByText(
        /You are paying a partial amount of .* Please contact the business if you intended to pay the full balance/i,
      ),
    ).toBeInTheDocument()

    // Label reads "Amount Due (Partial)"
    expect(screen.getByText('Amount Due (Partial)')).toBeInTheDocument()

    // The plain "Amount Due" label is NOT shown alongside it
    expect(screen.queryByText(/^Amount Due$/)).not.toBeInTheDocument()
  })

  it('hides the banner and uses the plain "Amount Due" label when is_partial_payment is false (default)', async () => {
    mockAxiosGet.mockResolvedValue({
      data: buildPaymentPageData({ is_partial_payment: false }),
    })

    render(<PublicPaymentScreen />)

    await waitFor(() => {
      expect(screen.getByTestId('stripe-payment-element')).toBeInTheDocument()
    })

    expect(
      screen.queryByText(/You are paying a partial amount of/i),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/^Amount Due$/)).toBeInTheDocument()
    expect(screen.queryByText('Amount Due (Partial)')).not.toBeInTheDocument()
  })

  it('hides the banner when is_partial_payment field is omitted from the response', async () => {
    const data = buildPaymentPageData()
    delete (data as { is_partial_payment?: boolean }).is_partial_payment
    mockAxiosGet.mockResolvedValue({ data })

    render(<PublicPaymentScreen />)

    await waitFor(() => {
      expect(screen.getByTestId('stripe-payment-element')).toBeInTheDocument()
    })

    expect(
      screen.queryByText(/You are paying a partial amount of/i),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/^Amount Due$/)).toBeInTheDocument()
  })
})
