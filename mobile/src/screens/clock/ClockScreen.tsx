/**
 * ClockScreen — mobile self-service clock-in/out screen.
 *
 * Mounted at `/clock` (lazy-loaded in `mobile/src/navigation/StackRoutes.tsx`).
 * Wraps content in `ModuleGate moduleSlug="staff_management"`.
 *
 * Mirrors the web `SelfServiceClockScreen.tsx` (D3) UX:
 *   - Single big "Clock in" / "Clock out" button (full-width, large touch
 *     target ≥ 44×44).
 *   - Hides the Clock button when `staff.self_service_clock_enabled=false`
 *     and shows a "Use the kiosk" banner instead.
 *   - "I'm running late" button (G3 / R14b.6): visible when (a) staff is
 *     NOT currently clocked in AND (b) staff has an in-window scheduled
 *     shift in `[now-60m, now+120m]`. Tapping opens `RunningLateSheet`.
 *   - Capacitor camera + geolocation guarded by `isNativePlatform()`.
 *   - Photo upload uses `POST /api/v2/uploads/clock-photos` (multipart
 *     returns `{ file_key }`); clock-action POSTs `photo_file_key`.
 *
 * Refs: Phase 3 R4 (self-service clock-in/out — mobile), R14b
 * (running-late upward message), G3, design §6.4. Touch targets ≥ 44×44,
 * `pb-safe` for safe-area inset, safe API consumption per
 * #[[file:.kiro/steering/safe-api-consumption.md]] (every API access uses
 * `?.` chaining and `?? null/0/[]`), AbortController in every useEffect.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import axios from 'axios'

import apiClient from '@/api/client'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { useAuth } from '@/contexts/AuthContext'
import { MobileSpinner } from '@/components/ui'

import RunningLateSheet from './RunningLateSheet'

/* ─────────────────────────────────────────────────────── Types ─── */

type ClockAction = 'in' | 'out'

interface StaffMember {
  id: string
  user_id: string | null
  first_name: string
  last_name: string | null
  on_file_photo_url: string | null
  self_service_clock_enabled: boolean
}

interface ClockEntry {
  id: string
  clock_in_at: string
  clock_out_at: string | null
  worked_minutes: number | null
  source: string
}

interface ScheduleEntry {
  id: string
  staff_id: string | null
  start_time: string
  end_time: string
  status: string
  entry_type: string
  title?: string | null
}

interface UploadResult {
  file_key: string
  file_name?: string | null
  file_size?: number | null
}

interface SelfServiceActionResult {
  time_clock_entry_id: string
  action: ClockAction
  source: string
  clock_in_at: string
  clock_out_at: string | null
  worked_minutes: number | null
}

interface OrgClockInPolicy {
  self_service_require_photo?: boolean | null
  self_service_require_geofence?: boolean | null
}

/* ────────────────────────────────────────── Constants & helpers ─── */

const IN_WINDOW_LOOKBACK_MIN = 60
const IN_WINDOW_LOOKAHEAD_MIN = 120

function isNativePlatform(): boolean {
  return !!(window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } })
    ?.Capacitor?.isNativePlatform?.()
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

function formatWorked(mins: number | null | undefined): string {
  if (mins == null) return ''
  const safe = Math.max(0, mins)
  const h = Math.floor(safe / 60)
  const m = safe % 60
  if (h > 0 && m > 0) return `${h}h ${m}m`
  if (h > 0) return `${h}h`
  return `${m}m`
}

function shiftLabel(entry: ScheduleEntry | null | undefined): string {
  if (!entry) return ''
  const start = formatTime(entry?.start_time)
  const end = formatTime(entry?.end_time)
  const title = entry?.title ?? ''
  const range = start && end ? `${start} → ${end}` : start || end
  return title ? `${title} (${range})` : range
}

function readErrorDetail(err: unknown): string | null {
  if (axios.isCancel?.(err)) return null
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (
    detail &&
    typeof detail === 'object' &&
    'detail' in detail &&
    typeof (detail as { detail?: unknown }).detail === 'string'
  ) {
    return (detail as { detail: string }).detail
  }
  return null
}

function isAbortError(err: unknown): boolean {
  if (axios.isCancel?.(err)) return true
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code?: string }).code === 'ERR_CANCELED'
  ) {
    return true
  }
  return false
}

/* ─────────────────────────────────── Native photo capture ─── */

