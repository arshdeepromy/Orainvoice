/**
 * Authenticated Employee Portal shell (task 14.2).
 *
 * Route: ``/e/:slug/*`` (registered in App.tsx by task 14.3), mounted ABOVE the
 * marketing ``PublicPageRenderer`` catch-all and outside ``RequireAuth`` —
 * authentication here is the portal's own HttpOnly ``emp_portal_session`` cookie,
 * NOT the staff-app JWT.
 *
 * This is the MVP capability floor (design D3, R7.2): a **profile** view and a
 * **roster** view for the authenticated Portal_User's own staff record, plus a
 * logout action. It is a deliberate sibling of the branded login at ``/e/:slug``
 * (task 14.1).
 *
 * Why raw ``axios`` (not the shared ``apiClient``): the shared client injects the
 * staff-app auth headers and redirects to ``/login`` on a ``401`` — wrong for a
 * cookie-authenticated public portal. We use a bare axios instance with
 * ``withCredentials: true`` so the ``/e``-scoped cookies ride along, exactly the
 * rule the onboarding/roster public pages follow.
 *
 * CSRF (R6.7, R6.8): state-changing calls (logout) echo the readable
 * ``emp_portal_csrf`` cookie back as the ``X-CSRF-Token`` header (double-submit).
 *
 * Completeness (frontend-feature-completeness steering): every authenticated
 * view implements the full state set — a loading skeleton during fetch, an empty
 * state with a helpful message, and an error state with a retry action on
 * failure. Never a blank screen. A ``401 session_invalid`` routes back to the
 * branded login. Every fetch ``useEffect`` uses an ``AbortController`` and
 * consumes data safely (``res.data?.x ?? default``, typed generics, no ``as any``).
 *
 * noindex (R8.7): authenticated portal pages are marked noindex via usePageMeta.
 *
 * _Requirements: 7.1, 7.2, 7.7, 8.7, 13.1_
 */

import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import axios, { type AxiosError } from 'axios'

import { usePageMeta } from '../../hooks/usePageMeta'

/* ── API base + bare client (cookie auth, no staff-app headers) ── */

const EP_API_BASE = '/e/api'
const CSRF_COOKIE_NAME = 'emp_portal_csrf'

/** Read a non-HttpOnly cookie value by name (the CSRF cookie is JS-readable). */
function readCookie(name: string): string | null {
  const target = `${name}=`
  const parts = document.cookie ? document.cookie.split('; ') : []
  for (const part of parts) {
    if (part.startsWith(target)) {
      return decodeURIComponent(part.slice(target.length))
    }
  }
  return null
}

/** True when an axios error carries an HTTP 401 (session invalid). */
function isUnauthorised(err: unknown): boolean {
  return axios.isAxiosError(err) && err.response?.status === 401
}

/** Extract the backend ``{message, code}`` envelope from an axios error. */
function errorEnvelope(err: unknown): { message?: string; code?: string } {
  if (axios.isAxiosError(err)) {
    const data = (err as AxiosError<{ message?: string; code?: string }>).response
      ?.data
    return { message: data?.message, code: data?.code }
  }
  return {}
}

/* ── API response types (mirror app/modules/employee_portal/schemas.py) ── */

interface Branding {
  logo_url: string | null
  primary_colour: string | null
  secondary_colour: string | null
}

interface MeResponse {
  portal_user_id: string
  email: string | null
  first_name: string | null
  staff_id: string | null
  org_name: string | null
  branding: Branding | null
}

interface ProfileResponse {
  staff_id: string
  first_name: string | null
  last_name: string | null
  name: string | null
  email: string | null
  phone: string | null
  position: string | null
  employee_id: string | null
  employment_basis: string | null
  employment_type: string | null
  working_arrangement: string | null
  employment_start_date: string | null
  tax_code: string | null
  kiwisaver_enrolled: boolean | null
  ird_number: string | null
  bank_account_number: string | null
  emergency_contact_name: string | null
  emergency_contact_phone: string | null
}

interface RosterEntry {
  start_time: string | null
  end_time: string | null
  title: string | null
  notes: string | null
  entry_type: string | null
}

interface RosterResponse {
  staff_id: string
  week_start: string
  week_end: string
  entries: RosterEntry[]
}

type PortalView = 'profile' | 'roster'

