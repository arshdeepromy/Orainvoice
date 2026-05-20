import { useState, useEffect, useRef, useCallback } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import apiClient from '@/api/client'

/* ── Types ── */

interface KioskQrPopupProps {
  session: {
    session_id: string
    checkout_url: string
    amount: number
    invoice_number: string
    expires_at: string
  }
  onPaymentComplete: () => void
  onExpired: () => void
  onClose?: () => void
}

type PopupState = 'scanning' | 'success'

/* ── Helpers ── */

/** Format seconds as MM:SS (zero-padded). */
export function formatCountdown(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(clamped / 60)
  const seconds = clamped % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

/** Format amount as NZD currency ($X.XX). */
export function formatNZD(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

/* ── Component ── */

export function KioskQrPopup({ session, onPaymentComplete, onExpired, onClose }: KioskQrPopupProps) {
  const [popupState, setPopupState] = useState<PopupState>('scanning')
  const [secondsRemaining, setSecondsRemaining] = useState<number>(() => {
    const expiresAt = new Date(session.expires_at).getTime()
    const now = Date.now()
    return Math.max(0, Math.floor((expiresAt - now) / 1000))
  })

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const successTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  /** Clean up all timers and abort in-flight requests. */
  const cleanup = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current)
      countdownIntervalRef.current = null
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
    if (popupState !== 'scanning') return

    abortControllerRef.current = new AbortController()

    const pollStatus = async () => {
      try {
        const controller = new AbortController()
        abortControllerRef.current = controller

        const res = await apiClient.get<{ status: string; payment_intent_id: string | null }>(
          `/payments/qr-session/${session.session_id}/status`,
          { signal: controller.signal },
        )

        const status = res.data?.status ?? 'open'

        if (status === 'complete') {
          // Stop polling, show success state
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current)
            pollIntervalRef.current = null
          }
          setPopupState('success')
        }
      } catch (err: unknown) {
        // Silent retry on network errors (Req 7.5)
        // Only log if not aborted
        if (err && typeof err === 'object' && 'code' in err && (err as { code: string }).code === 'ERR_CANCELED') {
          return
        }
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
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [popupState, session.session_id])

  /** Countdown timer — ticks every second. */
  useEffect(() => {
    if (popupState !== 'scanning') return

    countdownIntervalRef.current = setInterval(() => {
      setSecondsRemaining((prev) => {
        const next = prev - 1
        if (next <= 0) {
          return 0
        }
        return next
      })
    }, 1000)

    return () => {
      if (countdownIntervalRef.current) {
        clearInterval(countdownIntervalRef.current)
        countdownIntervalRef.current = null
      }
    }
  }, [popupState])

  /** Handle timer expiry. */
  useEffect(() => {
    if (secondsRemaining <= 0 && popupState === 'scanning') {
      cleanup()
      onExpired()
    }
  }, [secondsRemaining, popupState, cleanup, onExpired])

  /** Handle success state — show for 4 seconds then call onPaymentComplete. */
  useEffect(() => {
    if (popupState !== 'success') return

    // Stop countdown
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current)
      countdownIntervalRef.current = null
    }

    const handler = onPaymentComplete
    successTimeoutRef.current = setTimeout(() => {
      handler()
    }, 4000)

    return () => {
      if (successTimeoutRef.current) {
        clearTimeout(successTimeoutRef.current)
        successTimeoutRef.current = null
      }
    }
  }, [popupState]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Cleanup on unmount. */
  useEffect(() => {
    return () => cleanup()
  }, [cleanup])

  const isWarning = secondsRemaining < 120
  const timerColorClass = isWarning ? 'text-red-500' : 'text-gray-600'

  /* ── Success State ── */
  if (popupState === 'success') {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
        role="dialog"
        aria-modal="true"
        aria-label="Payment received"
        onClick={onPaymentComplete}
      >
        <div className="flex flex-col items-center gap-6 rounded-2xl bg-white p-12 text-center shadow-2xl">
          {/* Green tick */}
          <div className="flex h-24 w-24 items-center justify-center rounded-full bg-green-100">
            <svg
              className="h-14 w-14 text-green-600"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
          </div>

          {/* Thank you message */}
          <h2 className="text-3xl font-bold text-gray-900">Thank you</h2>
          <p className="text-2xl font-semibold text-green-700">
            {formatNZD(session.amount ?? 0)}
          </p>
          <p className="text-lg text-gray-500">Payment received</p>
          <p className="text-sm text-gray-400 mt-2">Tap anywhere to dismiss</p>
        </div>
      </div>
    )
  }

  /* ── Scanning State (QR Code Display) ── */
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80">
      <div className="flex flex-col items-center gap-6 rounded-2xl bg-white p-12 text-center shadow-2xl">
        {/* Amount */}
        <p className="text-3xl font-bold text-gray-900">
          {formatNZD(session.amount ?? 0)}
        </p>

        {/* Invoice number */}
        <p className="text-lg text-gray-500">
          Invoice: {session.invoice_number ?? ''}
        </p>

        {/* QR Code */}
        <div className="rounded-xl border-4 border-gray-100 p-4">
          <QRCodeSVG
            value={session.checkout_url ?? ''}
            size={280}
            level="M"
            includeMargin={false}
          />
        </div>

        {/* Instructional text */}
        <p className="text-xl font-medium text-gray-700">
          Scan with your phone camera to pay
        </p>

        {/* Countdown timer */}
        <div className={`text-2xl font-mono font-semibold ${timerColorClass}`}>
          {formatCountdown(secondsRemaining)} remaining
        </div>

        {/* Close button */}
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="mt-2 rounded-lg border border-gray-300 px-6 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 transition-colors"
          >
            Close
          </button>
        )}
      </div>
    </div>
  )
}

export default KioskQrPopup
