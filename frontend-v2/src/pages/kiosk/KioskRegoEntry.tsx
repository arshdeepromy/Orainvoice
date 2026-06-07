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
/* Full alphanumeric on-screen keypad. The prototype draws a 9-key mock
   (A/B/C/1/2/3/0/⌫/Clear) that can't enter most plates, so we keep its button
   styling (`.keypad`) but expose every key for real kiosk use. */
const KEYPAD_KEYS = [
  'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I',
  'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R',
  'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', '0',
  '1', '2', '3', '4', '5', '6', '7', '8', '9',
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

        <div className="keypad" style={{ gridTemplateColumns: 'repeat(6, 1fr)' }}>
          {KEYPAD_KEYS.map((k) => (
            <button key={k} type="button" onClick={() => pressKey(k)} disabled={loading}>
              {k}
            </button>
          ))}
          <button
            type="button"
            onClick={() => pressKey('back')}
            disabled={loading}
            aria-label="Backspace"
            style={{ gridColumn: 'span 3' }}
          >
            ⌫
          </button>
          <button
            type="button"
            onClick={() => pressKey('clear')}
            disabled={loading}
            style={{ gridColumn: 'span 3', fontSize: '18px' }}
          >
            Clear
          </button>
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