/* ── Date / time formatting helpers (en-NZ, local tz) ── */

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-NZ', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('en-NZ', {
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatWeekRange(weekStart: string, weekEnd: string): string {
  // week_end is exclusive (week_start + 7d); show the inclusive last day.
  let lastDay = weekEnd
  try {
    const end = new Date(weekEnd)
    end.setDate(end.getDate() - 1)
    lastDay = end.toISOString().slice(0, 10)
  } catch {
    /* fall back to the raw exclusive end */
  }
  return `${formatDate(weekStart)} – ${formatDate(lastDay)}`
}

function isoWeekStart(date: Date): string {
  // Monday of the week containing `date`, as YYYY-MM-DD (local).
  const d = new Date(date)
  const day = (d.getDay() + 6) % 7 // 0 = Monday
  d.setDate(d.getDate() - day)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`
}

function shiftWeek(weekStart: string, deltaWeeks: number): string {
  try {
    const d = new Date(`${weekStart}T00:00:00`)
    d.setDate(d.getDate() + deltaWeeks * 7)
    return isoWeekStart(d)
  } catch {
    return weekStart
  }
}

/* ── Shared presentational primitives (loading / empty / error) ── */

function SkeletonBlock({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-gray-200 ${className}`} />
}

function ErrorState({
  title,
  message,
  onRetry,
}: {
  title: string
  message: string
  onRetry: () => void
}) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
      <h2 className="text-base font-semibold text-red-900">{title}</h2>
      <p className="mt-1 text-sm text-red-700">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 inline-flex items-center rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
      >
        Try again
      </button>
    </div>
  )
}

function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      <p className="mt-1 text-sm text-gray-500">{message}</p>
    </div>
  )
}

/* ── Profile view (R7.1, R7.7) ── */

function ProfileField({
  label,
  value,
}: {
  label: string
  value: string | null | undefined
}) {
  return (
    <div className="py-3">
      <dt className="text-xs uppercase tracking-wide text-gray-500">{label}</dt>
      <dd className="mt-1 text-sm text-gray-900">{value ? value : '—'}</dd>
    </div>
  )
}

