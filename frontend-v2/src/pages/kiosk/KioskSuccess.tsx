import { useState, useEffect, useCallback } from 'react'

/* ── Types ── */

interface KioskSuccessProps {
  customerFirstName: string
  onDone: () => void
}

const COUNTDOWN_START = 10

/* ── KioskSuccess ──
 * Design: the "SUCCESS" screen in OraInvoice_Handoff/app/Kiosk.html. The
 * auto-return countdown behaviour is unchanged (renders as the design's plain
 * countdown line instead of the previous progress ring). */

export function KioskSuccess({ customerFirstName, onDone }: KioskSuccessProps) {
  const [secondsLeft, setSecondsLeft] = useState(COUNTDOWN_START)

  useEffect(() => {
    if (secondsLeft <= 0) {
      onDone()
      return
    }

    const timer = setInterval(() => {
      setSecondsLeft((prev) => prev - 1)
    }, 1000)

    return () => clearInterval(timer)
  }, [secondsLeft, onDone])

  const handleDone = useCallback(() => {
    onDone()
  }, [onDone])

  return (
    <div className="k-card" style={{ textAlign: 'center' }}>
      <div className="k-ico" style={{ background: 'var(--ok-soft)' }}>
        <svg viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth={2.4}>
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>

      <h1>You&apos;re checked in!</h1>
      <p className="lead">
        Thanks{customerFirstName ? `, ${customerFirstName}` : ''}. We&apos;ve let your technician
        know you&apos;ve arrived. Take a seat — we&apos;ll be with you shortly.
      </p>

      <button
        type="button"
        className="btn-kiosk primary"
        style={{ marginTop: '30px' }}
        onClick={handleDone}
      >
        Done
      </button>

      <p
        style={{ fontSize: '14px', color: 'var(--muted-2)', marginTop: '18px' }}
        aria-label={`Returning to start in ${secondsLeft} seconds`}
      >
        Returning to start in {secondsLeft}s…
      </p>
    </div>
  )
}

export default KioskSuccess
