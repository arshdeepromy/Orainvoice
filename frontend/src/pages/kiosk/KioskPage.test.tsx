/**
 * Unit tests for KioskPage QR polling integration.
 *
 * Validates: Requirements 4.1, 4.2, 7.2
 */

import { render, screen, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ */
/*  Mocks — must be declared before imports that use them              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
  },
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isEnabled: () => false,
    refetch: vi.fn(),
  }),
}))

// Mock child components to simplify testing
vi.mock('./KioskWelcome', () => ({
  KioskWelcome: ({ onCheckIn }: { onCheckIn: () => void }) => (
    <div data-testid="kiosk-welcome">
      <button data-testid="check-in-btn" onClick={onCheckIn}>Check In</button>
    </div>
  ),
}))

vi.mock('./KioskRegoEntry', () => ({
  KioskRegoEntry: () => <div data-testid="kiosk-rego-entry" />,
}))

vi.mock('./KioskVehicleSummary', () => ({
  KioskVehicleSummary: () => <div data-testid="kiosk-vehicle-summary" />,
}))

vi.mock('./KioskCheckInForm', () => ({
  KioskCheckInForm: () => <div data-testid="kiosk-check-in-form" />,
}))

vi.mock('./KioskSuccess', () => ({
  KioskSuccess: () => <div data-testid="kiosk-success" />,
}))

// Capture the onPaymentComplete and onExpired callbacks from KioskQrPopup
let capturedOnPaymentComplete: (() => void) | null = null
let capturedOnExpired: (() => void) | null = null

vi.mock('./KioskQrPopup', () => ({
  KioskQrPopup: ({ session, onPaymentComplete, onExpired }: {
    session: { session_id: string; checkout_url: string; amount: number; invoice_number: string; expires_at: string }
    onPaymentComplete: () => void
    onExpired: () => void
  }) => {
    capturedOnPaymentComplete = onPaymentComplete
    capturedOnExpired = onExpired
    return (
      <div data-testid="kiosk-qr-popup">
        <span data-testid="qr-session-id">{session.session_id}</span>
        <span data-testid="qr-amount">{session.amount}</span>
      </div>
    )
  },
}))

import apiClient from '@/api/client'
import { KioskPage } from './KioskPage'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const mockSession = {
  session_id: 'cs_test_123',
  checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_123',
  amount: 125.50,
  invoice_number: 'INV-2026-001',
  expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
  created_at: new Date().toISOString(),
}

function renderKioskPage() {
  return render(
    <MemoryRouter>
      <KioskPage />
    </MemoryRouter>,
  )
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('KioskPage — QR polling integration', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.clearAllMocks()
    capturedOnPaymentComplete = null
    capturedOnExpired = null
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls the pending QR session endpoint on the welcome screen', async () => {
    // API returns no session
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { session: null },
    })

    await act(async () => {
      renderKioskPage()
    })

    // Welcome screen should be visible
    expect(screen.getByTestId('kiosk-welcome')).toBeInTheDocument()

    // The initial poll should have been called
    expect(apiClient.get).toHaveBeenCalledWith(
      '/payments/qr-session/pending',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )

    const callCountAfterInitial = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls.length

    // Advance time by the poll interval (2500ms) to trigger next poll
    await act(async () => {
      vi.advanceTimersByTime(2500)
    })

    // Should have polled again
    expect((apiClient.get as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callCountAfterInitial)
  })

  it('renders KioskQrPopup when a pending session is detected', async () => {
    // API returns a pending session
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { session: mockSession },
    })

    await act(async () => {
      renderKioskPage()
    })

    // Wait for the popup to appear
    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })

    // Verify session data is passed through
    expect(screen.getByTestId('qr-session-id')).toHaveTextContent('cs_test_123')
    expect(screen.getByTestId('qr-amount')).toHaveTextContent('125.5')
  })

  it('dismisses the popup when onPaymentComplete is called', async () => {
    // API returns a pending session
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { session: mockSession },
    })

    await act(async () => {
      renderKioskPage()
    })

    // Wait for the popup to appear
    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })

    // Simulate payment complete callback
    expect(capturedOnPaymentComplete).not.toBeNull()
    act(() => {
      capturedOnPaymentComplete!()
    })

    // Popup should be dismissed
    await waitFor(() => {
      expect(screen.queryByTestId('kiosk-qr-popup')).not.toBeInTheDocument()
    })

    // Welcome screen should still be visible
    expect(screen.getByTestId('kiosk-welcome')).toBeInTheDocument()
  })

  it('dismisses the popup when onExpired is called', async () => {
    // API returns a pending session
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { session: mockSession },
    })

    await act(async () => {
      renderKioskPage()
    })

    // Wait for the popup to appear
    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })

    // Simulate session expired callback
    expect(capturedOnExpired).not.toBeNull()
    act(() => {
      capturedOnExpired!()
    })

    // Popup should be dismissed
    await waitFor(() => {
      expect(screen.queryByTestId('kiosk-qr-popup')).not.toBeInTheDocument()
    })

    // Welcome screen should still be visible
    expect(screen.getByTestId('kiosk-welcome')).toBeInTheDocument()
  })

  it('does not show popup when API returns null session', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { session: null },
    })

    await act(async () => {
      renderKioskPage()
    })

    // Advance past initial poll
    await act(async () => {
      vi.advanceTimersByTime(100)
    })

    // Popup should not be present
    expect(screen.queryByTestId('kiosk-qr-popup')).not.toBeInTheDocument()

    // Welcome screen should be visible
    expect(screen.getByTestId('kiosk-welcome')).toBeInTheDocument()
  })
})