/**
 * Capture a photo via the Capacitor camera plugin (native) or the web
 * `getUserMedia` API (web fallback). Returns a Blob suitable for upload
 * via multipart form-data.
 */
async function capturePhoto(): Promise<{ blob: Blob; dataUrl: string } | null> {
  if (isNativePlatform()) {
    try {
      const { Camera, CameraResultType, CameraSource } = await import(
        '@capacitor/camera'
      )
      const photo = await Camera.getPhoto({
        quality: 85,
        allowEditing: false,
        resultType: CameraResultType.DataUrl,
        source: CameraSource.Camera,
        width: 800,
        height: 800,
      })
      const dataUrl = photo?.dataUrl ?? ''
      if (!dataUrl) return null
      // Convert dataURL → Blob for multipart upload.
      const res = await fetch(dataUrl)
      const blob = await res.blob()
      return { blob, dataUrl }
    } catch {
      return null
    }
  }

  // Web fallback — getUserMedia + canvas.
  if (!navigator.mediaDevices?.getUserMedia) return null
  let stream: MediaStream | null = null
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: 'user',
        width: { ideal: 640 },
        height: { ideal: 480 },
      },
      audio: false,
    })
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    await new Promise<void>((resolve, reject) => {
      video.onloadedmetadata = () => {
        video.play().then(() => resolve()).catch(reject)
      }
      video.onerror = () => reject(new Error('camera_unavailable'))
    })
    await new Promise((r) => setTimeout(r, 250))
    const width = video.videoWidth || 640
    const height = video.videoHeight || 480
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.save()
    ctx.translate(width, 0)
    ctx.scale(-1, 1)
    ctx.drawImage(video, 0, 0, width, height)
    ctx.restore()
    const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85),
    )
    if (!blob) return null
    return { blob, dataUrl }
  } catch {
    return null
  } finally {
    stream?.getTracks().forEach((t) => t.stop())
  }
}

/**
 * Get the device's current position (Capacitor Geolocation on native,
 * `navigator.geolocation` in the browser). Returns null on permission
 * denial, timeout, or unsupported environment.
 */
async function getCurrentPosition(
  signal?: AbortSignal,
): Promise<{ lat: number; lng: number } | null> {
  if (signal?.aborted) return null
  if (isNativePlatform()) {
    try {
      const { Geolocation } = await import('@capacitor/geolocation')
      const pos = await Geolocation.getCurrentPosition({
        enableHighAccuracy: false,
        timeout: 10_000,
      })
      if (signal?.aborted) return null
      return {
        lat: pos?.coords?.latitude ?? 0,
        lng: pos?.coords?.longitude ?? 0,
      }
    } catch {
      return null
    }
  }

  if (!navigator.geolocation) return null
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve(null)
      return
    }
    const timer = setTimeout(() => resolve(null), 12_000)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(timer)
        if (signal?.aborted) {
          resolve(null)
          return
        }
        resolve({
          lat: pos?.coords?.latitude ?? 0,
          lng: pos?.coords?.longitude ?? 0,
        })
      },
      () => {
        clearTimeout(timer)
        resolve(null)
      },
      { enableHighAccuracy: false, maximumAge: 60_000, timeout: 10_000 },
    )
  })
}

/* ─────────────────────────────────────────── Page component ─── */

