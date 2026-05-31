/**
 * KioskClockScreen — staff clock-in/out flow for the kiosk tablet.
 *
 * Multi-step flow per design.md §6.1:
 *   1. welcome           — "Staff Clock In" tile.
 *   2. entry             — employee_id entry with on-screen alphanumeric keyboard.
 *   3. confirm-identity  — render on-file photo + first_name; "Take a photo to clock in/out".
 *   4. camera            — capture a photo via browser getUserMedia.
 *   5. confirmation      — side-by-side photos + worked-minutes display, then auto-return.
 *
 * Backend endpoints used (already shipped in Phase 3):
 *   - POST /api/v1/kiosk/clock/lookup        { employee_id } → { staff_id, first_name, on_file_photo_url, currently_clocked_in }
 *   - POST /api/v2/uploads/clock-photos      multipart       → { file_key, file_name, file_size }
 *   - POST /api/v1/kiosk/clock/action        { staff_id, action, photo_file_key, lat?, lng? }
 *                                            → { time_clock_entry_id, action, clock_in_at, clock_out_at, worked_minutes, on_file_photo_url, just_taken_photo_url }
 *
 * Touch targets ≥ 44×44 (mobile-app steering rule, WCAG 2.5.8).
 * All API responses consumed safely with `?.` + `?? null/0/[]` (safe-api-consumption).
 *
 * Requirements: R3 (kiosk clock-in flow). Tasks: D1.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { AxiosError } from 'axios'
import apiClient from '@/api/client'

/* ─────────────────────────────────────────────────────────── Types ── */

export type ClockStep =
  | 'welcome'
  | 'entry'
  | 'confirm-identity'
  | 'camera'
  | 'confirmation'

type ClockAction = 'in' | 'out'

interface LookupResult {
  staff_id: string
  first_name: string
  on_file_photo_url: string | null
  currently_clocked_in: boolean
}

interface ClockActionResult {
  time_clock_entry_id: string
  action: ClockAction
  clock_in_at: string
  clock_out_at: string | null
  worked_minutes: number | null
  on_file_photo_url: string | null
  just_taken_photo_url: string | null
}

interface UploadResult {
  file_key: string
  file_name: string
  file_size: number
}

interface KioskClockScreenProps {
  /** Called when staff taps "Back to home" / countdown finishes. */
  onExit?: () => void
}

/* ───────────────────────────────────────────── Auto-return countdown ── */

const CONFIRMATION_AUTO_RETURN_SECONDS = 8

/* ──────────────────────────────────────────────────── Error mapping ── */

interface ApiError {
  detail?: string
  message?: string
}

function getErrorMessage(err: unknown, context: 'lookup' | 'upload' | 'action'): string {
  const axiosErr = err as AxiosError<ApiError>
  const status = axiosErr?.response?.status
  const detail = axiosErr?.response?.data?.detail ?? ''

  if (context === 'lookup') {
    if (status === 422 || detail === 'employee_not_found' || status === 404) {
      return 'Employee code not recognised. Please see your manager.'
    }
    if (status === 429) {
      if (detail === 'kiosk_lookup_rate_limited') {
        return 'Too many attempts for this employee code. Please wait a minute.'
      }
      return 'Too many lookups. Please wait a moment.'
    }
  }

  if (context === 'action') {
    if (detail === 'photo_required') {
      return 'A photo is required. Please try the camera again.'
    }
    if (detail === 'invalid_action' || status === 409) {
      return 'Looks like your clock-in/out state is out of sync. Please see your manager.'
    }
    if (status === 422) {
      return "We couldn't record this clock action. Please try again."
    }
    if (status === 429) {
      return 'Too many requests. Please wait a moment and try again.'
    }
  }

  if (context === 'upload') {
    if (status === 413) return 'That photo is too large. Please retake it.'
    if (status === 415) return 'That image format is not supported.'
  }

  return "Something went wrong. Please try again or see your manager."
}

/* ────────────────────────────────────────────── On-screen keyboard ── */

