/**
 * Unit tests for QrPaymentWaitingPopup.
 *
 * Validates: Requirements 9.1, 9.3, 9.4
 */

import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { status: 'open', payment_intent_id: null } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import apiClient from '@/api/client'
import { QrPaymentWaitingPopup } from './QrPaymentWaitingPopup'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const defaultProps = {
  sessionId: 'cs_test_abc123',
  amount: 125.5,
  invoiceNumber: 'INV-2026-001',
  onClose: vi.fn(),
  onPaymentComplete: vi.fn(),
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('QrPaymentWaitingPopup', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.clearAllMocks()
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { status: 'open', payment_intent_id: null },
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders spinner and "Waiting for payment..." text initially', async () => {
    await act(async () => {
      render(<QrPaymentWaitingPopup {...defaultProps} />)
    })

    // Spinner is present (the animate-spin SVG)
    const spinner = document.querySelector('.animate-spin')
    expect(spinner).toBeInTheDocument()

    // Waiting text
    expect(screen.getByText('Waiting for payment...')).toBeInTheDocument()

    // Amount and invoice number displayed
    expect(screen.getByText('$125.50')).toBeInTheDocument()
    expect(screen.getByText('INV-2026-001')).toBeInTheDocument()

    // Dialog role
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-label', 'Waiting for payment')
  })

  it('close button calls onClose without cancelling the payment', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

    await act(async () => {
      render(<QrPaymentWaitingPopup {...defaultProps} />)
    })

    const closeButton = screen.getByRole('button', { name: /close/i })
    expect(closeButton).toBeInTheDocument()

    await user.click(closeButton)

    // onClose should be called
    expect(defaultProps.onClose).toHaveBeenCalledTimes(1)

    // No expire/cancel API call should have been made
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('shows green tick and "Payment received" when status poll returns "complete"', async () => {
    // First poll returns open, second returns complete
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { status: 'open', payment_intent_id: null } })
      .mockResolvedValueOnce({ data: { status: 'complete', payment_intent_id: 'pi_test_123' } })

    await act(async () => {
      render(<QrPaymentWaitingPopup {...defaultProps} />)
    })

    // Initially shows waiting state
    expect(screen.getByText('Waiting for payment...')).toBeInTheDocument()

    // Advance past the 3-second poll interval to trigger second poll
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })

    // Should now show success state with green tick
    await waitFor(() => {
      expect(screen.getByText(/Payment received/)).toBeInTheDocument()
    })

    // Verify the amount is shown in the success message
    expect(screen.getByText(/125\.50/)).toBeInTheDocument()

    // Dialog should now have the "Payment received" aria-label
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-label', 'Payment received')

    // After 3 seconds, onPaymentComplete should be called
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })

    expect(defaultProps.onPaymentComplete).toHaveBeenCalledTimes(1)
  })

  it('polls the session status endpoint every 3 seconds', async () => {
    await act(async () => {
      render(<QrPaymentWaitingPopup {...defaultProps} />)
    })

    // Initial poll fires immediately
    expect(apiClient.get).toHaveBeenCalledWith(
      `/payments/qr-session/${defaultProps.sessionId}/status`,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    const initialCallCount = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls.length

    // Advance 3 seconds for next poll
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })

    expect((apiClient.get as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(initialCallCount)
  })
})
