import { useState, useEffect, useRef, useCallback } from 'react'
import apiClient from '@/api/client'

/**
 * QrPaymentWaitingPopup — Task 19 port of
 * frontend/src/pages/invoices/QrPaymentWaitingPopup.
 *
 * All polling logic copied VERBATIM: poll GET /payments/qr-session/:id/status
 * every 3s with AbortController, transition to success (auto-close after 3s) or
 * superseded on `expired`, full timer/abort cleanup. Styling remapped onto the
 * design-system tokens (accent / ok / warn). Shared with Task 22.
 */

/* ── Types ── */

interface QrPaymentWaitingPopupProps {
  sessionId: string
  amount: number
  invoiceNumber: string
  onClose: () => void
  onPaymentComplete: () => void
}

type PopupState = 'waiting' | 'success' | 'superseded'

/* ── Component ── */

export function QrPaymentWaitingPopup({
  sessionId,
  amount,
  invoiceNumber,
  onClose,
  onPaymentComplete,
}: QrPaymentWaitingPopupProps) {
  const [popupState, setPopupState] = useState<PopupState>('waiting')

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const successTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  /** Format amount as NZD: $X.XX */
  const formattedAmount = `$${Number(amount ?? 0).toFixed(2)}`

  /** Clean up all timers and abort in-flight requests. */
  const cleanup = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
    if (successTimeoutRef.current) {
      clearTimeout(successTimeoutRef.current)
      successTimeoutRef.current = null
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
  }, [])

  /** Poll session status every 3 seconds. */
  useEffect(() => {
    if (popupState !== 'waiting') return

    const controller = new AbortController()
    abortControllerRef.current = controller

    const pollStatus = async () => {
      try {
        const res = await apiClient.get<{ status: string; payment_intent_id: string | null }>(
          `/payments/qr-session/${sessionId}/status`,
          { signal: controller.signal },
        )

        const status = res.data?.status ?? 'open'

        if (status === 'complete') {
          // Stop polling, transition to success state
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current)
            pollIntervalRef.current = null
          }
          setPopupState('success')
        } else if (status === 'expired') {
          // Stop polling, surface superseded message (Requirement 10.2)
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current)
            pollIntervalRef.current = null
          }
          setPopupState('superseded')
        }
      } catch (err: unknown) {
        // Silent retry on network errors
        if (
          err &&
          typeof err === 'object' &&
          'code' in err &&
          (err as { code: string }).code === 'ERR_CANCELED'
        ) {
          return
        }
        // Otherwise silently ignore and retry on next interval
      }
    }

    // Initial poll
    pollStatus()

    // Poll every 3 seconds
    pollIntervalRef.current = setInterval(pollStatus, 3000)

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
      controller.abort()
    }
  }, [popupState, sessionId])

  /** Handle success state — show for 3 seconds then call onPaymentComplete. */
  useEffect(() => {
    if (popupState !== 'success') return

    successTimeoutRef.current = setTimeout(() => {
      onPaymentComplete()
    }, 3000)

    return () => {
      if (successTimeoutRef.current) {
        clearTimeout(successTimeoutRef.current)
        successTimeoutRef.current = null
      }
    }
  }, [popupState, onPaymentComplete])

  /** Cleanup on unmount. */
  useEffect(() => {
    return () => cleanup()
  }, [cleanup])

  /* ── Success State ── */
  if (popupState === 'success') {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50"
        role="dialog"
        aria-modal="true"
        aria-label="Payment received"
      >
        <div className="flex flex-col items-center gap-4 rounded-card bg-card p-8 text-center shadow-pop max-w-sm w-full mx-4">
          {/* Green tick */}
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-ok-soft">
            <svg
              className="h-10 w-10 text-ok"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
          </div>

          {/* Success message */}
          <h2 className="text-xl font-semibold text-text">
            Payment received — {formattedAmount}
          </h2>
          <p className="text-sm text-muted">{invoiceNumber ?? ''}</p>
        </div>
      </div>
    )
  }

  /* ── Superseded State ── */
  if (popupState === 'superseded') {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50"
        role="dialog"
        aria-modal="true"
        aria-label="QR session superseded"
      >
        <div className="flex flex-col items-center gap-4 rounded-card bg-card p-8 text-center shadow-pop max-w-sm w-full mx-4">
          {/* Info icon (amber) */}
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-warn-soft">
            <svg
              className="h-10 w-10 text-warn"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m0 3.75h.008v.008H12v-.008zM12 3a9 9 0 100 18 9 9 0 000-18z"
              />
            </svg>
          </div>

          {/* Superseded message */}
          <h2 className="text-lg font-semibold text-text">QR session superseded</h2>
          <p className="text-sm text-muted">
            This QR session was superseded by a newer payment attempt.
          </p>
          <p className="text-xs text-muted-2">{invoiceNumber ?? ''}</p>

          {/* Close button */}
          <button
            type="button"
            onClick={onClose}
            className="mt-2 rounded-ctl border border-border px-5 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    )
  }

  /* ── Waiting State ── */
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/50"
      role="dialog"
      aria-modal="true"
      aria-label="Waiting for payment"
    >
      <div className="flex flex-col items-center gap-5 rounded-card bg-card p-8 text-center shadow-pop max-w-sm w-full mx-4">
        {/* Spinner */}
        <div className="flex h-16 w-16 items-center justify-center">
          <svg
            className="h-12 w-12 animate-spin text-accent"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        </div>

        {/* Waiting text */}
        <h2 className="text-lg font-semibold text-text">Waiting for payment...</h2>

        {/* Amount and invoice reference */}
        <div className="space-y-1">
          <p className="text-2xl font-bold text-text mono">{formattedAmount}</p>
          <p className="text-sm text-muted">{invoiceNumber ?? ''}</p>
        </div>

        {/* Close button */}
        <button
          type="button"
          onClick={onClose}
          className="mt-2 rounded-ctl border border-border px-5 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  )
}

export default QrPaymentWaitingPopup