const KEYBOARD_ROWS = [
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
  ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
  ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L'],
  ['Z', 'X', 'C', 'V', 'B', 'N', 'M'],
]

const MAX_EMPLOYEE_ID_LENGTH = 24

/* ───────────────────────────────────────────────────── Sub-screens ── */

interface WelcomeProps {
  onStart: () => void
  onExit?: () => void
}

function WelcomeStep({ onStart, onExit }: WelcomeProps) {
  return (
    <div className="w-full max-w-md space-y-8 rounded-xl bg-white p-8 text-center shadow-lg">
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-blue-100">
        <svg
          className="h-8 w-8 text-blue-600"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
      </div>

      <div className="space-y-2">
        <h1 className="text-2xl font-bold text-gray-900">Staff Clock In</h1>
        <p className="text-lg text-gray-600">
          Tap below to clock in or out using your employee code.
        </p>
      </div>

      <button
        type="button"
        onClick={onStart}
        className="inline-flex w-full min-h-[56px] items-center justify-center rounded-lg bg-blue-600 px-8 py-3 text-lg font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
      >
        Start
      </button>

      {onExit && (
        <button
          type="button"
          onClick={onExit}
          className="inline-flex min-h-[44px] items-center justify-center px-4 py-2 text-base font-medium text-gray-500 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Back to home
        </button>
      )}
    </div>
  )
}

interface EntryProps {
  onSubmit: (employeeId: string) => void
  onBack: () => void
  loading: boolean
  error: string | null
}

function EntryStep({ onSubmit, onBack, loading, error }: EntryProps) {
  const [employeeId, setEmployeeId] = useState('')

  const append = useCallback((char: string) => {
    setEmployeeId((prev) =>
      prev.length >= MAX_EMPLOYEE_ID_LENGTH ? prev : prev + char,
    )
  }, [])

  const backspace = useCallback(() => {
    setEmployeeId((prev) => prev.slice(0, -1))
  }, [])

  const clear = useCallback(() => {
    setEmployeeId('')
  }, [])

  const handleSubmit = useCallback(() => {
    const trimmed = employeeId.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }, [employeeId, onSubmit])

  const canSubmit = employeeId.trim().length > 0 && !loading

  return (
    <div className="w-full max-w-2xl space-y-6 rounded-xl bg-white p-6 text-center shadow-lg sm:p-8">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold text-gray-900">Enter your employee code</h1>
        <p className="text-base text-gray-600">
          Type the code printed on your lanyard or locker tag.
        </p>
      </div>

      {/* Display */}
      <div
        aria-live="polite"
        aria-label="Employee code"
        className="mx-auto flex min-h-[64px] w-full items-center justify-center rounded-lg border-2 border-gray-300 bg-gray-50 px-6 py-3 text-center text-3xl font-bold uppercase tracking-widest text-gray-900"
      >
        {employeeId || <span className="text-gray-300">EMP-…</span>}
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700"
        >
          {error}
        </p>
      )}

      {/* Keyboard */}
      <div className="space-y-2">
        {KEYBOARD_ROWS.map((row, idx) => (
          <div key={idx} className="flex flex-wrap justify-center gap-2">
            {row.map((char) => (
              <button
                key={char}
                type="button"
                onClick={() => append(char)}
                disabled={loading}
                className="inline-flex min-h-[48px] min-w-[44px] flex-1 items-center justify-center rounded-md border border-gray-300 bg-white px-3 py-2 text-lg font-semibold text-gray-900 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
                style={{ flexBasis: '40px' }}
              >
                {char}
              </button>
            ))}
          </div>
        ))}

        <div className="flex flex-wrap justify-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => append('-')}
            disabled={loading}
            className="inline-flex min-h-[48px] min-w-[44px] items-center justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-lg font-semibold text-gray-900 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            -
          </button>
          <button
            type="button"
            onClick={backspace}
            disabled={loading || employeeId.length === 0}
            className="inline-flex min-h-[48px] min-w-[88px] items-center justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-base font-medium text-gray-900 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Backspace"
          >
            ⌫
          </button>
          <button
            type="button"
            onClick={clear}
            disabled={loading || employeeId.length === 0}
            className="inline-flex min-h-[48px] min-w-[88px] items-center justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-base font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Actions */}
      <div className="grid grid-cols-2 gap-3 pt-2">
        <button
          type="button"
          onClick={onBack}
          disabled={loading}
          className="inline-flex min-h-[56px] items-center justify-center rounded-lg border border-gray-300 bg-white px-6 py-3 text-lg font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="inline-flex min-h-[56px] items-center justify-center rounded-lg bg-blue-600 px-6 py-3 text-lg font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? 'Looking up…' : 'Continue'}
        </button>
      </div>
    </div>
  )
}

