import { useState, useCallback, useEffect, useRef } from 'react'
import { useModules } from '@/contexts/ModuleContext'
import { useAuth } from '@/contexts/AuthContext'
import { useTenant } from '@/contexts/TenantContext'
import apiClient from '@/api/client'
import { KioskBrand } from './KioskBrand'
import { KioskWelcome } from './KioskWelcome'
import { KioskRegoEntry } from './KioskRegoEntry'
import { KioskVehicleSummary } from './KioskVehicleSummary'
import { KioskCheckInForm } from './KioskCheckInForm'
import { ReminderConsentStep } from './ReminderConsentStep'
import { KioskSuccess } from './KioskSuccess'
import { KioskQrPopup } from './KioskQrPopup'
import { KioskClockScreen } from './KioskClockScreen'
import { fetchConsentText } from './api'
import type {
  KioskVehicleEntry,
  VehicleLookupResult,
  KioskFormData,
  KioskSuccessData,
  KioskReminderConsentBlock,
  ReminderConsentVehicle,
} from './types'

/* ── Types ── */

export type KioskScreen = 'welcome' | 'rego' | 'vehicle-summary' | 'consent' | 'form' | 'success' | 'error' | 'clock'

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
  const [consentText, setConsentText] = useState('')
  const [consentTextVersion, setConsentTextVersion] = useState('')
  const [consentBlock, setConsentBlock] = useState<KioskReminderConsentBlock | null>(null)

  const { tradeFamily } = useTenant()
  const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  /** Fetch the reminder-consent banner text + version once at mount (E2). */
  useEffect(() => {
    const controller = new AbortController()
    fetchConsentText(controller.signal)
      .then((ct) => {
        setConsentText(ct.text)
        setConsentTextVersion(ct.version)
      })
      .catch(() => {
        // Graceful degradation: the consent step still renders with empty
        // text rather than blocking check-in.
      })
    return () => controller.abort()
  }, [])

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
        // Server-side dismissal: a dismissed session is filtered out by
        // the backend and returns null here. No client-side bookkeeping
        // needed — refresh-safe across browser tabs / multiple kiosks.
        setQrSession(session)
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
    setConsentBlock(null)
  }, [])

  /** Dismiss the QR popup.
   *
   * - ``manual`` (staff pressed Close on the QR popup): call
   *   ``POST /payments/qr-session/{id}/dismiss`` so the backend hides
   *   this session from subsequent kiosk polls. The Stripe
   *   PaymentIntent and the ``pending_qr_sessions`` row stay alive —
   *   a customer who already scanned the QR can complete payment from
   *   their phone, matching the intended hospitality flow.
   * - ``completed``: the payment succeeded and the webhook already
   *   deleted the row. No backend call needed.
   * - ``expired``: Stripe canceled the PI; the row has already been
   *   removed via ``expire_qr_session`` or natural session expiry.
   *
   * The local ``setQrSession(null)`` is unconditional so the popup
   * closes immediately for snappy UX. The backend stays authoritative
   * on subsequent polls (server-side dismissal is refresh-safe across
   * tabs and across multiple kiosk machines).
   */
  const handleQrDismiss = useCallback(
    (reason: 'manual' | 'completed' | 'expired' = 'manual') => {
      const sid = qrSession?.session_id
      setQrSession(null)
      if (sid && reason === 'manual') {
        apiClient
          .post(`/payments/qr-session/${encodeURIComponent(sid)}/dismiss`)
          .catch(() => {
            // Silent — dismiss is best-effort. If the call fails the
            // popup will reappear on the next 2.5s poll, at which point
            // the kiosk staff can press Close again.
          })
      }
    },
    [qrSession],
  )

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

  /** KioskRegoEntry: back.
   *
   * Non-destructive once a vehicle has been added (i.e. the user reached rego
   * via "Add another vehicle" or stepped back from the form): return to the
   * check-in form with the added vehicles AND any entered details intact, so an
   * accidental "Add another" / Back no longer wipes the session. Only resets to
   * welcome from a genuinely fresh start (no vehicles entered yet). */
  const handleRegoBack = useCallback(() => {
    if (vehicles.length > 0) {
      setScreen('form')
    } else {
      resetToWelcome()
    }
  }, [vehicles.length, resetToWelcome])

  /** KioskRegoEntry: "Continue to check-in" → proceed to the form with the
   *  vehicles already added (shown only when at least one vehicle exists). */
  const handleRegoContinue = useCallback(() => {
    setScreen('consent')
  }, [])

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
        cof_expiry: currentLookupResult.cof_expiry,
        inspection_type: currentLookupResult.inspection_type,
        rego_expiry: currentLookupResult.rego_expiry,
        last_odometer: currentLookupResult.odometer,
        odometer_km,
      }

      setVehicles((prev) => [...prev, entry])
      setCurrentLookupResult(null)
      setScreen('consent')
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

  /** KioskCheckInForm: back → consent (if vehicles present) or welcome. */
  const handleFormBack = useCallback(() => {
    if (vehiclesEnabled && vehicles.length > 0) {
      setScreen('consent')
    } else if (vehiclesEnabled) {
      setScreen('rego')
    } else {
      resetToWelcome()
    }
  }, [vehiclesEnabled, vehicles.length, resetToWelcome])

  /** ReminderConsentStep: continue → proceed to the customer-details form. */
  const handleConsentContinue = useCallback(() => {
    setScreen('form')
  }, [])

  /** ReminderConsentStep: back → return to rego. */
  const handleConsentBack = useCallback(() => {
    setScreen('rego')
  }, [])

  /** Map the collected vehicle entries to the consent-step vehicle shape. */
  const consentVehicles: ReminderConsentVehicle[] = vehicles.map((v) => ({
    global_vehicle_id: v.global_vehicle_id,
    rego: v.rego,
    make: v.make,
    model: v.model,
    inspection_type: v.inspection_type,
    wof_expiry: v.wof_expiry,
    cof_expiry: v.cof_expiry,
  }))

  /* ── Long-press logout (hidden admin escape) ── */
  const { logout } = useAuth()
  const [showLogoutPopup, setShowLogoutPopup] = useState(false)
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    // Only trigger on empty space (not on buttons/inputs)
    const target = e.target as HTMLElement
    if (target.closest('button, input, textarea, a, [role="button"]')) return

    longPressTimerRef.current = setTimeout(() => {
      setShowLogoutPopup(true)
    }, 5000) // 5 seconds hold
  }, [])

  const handlePointerUp = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }, [])

  const handlePointerLeave = useCallback(() => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }, [])

  const handleLogout = useCallback(() => {
    setShowLogoutPopup(false)
    logout()
  }, [logout])

  return (
    <div
      className="kiosk"
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerLeave}
      onPointerCancel={handlePointerUp}
    >
      {/* Persistent brand lockup, pinned top-centre on every screen (design). */}
      <KioskBrand />

      {screen === 'welcome' && (
        <KioskWelcome onCheckIn={handleCheckIn} />
      )}

      {screen === 'rego' && (
        <KioskRegoEntry
          vehicleCount={vehicles.length}
          onVehicleFound={handleVehicleFound}
          onBack={handleRegoBack}
          onContinue={handleRegoContinue}
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

      {screen === 'consent' && (
        <ReminderConsentStep
          vehicles={consentVehicles}
          consentText={consentText}
          consentTextVersion={consentTextVersion}
          isAutomotive={isAutomotive}
          onChange={setConsentBlock}
          onContinue={handleConsentContinue}
          onBack={handleConsentBack}
        />
      )}

      {screen === 'form' && (
        <KioskCheckInForm
          formData={formData}
          onFormDataChange={handleFormDataChange}
          vehicles={vehicles}
          reminderConsent={consentBlock}
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
        <div className="k-card" style={{ textAlign: 'center' }}>
          <div className="k-ico" style={{ background: 'var(--danger-soft)' }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="var(--danger)" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <h1 style={{ fontSize: '28px' }}>Something went wrong</h1>
          <p className="lead">We couldn&apos;t complete your check-in. Please try again.</p>
          <button
            type="button"
            className="btn-kiosk primary"
            style={{ marginTop: '30px' }}
            onClick={resetToWelcome}
          >
            Start over
          </button>
        </div>
      )}

      {screen === 'clock' && (
        <KioskClockScreen onExit={resetToWelcome} />
      )}

      {/*
       * Floating Staff Clock-In button — bottom-right, welcome screen only.
       *
       * Opens the existing `KioskClockScreen` (employee-id entry → identity
       * confirm → camera → confirmation). The clock screen handles its own
       * upload via POST /api/v2/uploads/clock-photos (which compresses the
       * JPEG to ≤ 2048px on the long edge at quality 82, encrypts it with the
       * envelope key, and writes to /app/uploads/clock_photos/<org_id>/...)
       * and POST /api/v1/kiosk/clock/action which records the time_clock_entry
       * with the photo file_key plus an audit_log row carrying the request
       * client_ip.
       *
       * Only rendered on the welcome screen so the kiosk customer-facing
       * check-in flow is uncluttered. Hidden during QR-popup so the staff
       * button doesn't sit on top of a payment QR.
       */}
      {screen === 'welcome' && !qrSession && (
        <button
          type="button"
          aria-label="Staff clock in or out"
          title="Staff clock in / out"
          onClick={() => setScreen('clock')}
          className="fixed bottom-6 right-6 z-30 inline-flex h-14 w-14 items-center justify-center rounded-full bg-card text-text shadow-pop ring-1 ring-border hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent active:scale-95 transition"
          style={{ minHeight: 56, minWidth: 56 }}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-7 w-7"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
        </button>
      )}

      {/* QR Payment Popup — overlays welcome screen when a pending session is detected */}
      {qrSession && (
        <KioskQrPopup
          session={qrSession}
          onPaymentComplete={() => handleQrDismiss('completed')}
          onExpired={() => handleQrDismiss('expired')}
          onClose={() => handleQrDismiss('manual')}
        />
      )}

      {/* Hidden logout popup — triggered by 5-second long press on empty space */}
      {showLogoutPopup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-72 rounded-card bg-card p-6 shadow-pop text-center space-y-4">
            <p className="text-lg font-semibold text-text">Kiosk Admin</p>
            <p className="text-sm text-muted">Sign out of kiosk mode?</p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setShowLogoutPopup(false)}
                className="flex-1 min-h-[44px] rounded-ctl border border-border-strong px-4 py-2 text-sm font-medium text-text hover:bg-canvas"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleLogout}
                className="flex-1 min-h-[44px] rounded-ctl bg-danger px-4 py-2 text-sm font-medium text-white hover:opacity-90"
              >
                Log Out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default KioskPage
