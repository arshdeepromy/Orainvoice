import { useState, useRef, useEffect, useCallback } from 'react'
import { lookupVehicle } from './api'
import type { VehicleLookupResult } from './types'

/* ── Types ── */

interface KioskRegoEntryProps {
  vehicleCount: number
  onVehicleFound: (result: VehicleLookupResult) => void
  onBack: () => void
}

/* ── KioskRegoEntry ── */

export function KioskRegoEntry({
  vehicleCount,
  onVehicleFound,
  onBack,
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
    <div className="w-full max-w-md space-y-6 rounded-card bg-card p-8 text-center shadow-pop">
      {/* Vehicle count badge */}
      {vehicleCount > 0 && (
        <div className="inline-flex items-center rounded-full bg-ok-soft px-3 py-1 text-sm font-medium text-ok">
          {vehicleCount} vehicle{vehicleCount !== 1 ? 's' : ''} added
        </div>
      )}

      {/* Title */}
      <h1 className="text-2xl font-bold text-text">
        Enter Vehicle Registration
      </h1>

      <p className="text-lg text-muted">
        Type your vehicle registration number below
      </p>

      {/* Rego input — 48px min tap target, 18px+ font */}
      <div className="space-y-2">
        <input
          type="text"
          value={rego}
          onChange={(e) => {
            setRego(e.target.value)
            if (error) setError(null)
          }}
          placeholder="e.g. ABC123"
          aria-label="Vehicle registration number"
          aria-invalid={!!error}
          aria-describedby={error ? 'rego-error' : undefined}
          className="mono w-full min-h-[48px] rounded-ctl border border-border-strong px-4 py-3 text-lg text-center font-semibold uppercase tracking-wider placeholder:normal-case placeholder:font-normal placeholder:tracking-normal focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent"
          autoComplete="off"
          autoCapitalize="characters"
          disabled={loading}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleConfirm()
          }}
        />

        {/* Validation / error message */}
        {error && (
          <p id="rego-error" className="text-sm text-danger" role="alert">
            {error}
          </p>
        )}
      </div>

      {/* Action buttons */}
      <div className="space-y-3">
        {/* Confirm button */}
        <button
          type="button"
          onClick={handleConfirm}
          disabled={loading}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-ctl bg-accent px-6 py-3 text-lg font-medium text-white shadow-card hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? (
            <>
              <svg
                className="mr-2 h-5 w-5 animate-spin text-white"
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
              Looking up…
            </>
          ) : (
            'Confirm'
          )}
        </button>

        {/* Back button */}
        <button
          type="button"
          onClick={onBack}
          disabled={loading}
          className="inline-flex w-full min-h-[48px] items-center justify-center rounded-ctl px-6 py-3 text-lg font-medium text-muted hover:text-text focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Back
        </button>
      </div>
    </div>
  )
}

export default KioskRegoEntry
