import { useState, useCallback, useEffect, useRef } from 'react'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'
import { KioskWelcome } from './KioskWelcome'
import { KioskRegoEntry } from './KioskRegoEntry'
import { KioskVehicleSummary } from './KioskVehicleSummary'
import { KioskCheckInForm } from './KioskCheckInForm'
import { KioskSuccess } from './KioskSuccess'
import { KioskQrPopup } from './KioskQrPopup'
import type {
  KioskVehicleEntry,
  VehicleLookupResult,
  KioskFormData,
  KioskSuccessData,
} from './types'

/* ── Types ── */

export type KioskScreen = 'welcome' | 'rego' | 'vehicle-summary' | 'form' | 'success' | 'error'

/** Shape returned by GET /payments/qr-session/pending when a session exists. */
interface QrSession {
  session_id: string
  checkout_url: string
  amount: number
  invoice_number: string
  expires_at: string
}

/** Polling interval for pending QR sessions (ms). */
const QR_POLL_INTERVAL = 2500

/* ── Initial state helpers ── */

const EMPTY_FORM_DATA: KioskFormData = {
  first_name: '',
  last_name: '',
  phone: '',
  email: '',
}

/* ── KioskPage ── */

export function KioskPage() {
  const { isEnabled } = useModules()
  const vehiclesEnabled = isEnabled('vehicles')

  const [screen, setScreen] = useState<KioskScreen>('welcome')
  const [vehicles, setVehicles] = useState<KioskVehicleEntry[]>([])
  const [currentLookupResult, setCurrentLookupResult] = useState<VehicleLookupResult | null>(null)
  const [formData, setFormData] = useState<KioskFormData>(EMPTY_FORM_DATA)
  const [successData, setSuccessData] = useState<KioskSuccessData | null>(null)
  const [qrSession, setQrSession] = useState<QrSession | null>(null)

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  /** Poll for pending QR sessions while on the welcome screen. */
  useEffect(() => {
    if (screen !== 'welcome') return

    const controller = new AbortController()

    const pollPending = async () => {
      try {
        const res = await apiClient.get<{ session: QrSession | null }>(
          '/payments/qr-session/pending',
          { signal: controller.signal },
        )
        const session = res.data?.session ?? null
        if (session) {
          setQrSession(session)
        }
      } catch {
        // Silent retry on network errors (Req 7.5)
      }
    }

    // Initial poll
    pollPending()

    // Poll every 2.5 seconds
    pollTimerRef.current = setInterval(pollPending, QR_POLL_INTERVAL)

    return () => {
      controller.abort()
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [screen])

  /** Clear all session state and return to welcome. */
  const resetToWelcome = useCallback(() => {
    setScreen('welcome')
    setVehicles([])
    setCurrentLookupResult(null)
    setFormData(EMPTY_FORM_DATA)
    setSuccessData(null)
  }, [])

  /** Dismiss QR popup — payment completed or session expired. */
  const handleQrDismiss = useCallback(() => {
    setQrSession(null)
  }, [])

  /** Welcome → Check In: module-gated transition. */
  const handleCheckIn = useCallback(() => {
    if (vehiclesEnabled) {
      setScreen('rego')
    } else {
      setScreen('form')
    }
  }, [vehiclesEnabled])

  /** KioskRegoEntry: vehicle found → go to vehicle-summary. */
  const handleVehicleFound = useCallback((result: VehicleLookupResult) => {
    setCurrentLookupResult(result)
    setScreen('vehicle-summary')
  }, [])

  /** KioskRegoEntry: back → go to welcome. */
  const handleRegoBack = useCallback(() => {
    resetToWelcome()
  }, [resetToWelcome])

  /** KioskVehicleSummary: confirm → add vehicle to list, go to form. */
  const handleVehicleConfirm = useCallback(
    (odometer_km: number | null) => {
      if (!currentLookupResult) return

      const entry: KioskVehicleEntry = {
        global_vehicle_id: currentLookupResult.id,
        rego: currentLookupResult.rego,
        make: currentLookupResult.make,
        model: currentLookupResult.model,
        body_type: currentLookupResult.body_type,
        year: currentLookupResult.year,
        wof_expiry: currentLookupResult.wof_expiry,
        rego_expiry: currentLookupResult.rego_expiry,
        last_odometer: currentLookupResult.odometer,
        odometer_km,
      }

      setVehicles((prev) => [...prev, entry])
      setCurrentLookupResult(null)
      setScreen('form')
    },
    [currentLookupResult],
  )

  /** KioskVehicleSummary: add another → go back to rego (vehicles preserved). */
  const handleAddAnother = useCallback(() => {
    setCurrentLookupResult(null)
    setScreen('rego')
  }, [])

  /** KioskVehicleSummary: back → go to rego. */
  const handleSummaryBack = useCallback(() => {
    setCurrentLookupResult(null)
    setScreen('rego')
  }, [])

  /** KioskCheckInForm: form data changed. */
  const handleFormDataChange = useCallback((data: KioskFormData) => {
    setFormData(data)
  }, [])

  /** KioskCheckInForm: success. */
  const handleSuccess = useCallback((data: KioskSuccessData) => {
    setSuccessData(data)
    setScreen('success')
  }, [])

  /** KioskCheckInForm: error. */
  const handleError = useCallback(() => {
    setScreen('error')
  }, [])

  /** KioskCheckInForm: back → go to rego (if vehicles enabled) or welcome. */
  const handleFormBack = useCallback(() => {
    if (vehiclesEnabled) {
      setScreen('rego')
    } else {
      resetToWelcome()
    }
  }, [vehiclesEnabled, resetToWelcome])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-50 px-4">
      {screen === 'welcome' && (
        <KioskWelcome onCheckIn={handleCheckIn} />
      )}

      {screen === 'rego' && (
        <KioskRegoEntry
          vehicleCount={vehicles.length}
          onVehicleFound={handleVehicleFound}
          onBack={handleRegoBack}
        />
      )}

      {screen === 'vehicle-summary' && currentLookupResult && (
        <KioskVehicleSummary
          vehicle={currentLookupResult}
          vehicleCount={vehicles.length}
          onConfirm={handleVehicleConfirm}
          onAddAnother={handleAddAnother}
          onBack={handleSummaryBack}
        />
      )}

      {screen === 'form' && (
        <KioskCheckInForm
          formData={formData}
          onFormDataChange={handleFormDataChange}
          vehicles={vehicles}
          onSuccess={handleSuccess}
          onError={handleError}
          onBack={handleFormBack}
        />
      )}

      {screen === 'success' && successData && (
        <KioskSuccess
          customerFirstName={successData.customer_first_name}
          onDone={resetToWelcome}
        />
      )}

      {screen === 'error' && (
        <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 text-center shadow-lg">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-100">
            <svg
              className="h-8 w-8 text-red-600"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-gray-900">Something went wrong</h2>
          <p className="text-lg text-gray-600">
            We couldn&apos;t complete your check-in. Please try again.
          </p>
          <button
            type="button"
            onClick={resetToWelcome}
            className="inline-flex min-h-[48px] items-center justify-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Start Over
          </button>
        </div>
      )}

      {/* QR Payment Popup — overlays welcome screen when a pending session is detected */}
      {qrSession && (
        <KioskQrPopup
          session={qrSession}
          onPaymentComplete={handleQrDismiss}
          onExpired={handleQrDismiss}
        />
      )}
    </div>
  )
}

export default KioskPage
