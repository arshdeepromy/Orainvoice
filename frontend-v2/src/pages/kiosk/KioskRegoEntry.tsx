import { useState, useRef, useEffect, useCallback } from 'react'
import { lookupVehicle } from './api'
import type { VehicleLookupResult } from './types'

/* ── Types ── */

interface KioskRegoEntryProps {
  vehicleCount: number
  onVehicleFound: (result: VehicleLookupResult) => void
  onBack: () => void
  /** Proceed to the check-in form with the vehicles already added. Rendered as
   *  a "Continue to check-in" button when at least one vehicle exists. */
  onContinue?: () => void
}

const REGO_MAX = 6
/* QWERTY keypad layout — matches the staff clock-in screen so kiosk users see
   a familiar typewriter ordering instead of an A-Z grid (faster touch hunting
   on a tablet). Digits live above the letters per phone-keyboard convention. */
const KEYPAD_ROWS: string[][] = [
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
  ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
  ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
  ['Z', 'X', 'C', 'V', 'B', 'N', 'M'],
]

/* ── KioskRegoEntry ──
 * Design: the "REGO" screen in OraInvoice_Handoff/app/Kiosk.html. Vehicle
 * lookup logic (lookupVehicle + 404/429/error handling) is unchanged. */

export function KioskRegoEntry({
  vehicleCount,
  onVehicleFound,
  onBack,
  onContinue,
}: KioskRegoEntryProps) {
  const [rego, setRego] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Cleanup AbortController on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
    }
  }, [])

  /** Mirror of the prototype `key()` helper — drives the readonly-style input
   *  from the on-screen keypad. The input itself stays editable for keyboards. */
  const pressKey = useCallback((k: string) => {
    if (error) setError(null)
    setRego((prev) => {
      if (k === 'back') return prev.slice(0, -1)
      if (k === 'clear') return ''
      if (prev.length >= REGO_MAX) return prev
      return (prev + k).toUpperCase()
    })
  }, [error])

  const handleConfirm = useCallback(async () => {
    // Validate non-empty
    const cleaned = rego.trim().toUpperCase()
    if (!cleaned) {
      setError('Please enter a registration number')
      return
    }

    setError(null)
    setLoading(true)

    // Abort any in-flight request
    abortControllerRef.current?.abort()
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const result = await lookupVehicle(cleaned, controller.signal)
      if (!controller.signal.aborted) {
        onVehicleFound(result)
      }
    } catch (err: unknown) {
      if (controller.signal.aborted) return

      // Determine error type from axios response
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        setError('Vehicle not found. Please check the registration and try again.')
      } else if (status === 429) {
        setError('Too many lookups, please wait a moment and try again.')
      } else {
        setError('Something went wrong. Please try again.')
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }, [rego, onVehicleFound])

  return (
    <>
      <button type="button" className="k-back" onClick={onBack} disabled={loading}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Back
      </button>

      <div className="k-card">
        <h1>Your number plate</h1>
        <p className="lead">Pop in your rego and we&apos;ll find your vehicle.</p>

        {vehicleCount > 0 && (
          <p className="mono" style={{ textAlign: 'center', color: 'var(--ok)', fontSize: '14px', fontWeight: 600, marginTop: '14px' }}>
            {vehicleCount} vehicle{vehicleCount !== 1 ? 's' : ''} added
          </p>
        )}

        <div style={{ marginTop: '26px' }}>
          <input
            className="k-input"
            value={rego}
            maxLength={REGO_MAX}
            onChange={(e) => {
              setRego(e.target.value.toUpperCase().slice(0, REGO_MAX))
              if (error) setError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleConfirm()
            }}
            aria-label="Vehicle registration number"
            aria-invalid={!!error}
            aria-describedby={error ? 'rego-error' : undefined}
            autoComplete="off"
            autoCapitalize="characters"
            disabled={loading}
          />
        </div>

        {error && (
          <p
            id="rego-error"
            role="alert"
            style={{ textAlign: 'center', color: 'var(--danger)', fontSize: '14px', marginTop: '10px' }}
          >
            {error}
          </p>
        )}

        <div className="space-y-2" style={{ marginTop: '18px' }}>
          {KEYPAD_ROWS.map((row, idx) => (
            <div key={idx} className="flex flex-nowrap justify-center gap-1.5 sm:gap-2">
              {row.map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => pressKey(k)}
                  disabled={loading}
                  className="mono inline-flex min-h-[48px] flex-1 basis-0 min-w-0 items-center justify-center rounded-ctl border border-border bg-card px-1.5 py-2 text-base font-semibold text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-50 sm:px-3 sm:text-lg"
                >
                  {k}
                </button>
              ))}
            </div>
          ))}

          <div className="flex flex-nowrap justify-center gap-1.5 sm:gap-2 pt-1">
            <button
              type="button"
              onClick={() => pressKey('back')}
              disabled={loading}
              aria-label="Backspace"
              className="inline-flex min-h-[48px] flex-1 basis-0 min-w-0 items-center justify-center rounded-ctl border border-border bg-card px-3 py-2 text-base font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              ⌫
            </button>
            <button
              type="button"
              onClick={() => pressKey('clear')}
              disabled={loading}
              className="inline-flex min-h-[48px] flex-1 basis-0 min-w-0 items-center justify-center rounded-ctl border border-border bg-card px-3 py-2 text-base font-medium text-text shadow-card hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              Clear
            </button>
          </div>
        </div>

        <button
          type="button"
          className="btn-kiosk primary"
          style={{ marginTop: '20px' }}
          onClick={handleConfirm}
          disabled={loading}
        >
          {loading ? (
            'Looking up…'
          ) : (
            <>
              Find my vehicle
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M21 21l-5-5m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </>
          )}
        </button>

        {/* Recover from an accidental "Add another vehicle": continue to the
            check-in form with the vehicles already added (no data lost). */}
        {vehicleCount > 0 && onContinue && (
          <button
            type="button"
            className="btn-kiosk ghost"
            style={{ marginTop: '12px' }}
            onClick={onContinue}
            disabled={loading}
          >
            Continue to check-in
          </button>
        )}

        <div className="step-dots">
          <i className="on" />
          <i />
          <i />
        </div>
      </div>
    </>
  )
}

export default KioskRegoEntry