interface IdentityProps {
  lookup: LookupResult
  onTakePhoto: () => void
  onBack: () => void
}

function IdentityConfirmStep({ lookup, onTakePhoto, onBack }: IdentityProps) {
  const action: ClockAction = lookup?.currently_clocked_in ? 'out' : 'in'
  const onFile = lookup?.on_file_photo_url ?? null
  const firstName = lookup?.first_name ?? 'there'

  return (
    <div className="w-full max-w-md space-y-6 rounded-xl bg-white p-8 text-center shadow-lg">
      {/* On-file photo */}
      <div className="mx-auto h-40 w-40 overflow-hidden rounded-full border-4 border-blue-100 bg-gray-100">
        {onFile ? (
          <img
            src={onFile}
            alt={`On-file photo of ${firstName}`}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-gray-300">
            <svg
              className="h-16 w-16"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"
              />
            </svg>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <h2 className="text-2xl font-bold text-gray-900">Hi {firstName}</h2>
        <p className="text-lg text-gray-700">
          {action === 'in'
            ? "Take a photo to clock in."
            : 'Take a photo to clock out.'}
        </p>
        {action === 'out' && (
          <p className="text-sm font-medium text-orange-600">
            You are currently clocked in.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 pt-2">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex min-h-[56px] items-center justify-center rounded-lg border border-gray-300 bg-white px-6 py-3 text-lg font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          Not me
        </button>
        <button
          type="button"
          onClick={onTakePhoto}
          className="inline-flex min-h-[56px] items-center justify-center rounded-lg bg-blue-600 px-6 py-3 text-lg font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Take photo
        </button>
      </div>
    </div>
  )
}

interface CameraProps {
  firstName: string
  action: ClockAction
  onCapture: (blob: Blob, dataUrl: string) => void
  onCancel: () => void
  busy: boolean
  error: string | null
}

function CameraStep({ firstName, action, onCapture, onCancel, busy, error }: CameraProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false

    const start = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          setCameraError('Camera is not available in this browser.')
          return
        }
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
          audio: false,
        })
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        const videoEl = videoRef.current
        if (videoEl) {
          videoEl.srcObject = stream
          // Wait for metadata before marking ready.
          videoEl.onloadedmetadata = () => {
            if (!cancelled) {
              videoEl.play().catch(() => {/* ignored */})
              setReady(true)
            }
          }
        }
      } catch (err: unknown) {
        if (cancelled) return
        const name = (err as { name?: string })?.name ?? ''
        if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
          setCameraError(
            'Camera permission was denied. Please grant access and try again.',
          )
        } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
          setCameraError('No camera found on this device.')
        } else {
          setCameraError('Could not start the camera. Please try again.')
        }
      }
    }

    start()

    return () => {
      cancelled = true
      const stream = streamRef.current
      if (stream) {
        stream.getTracks().forEach((t) => t.stop())
      }
      streamRef.current = null
      setReady(false)
    }
  }, [])

  const handleCapture = useCallback(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !ready) return

    const width = video.videoWidth || 640
    const height = video.videoHeight || 480
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Mirror horizontally so the captured image matches what the staff
    // sees in the preview (front cameras are usually shown mirrored).
    ctx.save()
    ctx.translate(width, 0)
    ctx.scale(-1, 1)
    ctx.drawImage(video, 0, 0, width, height)
    ctx.restore()

    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    canvas.toBlob(
      (blob) => {
        if (blob) onCapture(blob, dataUrl)
      },
      'image/jpeg',
      0.85,
    )
  }, [onCapture, ready])

  const heading = action === 'in' ? `Smile, ${firstName}` : `Almost done, ${firstName}`

  return (
    <div className="w-full max-w-xl space-y-4 rounded-xl bg-white p-6 text-center shadow-lg sm:p-8">
      <h2 className="text-xl font-bold text-gray-900">{heading}</h2>
      <p className="text-sm text-gray-600">
        Centre your face in the frame, then tap <span className="font-semibold">Capture</span>.
      </p>

      <div className="relative mx-auto aspect-[4/3] w-full max-w-md overflow-hidden rounded-lg bg-gray-900">
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          aria-label="Camera preview"
          className="h-full w-full object-cover"
          style={{ transform: 'scaleX(-1)' }}
        />
        <canvas ref={canvasRef} className="hidden" />
        {!ready && !cameraError && (
          <div className="absolute inset-0 flex items-center justify-center text-white">
            Loading camera…
          </div>
        )}
        {cameraError && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 px-4 text-center text-sm font-medium text-white">
            {cameraError}
          </div>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700"
        >
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 pt-1">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="inline-flex min-h-[56px] items-center justify-center rounded-lg border border-gray-300 bg-white px-6 py-3 text-lg font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleCapture}
          disabled={!ready || busy || !!cameraError}
          className="inline-flex min-h-[56px] items-center justify-center rounded-lg bg-blue-600 px-6 py-3 text-lg font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Capture'}
        </button>
      </div>
    </div>
  )
}

