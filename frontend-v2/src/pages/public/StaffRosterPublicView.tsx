/**
 * Public read-only staff roster viewer (Phase 1 task E9).
 *
 * Route: ``/public/staff-roster/:token`` (no auth).
 * API:   ``GET /api/v2/public/staff-roster/:token``
 *
 * The recipient (a staff member) clicks the tokenised link from their
 * roster SMS or email and lands here. We render a read-only week view
 * with their shifts and call out the failure modes per design §9 +
 * R9.4 / G4 / G5:
 *
 * - 200 → render the week view.
 * - 404 ``token_not_found``                  → "link not valid".
 * - 410 ``token_expired_staff_deactivated``  → "revoked, staff deactivated"
 *                                              (G4 — the deactivation
 *                                              flow expired the token).
 * - 410 ``token_expired``                    → "natural 30-day TTL".
 * - 429 (G5 rate limit)                      → "too many requests".
 *
 * The page deliberately exposes only what the backend returns —
 * staff display name, week range, schedule entries — and nothing
 * else. No PII is rendered beyond the staff's own display name (the
 * recipient already knows who they are).
 *
 * **Validates: Requirement R9.4** (Phase 1 task E9).
 */

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'

interface ScheduleEntry {
  start_time: string | null
  end_time: string | null
  title: string | null
  notes: string | null
  entry_type?: string | null
}

interface RosterPayload {
  staff_name: string
  week_start: string
  week_end: string
  entries: ScheduleEntry[]
}

type ErrorKind =
  | 'not_found'
  | 'expired_revoked'
  | 'expired'
  | 'rate_limited'
  | 'unknown'

interface ErrorState {
  kind: ErrorKind
  title: string
  message: string
}

function formatDateRange(weekStart: string, weekEnd: string): string {
  const fmt = (iso: string) => {
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
  return `${fmt(weekStart)} – ${fmt(weekEnd)}`
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

export default function StaffRosterPublicView() {
  const { token } = useParams<{ token: string }>()
  const [data, setData] = useState<RosterPayload | null>(null)
  const [error, setError] = useState<ErrorState | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()

    const fetchRoster = async () => {
      if (!token) {
        setError({
          kind: 'not_found',
          title: 'Roster unavailable',
          message: 'This roster link is not valid.',
        })
        setLoading(false)
        return
      }

      setLoading(true)
      setError(null)
      try {
        const res = await axios.get<RosterPayload>(
          `/api/v2/public/staff-roster/${token}`,
          { signal: controller.signal },
        )
        if (!controller.signal.aborted) {
          setData(res.data ?? null)
        }
      } catch (err) {
        if (controller.signal.aborted) return

        const status = axios.isAxiosError(err) ? err.response?.status : undefined
        const detail = axios.isAxiosError(err)
          ? (err.response?.data as { detail?: string } | undefined)?.detail
          : undefined

        if (status === 404) {
          setError({
            kind: 'not_found',
            title: 'Roster unavailable',
            message:
              'This roster link is not valid. Please contact your manager for an updated link.',
          })
        } else if (status === 410 && detail === 'token_expired_staff_deactivated') {
          setError({
            kind: 'expired_revoked',
            title: 'Roster link revoked',
            message:
              'This roster link is no longer valid because the staff member has been deactivated. Please contact your manager for an updated link.',
          })
        } else if (status === 410) {
          // Either ``token_expired`` (natural TTL) or any other 410 —
          // treat both as "ask for a fresh link".
          setError({
            kind: 'expired',
            title: 'Roster link expired',
            message:
              'This roster link has expired. Ask your manager to send a fresh one.',
          })
        } else if (status === 429) {
          setError({
            kind: 'rate_limited',
            title: 'Too many requests',
            message: 'Please wait a moment and refresh the page to try again.',
          })
        } else {
          setError({
            kind: 'unknown',
            title: 'Could not load roster',
            message:
              'Something went wrong loading this roster. Please try again later.',
          })
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    fetchRoster()
    return () => controller.abort()
  }, [token])

  /* ── Loading state ── */
  if (loading) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 px-4"
        style={{ minHeight: '100vh' }}
        role="status"
        aria-label="Loading roster"
      >
        <p className="text-sm text-gray-500">Loading roster…</p>
      </div>
    )
  }

  /* ── Error state ── */
  if (error) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 px-4 py-8"
        style={{ minHeight: '100vh' }}
      >
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm text-center">
          <h1 className="text-lg font-semibold text-gray-900">{error.title}</h1>
          <p className="mt-2 text-sm text-gray-600">{error.message}</p>
        </div>
      </div>
    )
  }

  if (!data) return null

  const entries = data?.entries ?? []
  const staffName = data?.staff_name ?? 'Staff member'

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
        <header className="mb-6">
          <p className="text-xs uppercase tracking-wide text-gray-500">
            Roster
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-gray-900">
            {staffName}
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Week of {formatDateRange(data?.week_start ?? '', data?.week_end ?? '')}
          </p>
        </header>

        <section
          className="rounded-lg border border-gray-200 bg-white shadow-sm"
          aria-label="Scheduled shifts"
        >
          {entries.length === 0 ? (
            <div className="p-6 text-center text-sm text-gray-500">
              No shifts scheduled for this week.
            </div>
          ) : (
            <ul className="divide-y divide-gray-200">
              {entries.map((entry, idx) => (
                <li key={idx} className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900">
                        {entry?.title ?? 'Shift'}
                      </p>
                      <p className="mt-0.5 text-sm text-gray-600">
                        {formatDateTime(entry?.start_time ?? null)}
                        {entry?.end_time
                          ? ` – ${formatTime(entry.end_time)}`
                          : ''}
                      </p>
                      {entry?.notes ? (
                        <p className="mt-1 text-xs text-gray-500">
                          {entry.notes}
                        </p>
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
        </section>

        <footer className="mt-6 text-center text-xs text-gray-400">
          Read-only view. Times are shown in your local timezone.
        </footer>
      </div>
    </div>
  )
}
