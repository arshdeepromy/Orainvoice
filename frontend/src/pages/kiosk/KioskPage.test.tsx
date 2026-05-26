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

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'kiosk@example.com', role: 'kiosk' },
    logout: vi.fn(),
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

// Capture the onPaymentComplete, onExpired, and onClose callbacks from KioskQrPopup
let capturedOnPaymentComplete: (() => void) | null = null
let capturedOnExpired: (() => void) | null = null
let capturedOnClose: (() => void) | null = null

vi.mock('./KioskQrPopup', () => ({
  KioskQrPopup: ({ session, onPaymentComplete, onExpired, onClose }: {
    session: { session_id: string; checkout_url: string; amount: number; invoice_number: string; expires_at: string }
    onPaymentComplete: () => void
    onExpired: () => void
    onClose?: () => void
  }) => {
    capturedOnPaymentComplete = onPaymentComplete
    capturedOnExpired = onExpired
    capturedOnClose = onClose ?? null
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
    capturedOnClose = null
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

  it('calls POST /payments/qr-session/{id}/dismiss when staff closes the popup', async () => {
    // The kiosk's "Close" button on the QR popup performs a soft-dismiss
    // server-side. The Stripe PaymentIntent + the pending_qr_sessions
    // row stay alive so a customer who already scanned can complete
    // payment from their phone — only the kiosk display is hidden.
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { session: mockSession },
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { status: 'dismissed' },
    })

    await act(async () => {
      renderKioskPage()
    })

    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })

    // Simulate the kiosk staff pressing the "Close" button on the QR popup.
    expect(capturedOnClose).not.toBeNull()
    act(() => {
      capturedOnClose!()
    })

    // The popup is dismissed locally immediately for snappy UX.
    await waitFor(() => {
      expect(screen.queryByTestId('kiosk-qr-popup')).not.toBeInTheDocument()
    })

    // And the dismiss endpoint is called with the session id so the
    // backend filters this session out of subsequent kiosk polls.
    expect(apiClient.post).toHaveBeenCalledWith(
      `/payments/qr-session/${encodeURIComponent(mockSession.session_id)}/dismiss`,
    )
  })

  it('does not show the popup again on next poll if backend filters dismissed session', async () => {
    // After dismiss, the backend's get_pending_qr_session filters out
    // dismissed rows and returns ``{session: null}`` even though the
    // row still exists in the DB. The kiosk should NOT re-render the
    // popup until a new session arrives.
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { session: mockSession } })
      .mockResolvedValue({ data: { session: null } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { status: 'dismissed' },
    })

    await act(async () => {
      renderKioskPage()
    })

    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })

    // Dismiss locally + call backend.
    act(() => {
      capturedOnClose!()
    })
    await waitFor(() => {
      expect(screen.queryByTestId('kiosk-qr-popup')).not.toBeInTheDocument()
    })

    // Several poll cycles pass — popup must NOT reappear.
    await act(async () => {
      vi.advanceTimersByTime(2500 * 4)
    })
    expect(screen.queryByTestId('kiosk-qr-popup')).not.toBeInTheDocument()
  })

  it('shows the popup again when a different session arrives after dismissal', async () => {
    // After dismissal, when staff fires QR Payment again the backend
    // rotates the pending_qr_sessions row (DELETE+INSERT) which
    // clears ``dismissed_at``. The next poll returns the (possibly
    // same session_id, fresh expires_at) session and the kiosk shows
    // the popup again.
    const refreshedSession = {
      ...mockSession,
      // expires_at is bumped by the backend on row rotation; for the
      // kiosk test we just need a non-null session to come back.
      expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    }

    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { session: mockSession } })
      .mockResolvedValueOnce({ data: { session: null } })
      .mockResolvedValue({ data: { session: refreshedSession } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { status: 'dismissed' },
    })

    await act(async () => {
      renderKioskPage()
    })

    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })

    // Dismiss.
    act(() => {
      capturedOnClose!()
    })
    await waitFor(() => {
      expect(screen.queryByTestId('kiosk-qr-popup')).not.toBeInTheDocument()
    })

    // Drive the poll forward — the second poll returns null, the third
    // returns the refreshed session.
    await act(async () => {
      vi.advanceTimersByTime(2500 * 3)
    })

    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })
  })

  it('does not call dismiss endpoint on payment-complete or expired callbacks', async () => {
    // onPaymentComplete and onExpired should NOT call the dismiss
    // endpoint — the backend has already resolved the session in those
    // cases (webhook deletes the row on success; Stripe expires the PI).
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { session: mockSession },
    })

    await act(async () => {
      renderKioskPage()
    })

    await waitFor(() => {
      expect(screen.getByTestId('kiosk-qr-popup')).toBeInTheDocument()
    })

    // Reset post-call counter (in case any prior interaction triggered one).
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockClear()

    act(() => {
      capturedOnPaymentComplete!()
    })

    // Wait a tick so any incidental calls would be observed.
    await act(async () => {
      vi.advanceTimersByTime(50)
    })

    expect(apiClient.post).not.toHaveBeenCalled()
  })
})