function ClockScreenInner() {
  const { user } = useAuth()
  const userId = user?.id ?? null

  const [staff, setStaff] = useState<StaffMember | null>(null)
  const [openEntry, setOpenEntry] = useState<ClockEntry | null>(null)
  const [policy, setPolicy] = useState<OrgClockInPolicy>({})
  const [inWindowShift, setInWindowShift] = useState<ScheduleEntry | null>(null)

  const [loading, setLoading] = useState<boolean>(true)
  const [refreshing, setRefreshing] = useState<boolean>(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState<number>(0)

  const [busy, setBusy] = useState<boolean>(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  const [runningLateOpen, setRunningLateOpen] = useState<boolean>(false)

  const isMounted = useRef<boolean>(true)
  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
    }
  }, [])

  /* ── Load staff record + open entry + policy + in-window shift ─── */
  useEffect(() => {
    if (!userId) {
      setLoading(false)
      setLoadError('You need to sign in to use self-service clock-in.')
      return
    }

    const controller = new AbortController()

    const load = async () => {
      setLoading(true)
      setLoadError(null)
      try {
        // 1. Find the staff record linked to this user.
        const staffRes = await apiClient.get<{
          staff?: StaffMember[]
          items?: StaffMember[]
          total?: number
        }>('/api/v2/staff', {
          params: { is_active: 'true', page_size: 200 },
          signal: controller.signal,
        })
        if (controller.signal.aborted) return
        const list = staffRes.data?.staff ?? staffRes.data?.items ?? []
        const me =
          (list ?? []).find((s) => (s?.user_id ?? null) === userId) ?? null
        if (!me) {
          if (!isMounted.current) return
          setStaff(null)
          setLoadError(
            'No staff record is linked to your login. Please ask your manager to link your account.',
          )
          setLoading(false)
          return
        }
        if (!isMounted.current) return
        setStaff({
          id: me?.id ?? '',
          user_id: me?.user_id ?? null,
          first_name: me?.first_name ?? '',
          last_name: me?.last_name ?? null,
          on_file_photo_url: me?.on_file_photo_url ?? null,
          self_service_clock_enabled: !!me?.self_service_clock_enabled,
        })

        // 2. Pull the current week's clock entries (find open one) +
        //    the org clock-in policy + nearby scheduled shifts.
        const today = new Date()
        const weekStart = new Date(today)
        const day = weekStart.getDay()
        const diff = day === 0 ? -6 : 1 - day
        weekStart.setDate(weekStart.getDate() + diff)
        const pad = (n: number) => String(n).padStart(2, '0')
        const weekIso = `${weekStart.getFullYear()}-${pad(
          weekStart.getMonth() + 1,
        )}-${pad(weekStart.getDate())}`

        const [entriesResult, settingsResult, scheduleResult] =
          await Promise.allSettled([
            apiClient.get<{ items?: ClockEntry[]; total?: number }>(
              `/api/v2/staff/${me?.id ?? ''}/clock`,
              { params: { week: weekIso }, signal: controller.signal },
            ),
            apiClient.get<{ clock_in_policy?: OrgClockInPolicy | null }>(
              '/org/settings',
              { signal: controller.signal },
            ),
            apiClient.get<{ entries?: ScheduleEntry[]; total?: number }>(
              '/api/v2/schedule',
              {
                params: {
                  staff_id: me?.id ?? '',
                  start: new Date(
                    Date.now() - IN_WINDOW_LOOKBACK_MIN * 60_000,
                  ).toISOString(),
                  end: new Date(
                    Date.now() + IN_WINDOW_LOOKAHEAD_MIN * 60_000,
                  ).toISOString(),
                },
                signal: controller.signal,
              },
            ),
          ])

        if (controller.signal.aborted || !isMounted.current) return

        if (entriesResult.status === 'fulfilled') {
          const items = entriesResult.value.data?.items ?? []
          const open = (items ?? []).find((e) => !e?.clock_out_at) ?? null
          setOpenEntry(open)
        } else {
          setOpenEntry(null)
        }

        if (settingsResult.status === 'fulfilled') {
          const pol = settingsResult.value.data?.clock_in_policy ?? {}
          setPolicy({
            self_service_require_photo:
              pol?.self_service_require_photo ?? true,
            self_service_require_geofence:
              pol?.self_service_require_geofence ?? false,
          })
        } else {
          setPolicy({
            self_service_require_photo: true,
            self_service_require_geofence: false,
          })
        }

        if (scheduleResult.status === 'fulfilled') {
          const entries = scheduleResult.value.data?.entries ?? []
          const now = Date.now()
          const candidate = (entries ?? [])
            .filter(
              (e) =>
                (e?.staff_id ?? null) === (me?.id ?? '') &&
                e?.status !== 'cancelled' &&
                ['job', 'booking', 'other'].includes(e?.entry_type ?? ''),
            )
            .map((e) => ({
              entry: e,
              delta: Math.abs(
                new Date(e?.start_time ?? '').getTime() - now,
              ),
            }))
            .filter((row) => Number.isFinite(row.delta))
            .sort((a, b) => a.delta - b.delta)[0]?.entry
          setInWindowShift(candidate ?? null)
        } else {
          setInWindowShift(null)
        }
      } catch (err) {
        if (controller.signal.aborted || isAbortError(err)) return
        if (!isMounted.current) return
        setLoadError('Failed to load your clock-in info.')
      } finally {
        if (!controller.signal.aborted && isMounted.current) {
          setLoading(false)
          setRefreshing(false)
        }
      }
    }

    void load()
    return () => controller.abort()
  }, [userId, refreshKey])

  const refresh = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  const handlePullRefresh = useCallback(async (): Promise<void> => {
    setRefreshing(true)
    setActionError(null)
    setActionMessage(null)
    refresh()
  }, [refresh])

  /* ── Action: clock in / clock out ────────────────────────────── */

  const action: ClockAction = openEntry ? 'out' : 'in'

  const handleClockAction = useCallback(async () => {
    if (!staff || busy) return
    setBusy(true)
    setActionError(null)
    setActionMessage(null)
    const controller = new AbortController()
    const requirePhoto = policy?.self_service_require_photo ?? true
    const requireGeofence = policy?.self_service_require_geofence ?? false

    let photoFileKey: string | null = null
    try {
      if (requirePhoto) {
        const captured = await capturePhoto()
        if (!captured) {
          setActionError(
            "We couldn't take your photo. Please grant camera permission, or use the on-site kiosk.",
          )
          return
        }
        const formData = new FormData()
        formData.append(
          'file',
          captured.blob,
          `clock-${Date.now()}.jpg`,
        )
        try {
          const uploadRes = await apiClient.post<UploadResult>(
            '/api/v2/uploads/clock-photos',
            formData,
            {
              headers: { 'Content-Type': 'multipart/form-data' },
              signal: controller.signal,
            },
          )
          if (controller.signal.aborted) return
          photoFileKey = uploadRes.data?.file_key ?? null
          if (!photoFileKey) {
            setActionError(
              "We couldn't save your photo. Please refresh and try again.",
            )
            return
          }
        } catch (err) {
          if (controller.signal.aborted || isAbortError(err)) return
          setActionError(
            "We couldn't upload your photo. Please check your connection and try again.",
          )
          return
        }
      }

      let lat: number | null = null
      let lng: number | null = null
      if (requireGeofence) {
        const pos = await getCurrentPosition(controller.signal)
        if (controller.signal.aborted) return
        if (!pos) {
          setActionError(
            'We need your location to clock in/out from this device. Please grant permission, or use the on-site kiosk.',
          )
          return
        }
        lat = pos.lat
        lng = pos.lng
      }

      const payload: Record<string, unknown> = { action }
      if (photoFileKey) payload.photo_file_key = photoFileKey
      if (lat !== null) payload.lat = lat
      if (lng !== null) payload.lng = lng

      const res = await apiClient.post<SelfServiceActionResult>(
        '/api/v2/staff/me/clock-action',
        payload,
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return

      const data = res.data
      const safe: SelfServiceActionResult = {
        time_clock_entry_id: data?.time_clock_entry_id ?? '',
        action: data?.action ?? action,
        source: data?.source ?? '',
        clock_in_at: data?.clock_in_at ?? '',
        clock_out_at: data?.clock_out_at ?? null,
        worked_minutes: data?.worked_minutes ?? null,
      }
      if (safe.action === 'out') {
        setActionMessage(
          `Clocked out at ${formatTime(safe.clock_out_at)}${
            safe.worked_minutes != null
              ? ` · Worked ${formatWorked(safe.worked_minutes)}`
              : ''
          }`,
        )
      } else {
        setActionMessage(`Clocked in at ${formatTime(safe.clock_in_at)}`)
      }
      // Re-load to pick up the newly-open entry (or clear it after clock-out).
      refresh()
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return
      const detail = readErrorDetail(err)
      const status = (err as { response?: { status?: number } })?.response
        ?.status
      if (detail === 'self_service_disabled' || status === 403) {
        setActionError(
          'Self-service clock-in is not enabled — please use the on-site kiosk.',
        )
      } else if (detail === 'photo_required') {
        setActionError(
          "A photo is required. We couldn't capture one — please try again.",
        )
      } else if (detail === 'geofence_failed') {
        setActionError(
          "You're too far from your branch to clock in/out from here.",
        )
      } else if (detail === 'already_clocked_in') {
        setActionError("You're already clocked in. Refresh to update.")
      } else if (detail === 'not_clocked_in') {
        setActionError("You're not currently clocked in. Refresh to update.")
      } else {
        setActionError('Could not record your clock action. Please try again.')
      }
    } finally {
      if (!controller.signal.aborted && isMounted.current) {
        setBusy(false)
      }
    }
  }, [staff, busy, policy, action, refresh])

  /* ── Derived state + greeting ─────────────────────────────────── */

  const showClockButton = !!staff?.self_service_clock_enabled
  const showRunningLate = !openEntry && !!inWindowShift

  const greeting = useMemo(() => {
    const first = staff?.first_name ?? user?.name ?? 'there'
    const hour = new Date().getHours()
    if (hour < 12) return `Good morning, ${first}.`
    if (hour < 18) return `Good afternoon, ${first}.`
    return `Good evening, ${first}.`
  }, [staff, user])

  /* ── Render ───────────────────────────────────────────────────── */

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="flex flex-col gap-3 px-4 pt-6 pb-safe">
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300"
          data-testid="mobile-clock-load-error"
        >
          {loadError}
        </div>
      </div>
    )
  }

  return (
    <PullRefresh onRefresh={handlePullRefresh} isRefreshing={refreshing}>
      <div
        className="mx-auto flex w-full max-w-md flex-col gap-4 px-4 pt-6 pb-safe"
        data-testid="mobile-clock-screen"
      >
        <header className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            {greeting}
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {openEntry
              ? `You're clocked in since ${formatTime(openEntry.clock_in_at)}`
              : 'Use the button below to clock in or out.'}
          </p>
        </header>

        {!showClockButton && (
          <div
            role="status"
            className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-100"
            data-testid="mobile-clock-disabled-banner"
          >
            Self-service clock-in is not enabled for your account. Please use
            the on-site kiosk to clock in and out, or talk to your manager.
          </div>
        )}

        {showClockButton && (
          <button
            type="button"
            onClick={() => void handleClockAction()}
            disabled={busy}
            aria-busy={busy || undefined}
            className={`flex min-h-[120px] w-full items-center justify-center rounded-2xl px-6 py-6 text-2xl font-semibold text-white shadow-lg transition-colors focus:outline-none focus:ring-4 focus:ring-blue-300 disabled:cursor-not-allowed disabled:opacity-60 ${
              action === 'in'
                ? 'bg-blue-600 active:bg-blue-700'
                : 'bg-emerald-600 active:bg-emerald-700'
            }`}
            data-testid="mobile-clock-button"
          >
            {busy ? 'Working…' : action === 'in' ? 'Clock in' : 'Clock out'}
          </button>
        )}

        {actionMessage && (
          <p
            role="status"
            className="rounded-md bg-emerald-50 px-3 py-2 text-center text-sm font-medium text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200"
            data-testid="mobile-clock-action-success"
          >
            {actionMessage}
          </p>
        )}

        {actionError && (
          <p
            role="alert"
            className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300"
            data-testid="mobile-clock-action-error"
          >
            {actionError}
          </p>
        )}

        {showRunningLate && inWindowShift && (
          <button
            type="button"
            onClick={() => setRunningLateOpen(true)}
            className="min-h-[44px] w-full rounded-lg border border-amber-400 bg-white px-4 py-3 text-sm font-semibold text-amber-700 active:bg-amber-50 dark:border-amber-600 dark:bg-gray-900 dark:text-amber-300 dark:active:bg-amber-900/20"
            data-testid="mobile-running-late-button"
          >
            I'm running late {inWindowShift && `(${shiftLabel(inWindowShift)})`}
          </button>
        )}

        <RunningLateSheet
          open={runningLateOpen}
          onClose={() => setRunningLateOpen(false)}
          onSent={() => {
            setRunningLateOpen(false)
            setActionMessage('Manager has been notified you are running late.')
          }}
        />
      </div>
    </PullRefresh>
  )
}

/**
 * `ClockScreen` — module-gated wrapper. Falls back to a friendly banner
 * when the `staff_management` module is not enabled for the org.
 */
export default function ClockScreen() {
  return (
    <ModuleGate
      moduleSlug="staff_management"
      fallback={
        <div className="px-4 pt-6 pb-safe">
          <div
            role="status"
            className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-100"
            data-testid="mobile-clock-module-disabled"
          >
            The Staff Management module is not enabled for your organisation.
            Talk to your org admin to turn it on.
          </div>
        </div>
      }
    >
      <ClockScreenInner />
    </ModuleGate>
  )
}
