/**
 * Unit tests for InvoicePaymentPage — partial-payment banner and label.
 *
 * Validates: Requirements 6.3, 6.5
 *
 * Scenarios covered:
 * - When `is_partial_payment` is true, banner text appears and the
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

vi.mock('@stripe/stripe-js', () => ({
  loadStripe: vi.fn(() =>
    Promise.resolve({
      // The minimum Stripe surface InvoicePaymentPage actually touches
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

import InvoicePaymentPage from '../InvoicePaymentPage'

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

describe('InvoicePaymentPage — partial-payment banner and label', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the partial-payment banner and "Amount Due (Partial)" label when is_partial_payment is true', async () => {
    mockAxiosGet.mockResolvedValue({
      data: buildPaymentPageData({ is_partial_payment: true, balance_due: 100 }),
    })

    render(<InvoicePaymentPage />)

    // Wait for the payment form to render (proxy: PaymentElement appears)
    await waitFor(() => {
      expect(screen.getByTestId('stripe-payment-element')).toBeInTheDocument()
    })

    // Banner text is present
    expect(
      screen.getByText(
        /You are paying a partial amount of .* Please contact the business if you intended to pay the full balance/i,
      ),
    ).toBeInTheDocument()

    // Label reads "Amount Due (Partial)" when partial flag is set
    expect(screen.getByText('Amount Due (Partial)')).toBeInTheDocument()

    // The plain "Amount Due" label is NOT shown alongside it
    expect(screen.queryByText(/^Amount Due$/)).not.toBeInTheDocument()
  })

  it('hides the banner and uses the plain "Amount Due" label when is_partial_payment is false (default)', async () => {
    mockAxiosGet.mockResolvedValue({
      data: buildPaymentPageData({ is_partial_payment: false }),
    })

    render(<InvoicePaymentPage />)

    await waitFor(() => {
      expect(screen.getByTestId('stripe-payment-element')).toBeInTheDocument()
    })

    // No partial banner
    expect(
      screen.queryByText(
        /You are paying a partial amount of .* Please contact the business if you intended to pay the full balance/i,
      ),
    ).not.toBeInTheDocument()

    // Label reads "Amount Due", not "Amount Due (Partial)"
    expect(screen.getByText(/^Amount Due$/)).toBeInTheDocument()
    expect(screen.queryByText('Amount Due (Partial)')).not.toBeInTheDocument()
  })

  it('hides the banner when is_partial_payment field is omitted from the response', async () => {
    // Older backend payloads may omit the field entirely — frontend defaults it to false.
    const data = buildPaymentPageData()
    delete (data as { is_partial_payment?: boolean }).is_partial_payment
    mockAxiosGet.mockResolvedValue({ data })

    render(<InvoicePaymentPage />)

    await waitFor(() => {
      expect(screen.getByTestId('stripe-payment-element')).toBeInTheDocument()
    })

    expect(
      screen.queryByText(/You are paying a partial amount of/i),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/^Amount Due$/)).toBeInTheDocument()
  })
})