function ProfileView({ onSessionInvalid }: { onSessionInvalid: () => void }) {
  const [data, setData] = useState<ProfileResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [notLinked, setNotLinked] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    const fetchProfile = async () => {
      setLoading(true)
      setError(null)
      setNotLinked(false)
      try {
        const res = await axios.get<ProfileResponse>(`${EP_API_BASE}/profile`, {
          withCredentials: true,
          signal: controller.signal,
        })
        if (!controller.signal.aborted) {
          setData(res.data ?? null)
        }
      } catch (err) {
        if (controller.signal.aborted) return
        if (isUnauthorised(err)) {
          onSessionInvalid()
          return
        }
        const { code } = errorEnvelope(err)
        const status = axios.isAxiosError(err) ? err.response?.status : undefined
        if (status === 409 || code === 'not_linked') {
          setNotLinked(true)
        } else {
          setError('We could not load your profile. Please try again.')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    fetchProfile()
    return () => controller.abort()
  }, [reloadKey, onSessionInvalid])

  const retry = useCallback(() => setReloadKey((k) => k + 1), [])

  if (loading) {
    return (
      <div className="space-y-3" role="status" aria-label="Loading profile">
        <SkeletonBlock className="h-6 w-40" />
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="py-3">
              <SkeletonBlock className="h-3 w-24" />
              <SkeletonBlock className="mt-2 h-4 w-56" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (notLinked) {
    return (
      <EmptyState
        title="Account not yet linked"
        message="Your account is not yet linked to a staff record. Please contact your organisation administrator."
      />
    )
  }

  if (error) {
    return (
      <ErrorState
        title="Could not load profile"
        message={error}
        onRetry={retry}
      />
    )
  }

  if (!data) {
    return (
      <EmptyState
        title="No profile details"
        message="There are no profile details to show yet."
      />
    )
  }

  const displayName =
    data.name ??
    [data.first_name, data.last_name].filter(Boolean).join(' ').trim() ??
    'Your profile'

  return (
    <div className="space-y-6">
      <section
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        aria-label="Personal details"
      >
        <h2 className="text-sm font-semibold text-gray-900">Personal details</h2>
        <dl className="mt-2 divide-y divide-gray-100">
          <ProfileField label="Name" value={displayName || '—'} />
          <ProfileField label="Email" value={data.email} />
          <ProfileField label="Phone" value={data.phone} />
          <ProfileField label="Emergency contact" value={data.emergency_contact_name} />
          <ProfileField label="Emergency phone" value={data.emergency_contact_phone} />
        </dl>
      </section>

      <section
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        aria-label="Employment details"
      >
        <h2 className="text-sm font-semibold text-gray-900">Employment</h2>
        <dl className="mt-2 divide-y divide-gray-100">
          <ProfileField label="Position" value={data.position} />
          <ProfileField label="Employee ID" value={data.employee_id} />
          <ProfileField label="Employment basis" value={data.employment_basis} />
          <ProfileField label="Employment type" value={data.employment_type} />
          <ProfileField label="Working arrangement" value={data.working_arrangement} />
          <ProfileField
            label="Start date"
            value={data.employment_start_date ? formatDate(data.employment_start_date) : null}
          />
        </dl>
      </section>

      <section
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        aria-label="Payroll details"
      >
        <h2 className="text-sm font-semibold text-gray-900">Payroll</h2>
        <p className="mt-1 text-xs text-gray-400">
          Sensitive details are masked for your security.
        </p>
        <dl className="mt-2 divide-y divide-gray-100">
          <ProfileField label="Tax code" value={data.tax_code} />
          <ProfileField
            label="KiwiSaver"
            value={
              data.kiwisaver_enrolled === null || data.kiwisaver_enrolled === undefined
                ? null
                : data.kiwisaver_enrolled
                  ? 'Enrolled'
                  : 'Not enrolled'
            }
          />
          <ProfileField label="IRD number" value={data.ird_number} />
          <ProfileField label="Bank account" value={data.bank_account_number} />
        </dl>
      </section>
    </div>
  )
}

/* ── Roster view (R7.1, R7.2, R7.4) ── */

function RosterView({ onSessionInvalid }: { onSessionInvalid: () => void }) {
  const [weekStart, setWeekStart] = useState<string>(() => isoWeekStart(new Date()))
  const [data, setData] = useState<RosterResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [notLinked, setNotLinked] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    const fetchRoster = async () => {
      setLoading(true)
      setError(null)
      setNotLinked(false)
      try {
        const res = await axios.get<RosterResponse>(`${EP_API_BASE}/roster`, {
          withCredentials: true,
          params: { week_start: weekStart },
          signal: controller.signal,
        })
        if (!controller.signal.aborted) {
          setData(res.data ?? null)
        }
      } catch (err) {
        if (controller.signal.aborted) return
        if (isUnauthorised(err)) {
          onSessionInvalid()
          return
        }
        const { code } = errorEnvelope(err)
        const status = axios.isAxiosError(err) ? err.response?.status : undefined
        if (status === 409 || code === 'not_linked') {
          setNotLinked(true)
        } else {
          setError('We could not load your roster. Please try again.')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    fetchRoster()
    return () => controller.abort()
  }, [weekStart, reloadKey, onSessionInvalid])

  const retry = useCallback(() => setReloadKey((k) => k + 1), [])

  const entries = data?.entries ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setWeekStart((w) => shiftWeek(w, -1))}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          ← Previous
        </button>
        <p className="text-sm font-medium text-gray-700">
          {data ? formatWeekRange(data.week_start, data.week_end) : 'This week'}
        </p>
        <button
          type="button"
          onClick={() => setWeekStart((w) => shiftWeek(w, 1))}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Next →
        </button>
      </div>

      {loading ? (
        <div className="space-y-2" role="status" aria-label="Loading roster">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-gray-200 bg-white p-4">
              <SkeletonBlock className="h-4 w-32" />
              <SkeletonBlock className="mt-2 h-3 w-48" />
            </div>
          ))}
        </div>
      ) : notLinked ? (
        <EmptyState
          title="Account not yet linked"
          message="Your account is not yet linked to a staff record. Please contact your organisation administrator."
        />
      ) : error ? (
        <ErrorState title="Could not load roster" message={error} onRetry={retry} />
      ) : entries.length === 0 ? (
        <EmptyState
          title="No shifts this week"
          message="You have no shifts scheduled for this week. Try another week using the controls above."
        />
      ) : (
        <ul className="divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white shadow-sm">
          {entries.map((entry, idx) => (
            <li key={idx} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900">
                    {entry?.title ?? 'Shift'}
                  </p>
                  <p className="mt-0.5 text-sm text-gray-600">
                    {formatDateTime(entry?.start_time ?? null)}
                    {entry?.end_time ? ` – ${formatTime(entry.end_time)}` : ''}
                  </p>
                  {entry?.notes ? (
                    <p className="mt-1 text-xs text-gray-500">{entry.notes}</p>
                  ) : null}
                </div>
                {entry?.entry_type ? (
                  <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
                    {entry.entry_type}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ── Top-level authenticated shell ── */

export default function EmployeePortalApp() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  // R8.7 — authenticated portal pages must never be indexed.
  usePageMeta({ noindex: true, title: 'Employee Portal' })

  const [me, setMe] = useState<MeResponse | null>(null)
  const [authState, setAuthState] = useState<'checking' | 'ready' | 'error'>(
    'checking',
  )
  const [view, setView] = useState<PortalView>('profile')
  const [reloadKey, setReloadKey] = useState(0)
  const [loggingOut, setLoggingOut] = useState(false)

  const goToLogin = useCallback(() => {
    navigate(`/e/${slug ?? ''}`, { replace: true })
  }, [navigate, slug])

  // Verify the session on mount via /e/api/auth/me; 401 → branded login (R6.10).
  useEffect(() => {
    const controller = new AbortController()

    const checkSession = async () => {
      setAuthState('checking')
      try {
        const res = await axios.get<MeResponse>(`${EP_API_BASE}/auth/me`, {
          withCredentials: true,
          signal: controller.signal,
        })
        if (!controller.signal.aborted) {
          setMe(res.data ?? null)
          setAuthState('ready')
        }
      } catch (err) {
        if (controller.signal.aborted) return
        if (isUnauthorised(err)) {
          goToLogin()
          return
        }
        setAuthState('error')
      }
    }

    checkSession()
    return () => controller.abort()
  }, [reloadKey, goToLogin])

  const handleLogout = useCallback(async () => {
    setLoggingOut(true)
    try {
      // CSRF double-submit (R6.7, R6.8): echo the readable cookie as the header.
      const csrf = readCookie(CSRF_COOKIE_NAME)
      await axios.post(
        `${EP_API_BASE}/auth/logout`,
        {},
        {
          withCredentials: true,
          headers: csrf ? { 'X-CSRF-Token': csrf } : undefined,
        },
      )
    } catch {
      // Logout is best-effort; the cookies are cleared server-side on success and
      // the session expires regardless. Always return to the branded login.
    } finally {
      goToLogin()
    }
  }, [goToLogin])

  /* ── Session check states (never blank) ── */

  if (authState === 'checking') {
    return (
      <div
        className="flex min-h-screen items-center justify-center bg-gray-50 px-4"
        role="status"
        aria-label="Loading portal"
      >
        <div className="w-full max-w-md space-y-3">
          <SkeletonBlock className="mx-auto h-8 w-48" />
          <SkeletonBlock className="h-32 w-full" />
        </div>
      </div>
    )
  }

  if (authState === 'error') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-md">
          <ErrorState
            title="Something went wrong"
            message="We could not load your portal. Please try again."
            onRetry={() => setReloadKey((k) => k + 1)}
          />
        </div>
      </div>
    )
  }

  const orgName = me?.org_name ?? 'Employee Portal'
  const logoUrl = me?.branding?.logo_url ?? null
  const greetingName = me?.first_name ?? null

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            {logoUrl ? (
              <img
                src={logoUrl}
                alt={`${orgName} logo`}
                className="h-8 w-auto max-w-[120px] object-contain"
              />
            ) : null}
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-gray-900">{orgName}</p>
              {greetingName ? (
                <p className="truncate text-xs text-gray-500">
                  Signed in as {greetingName}
                </p>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            disabled={loggingOut}
            className="shrink-0 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {loggingOut ? 'Signing out…' : 'Log out'}
          </button>
        </div>
      </header>

      <nav className="border-b border-gray-200 bg-white" aria-label="Portal sections">
        <div className="mx-auto flex max-w-3xl gap-1 px-4">
          {(['profile', 'roster'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setView(tab)}
              aria-current={view === tab ? 'page' : undefined}
              className={`-mb-px border-b-2 px-4 py-3 text-sm font-medium capitalize transition-colors ${
                view === tab
                  ? 'border-gray-900 text-gray-900'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </nav>

      <main className="mx-auto max-w-3xl px-4 py-6">
        {view === 'profile' ? (
          <ProfileView onSessionInvalid={goToLogin} />
        ) : (
          <RosterView onSessionInvalid={goToLogin} />
        )}
      </main>
    </div>
  )
}