interface ConfirmationProps {
  result: ClockActionResult
  firstName: string
  capturedDataUrl: string | null
  secondsLeft: number
  onDone: () => void
}

function ConfirmationStep({
  result,
  firstName,
  capturedDataUrl,
  secondsLeft,
  onDone,
}: ConfirmationProps) {
  const action = result?.action ?? 'in'
  const onFile = result?.on_file_photo_url ?? null
  const justTaken = capturedDataUrl ?? result?.just_taken_photo_url ?? null
  const workedMinutes = result?.worked_minutes ?? null
  const clockTime = action === 'out' ? result?.clock_out_at : result?.clock_in_at

  const formatTime = (iso: string | null | undefined): string => {
    if (!iso) return ''
    try {
      return new Date(iso).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return ''
    }
  }

  const formatWorked = (mins: number | null): string => {
    if (mins === null || mins === undefined) return ''
    const safe = mins < 0 ? 0 : mins
    const h = Math.floor(safe / 60)
    const m = safe % 60
    if (h > 0 && m > 0) return `${h}h ${m}m`
    if (h > 0) return `${h}h`
    return `${m}m`
  }

  return (
    <div className="w-full max-w-2xl space-y-6 rounded-xl bg-white p-6 text-center shadow-lg sm:p-8">
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

      <div className="space-y-1">
        <h2 className="text-2xl font-bold text-gray-900">
          {action === 'in'
            ? `Clocked in at ${formatTime(clockTime)}`
            : `Clocked out at ${formatTime(clockTime)}`}
        </h2>
        <p className="text-lg text-gray-700">
          {action === 'in'
            ? `Have a great shift, ${firstName}.`
            : `Thanks ${firstName} — see you next time.`}
        </p>
        {action === 'out' && workedMinutes !== null && (
          <p className="text-base font-medium text-blue-700">
            Worked: {formatWorked(workedMinutes)}
          </p>
        )}
      </div>

      {/* Side-by-side photos */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            On file
          </p>
          <div className="mx-auto aspect-square w-full max-w-[180px] overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
            {onFile ? (
              <img
                src={onFile}
                alt={`On-file photo of ${firstName}`}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-xs text-gray-400">
                No photo on file
              </div>
            )}
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Just taken
          </p>
          <div className="mx-auto aspect-square w-full max-w-[180px] overflow-hidden rounded-lg border border-gray-200 bg-gray-50">
            {justTaken ? (
              <img
                src={justTaken}
                alt="Photo just taken"
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-xs text-gray-400">
                —
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-col items-center gap-2">
        <p className="text-sm text-gray-500">
          Returning to home in {secondsLeft}s…
        </p>
        <button
          type="button"
          onClick={onDone}
          className="inline-flex min-h-[48px] items-center justify-center rounded-lg bg-blue-600 px-8 py-3 text-base font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Done
        </button>
      </div>
    </div>
  )
}

/* ───────────────────────────────────────────── KioskClockScreen ── */

export function KioskClockScreen({ onExit }: KioskClockScreenProps = {}) {
  const [step, setStep] = useState<ClockStep>('welcome')
  const [employeeId, setEmployeeId] = useState('')
  const [lookup, setLookup] = useState<LookupResult | null>(null)
  const [actionResult, setActionResult] = useState<ClockActionResult | null>(null)
  const [capturedDataUrl, setCapturedDataUrl] = useState<string | null>(null)
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [lookupLoading, setLookupLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(CONFIRMATION_AUTO_RETURN_SECONDS)

  const lookupAbortRef = useRef<AbortController | null>(null)
  const actionAbortRef = useRef<AbortController | null>(null)

  /** Reset the entire flow back to the welcome screen. */
  const resetFlow = useCallback(() => {
    lookupAbortRef.current?.abort()
    actionAbortRef.current?.abort()
    lookupAbortRef.current = null
    actionAbortRef.current = null

    setStep('welcome')
    setEmployeeId('')
    setLookup(null)
    setActionResult(null)
    setCapturedDataUrl(null)
    setLookupError(null)
    setActionError(null)
    setLookupLoading(false)
    setActionLoading(false)
    setSecondsLeft(CONFIRMATION_AUTO_RETURN_SECONDS)
  }, [])

  /** Cleanup any in-flight requests on unmount. */
  useEffect(() => {
    return () => {
      lookupAbortRef.current?.abort()
      actionAbortRef.current?.abort()
    }
  }, [])

  /** Confirmation auto-return countdown. */
  useEffect(() => {
    if (step !== 'confirmation') return

    if (secondsLeft <= 0) {
      resetFlow()
      return
    }

    const t = setTimeout(() => setSecondsLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [step, secondsLeft, resetFlow])

  /* ── Step 2: lookup ───────────────────────────────────────── */

  const handleLookup = useCallback(async (id: string) => {
    setLookupError(null)
    setLookupLoading(true)
    setEmployeeId(id)

    lookupAbortRef.current?.abort()
    const controller = new AbortController()
    lookupAbortRef.current = controller

    try {
      const res = await apiClient.post<LookupResult>(
        '/kiosk/clock/lookup',
        { employee_id: id },
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return

      const data = res.data
      const safe: LookupResult = {
        staff_id: data?.staff_id ?? '',
        first_name: data?.first_name ?? '',
        on_file_photo_url: data?.on_file_photo_url ?? null,
        currently_clocked_in: data?.currently_clocked_in ?? false,
      }
      if (!safe.staff_id) {
        setLookupError('Employee code not recognised. Please see your manager.')
        return
      }
      setLookup(safe)
      setStep('confirm-identity')
    } catch (err: unknown) {
      if (controller.signal.aborted) return
      setLookupError(getErrorMessage(err, 'lookup'))
    } finally {
      if (!controller.signal.aborted) {
        setLookupLoading(false)
      }
    }
  }, [])

  /* ── Step 4 → 5: upload + clock action ────────────────────── */

  const handleCapture = useCallback(
    async (blob: Blob, dataUrl: string) => {
      if (!lookup) return
      setActionError(null)
      setActionLoading(true)
      setCapturedDataUrl(dataUrl)

      actionAbortRef.current?.abort()
      const controller = new AbortController()
      actionAbortRef.current = controller

      try {
        // 1. Upload the photo to /api/v2/uploads/clock-photos.
        const formData = new FormData()
        const filename = `clock-${Date.now()}.jpg`
        formData.append('file', blob, filename)

        const uploadRes = await apiClient.post<UploadResult>(
          '/api/v2/uploads/clock-photos',
          formData,
          {
            headers: { 'Content-Type': 'multipart/form-data' },
            signal: controller.signal,
          },
        )
        if (controller.signal.aborted) return

        const fileKey = uploadRes.data?.file_key ?? ''
        if (!fileKey) {
          setActionError("We couldn't save your photo. Please try again.")
          return
        }

        // 2. Submit the clock action.
        const action: ClockAction = lookup.currently_clocked_in ? 'out' : 'in'
        const actionRes = await apiClient.post<ClockActionResult>(
          '/kiosk/clock/action',
          {
            staff_id: lookup.staff_id,
            action,
            photo_file_key: fileKey,
          },
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return

        const data = actionRes.data
        const safe: ClockActionResult = {
          time_clock_entry_id: data?.time_clock_entry_id ?? '',
          action: data?.action ?? action,
          clock_in_at: data?.clock_in_at ?? '',
          clock_out_at: data?.clock_out_at ?? null,
          worked_minutes: data?.worked_minutes ?? null,
          on_file_photo_url: data?.on_file_photo_url ?? lookup.on_file_photo_url ?? null,
          just_taken_photo_url: data?.just_taken_photo_url ?? null,
        }
        setActionResult(safe)
        setSecondsLeft(CONFIRMATION_AUTO_RETURN_SECONDS)
        setStep('confirmation')
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        const axiosErr = err as AxiosError<ApiError>
        const url = axiosErr?.config?.url ?? ''
        const ctx: 'upload' | 'action' = url.includes('/uploads/') ? 'upload' : 'action'
        setActionError(getErrorMessage(err, ctx))
      } finally {
        if (!controller.signal.aborted) {
          setActionLoading(false)
        }
      }
    },
    [lookup],
  )

  /* ── Render ──────────────────────────────────────────────── */

  if (step === 'welcome') {
    return (
      <WelcomeStep
        onStart={() => {
          setLookupError(null)
          setStep('entry')
        }}
        onExit={onExit}
      />
    )
  }

  if (step === 'entry') {
    return (
      <EntryStep
        onSubmit={handleLookup}
        onBack={resetFlow}
        loading={lookupLoading}
        error={lookupError}
      />
    )
  }

  if (step === 'confirm-identity' && lookup) {
    return (
      <IdentityConfirmStep
        lookup={lookup}
        onTakePhoto={() => {
          setActionError(null)
          setCapturedDataUrl(null)
          setStep('camera')
        }}
        onBack={resetFlow}
      />
    )
  }

  if (step === 'camera' && lookup) {
    const action: ClockAction = lookup.currently_clocked_in ? 'out' : 'in'
    return (
      <CameraStep
        firstName={lookup.first_name ?? ''}
        action={action}
        onCapture={handleCapture}
        onCancel={() => {
          setActionError(null)
          setCapturedDataUrl(null)
          setStep('confirm-identity')
        }}
        busy={actionLoading}
        error={actionError}
      />
    )
  }

  if (step === 'confirmation' && actionResult) {
    return (
      <ConfirmationStep
        result={actionResult}
        firstName={lookup?.first_name ?? ''}
        capturedDataUrl={capturedDataUrl}
        secondsLeft={secondsLeft}
        onDone={resetFlow}
      />
    )
  }

  // Fallback — invalid state, send back to welcome.
  // employeeId is referenced here so unused-locals stays quiet for the
  // diagnostic-debug case where ops want to inspect last-attempted code.
  void employeeId
  return (
    <WelcomeStep
      onStart={() => setStep('entry')}
      onExit={onExit}
    />
  )
}

export default KioskClockScreen
