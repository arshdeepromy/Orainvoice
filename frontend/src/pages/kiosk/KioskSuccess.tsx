import { useState, useEffect, useCallback } from 'react'

/* ── Types ── */

interface KioskSuccessProps {
  customerFirstName: string
  onDone: () => void
}

const COUNTDOWN_START = 10

/* ── KioskSuccess ── */

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

  /** Progress percentage for the visual countdown ring (1 = full, 0 = empty). */
  const progress = secondsLeft / COUNTDOWN_START

  return (
    <div className="w-full max-w-md space-y-8 rounded-xl bg-white p-8 text-center shadow-lg">
      {/* Confirmation icon */}
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
        <svg
          className="h-8 w-8 text-green-600"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </div>

      {/* Greeting (Req 5.1) */}
      <h2 className="text-xl font-semibold text-gray-900">
        Thanks {customerFirstName}, we&apos;ll be with you shortly
      </h2>

      {/* Countdown visual (Req 5.2) */}
      <div className="flex flex-col items-center gap-2">
        <div className="relative h-20 w-20" aria-label={`Returning to welcome in ${secondsLeft} seconds`}>
          <svg className="h-20 w-20 -rotate-90" viewBox="0 0 36 36">
            {/* Background circle */}
            <circle
              cx="18"
              cy="18"
              r="15.9155"
              fill="none"
              stroke="#e5e7eb"
              strokeWidth="3"
            />
            {/* Progress circle */}
            <circle
              cx="18"
              cy="18"
              r="15.9155"
              fill="none"
              stroke="#3b82f6"
              strokeWidth="3"
              strokeDasharray="100"
              strokeDashoffset={100 - progress * 100}
              strokeLinecap="round"
              className="transition-[stroke-dashoffset] duration-1000 ease-linear"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-2xl font-bold text-gray-700">
            {secondsLeft}
          </span>
        </div>
        <p className="text-sm text-gray-500">Returning to welcome…</p>
      </div>

      {/* Done button (Req 5.4) */}
      <button
        type="button"
        onClick={handleDone}
        className="inline-flex min-h-[48px] items-center justify-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
      >
        Done
      </button>
    </div>
  )
}

export default KioskSuccess
