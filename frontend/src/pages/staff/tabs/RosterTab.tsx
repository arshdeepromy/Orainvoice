/**
 * RosterTab — Staff Detail tabbed shell, task E4.
 *
 * Embeds the existing `ScheduleCalendar` filtered to a single staff via
 * the new `focusStaffId` prop (per design §6.3 + P1-N6/P1-N7). The
 * calendar continues to self-manage its own data fetching, week
 * navigation, and read/write state — this tab only contributes the
 * "Email roster" / "Send roster SMS" toolbar that needs its own week
 * state via `useRosterWeek` (P1-N7).
 *
 * "Add shift" / "Apply template" — the embedded `ScheduleCalendar`
 * already has its own "+ New Entry" button and a "Templates" panel,
 * so this tab does not duplicate them. Per the spec note on E4, the
 * toolbar items in this tab focus on the actions that aren't already
 * available inside the calendar (email + SMS).
 *
 * Refs: Staff Management Phase 1 — R7, R8, R9.
 */

import React, { useState } from 'react'
import apiClient from '@/api/client'
import ScheduleCalendar from '@/pages/schedule/ScheduleCalendar'
import useRosterWeek from '@/hooks/useRosterWeek'

interface RosterTabProps {
  staffId: string
}

interface RosterSendResponse {
  ok: boolean
  message_id?: string | null
  reason?: string | null
}

type Toast = { kind: 'success' | 'error'; text: string }

/**
 * Best-effort extraction of the `reason` string from a 422 response
 * body. The backend can return either:
 *   { detail: 'minimum_wage_below_threshold' }                 (string)
 *   { detail: { reason: 'no_email', threshold: 23.15 } }       (object)
 *   { detail: [{ msg: '...', loc: [...] }] }                   (FastAPI 422)
 */
function readErrorReason(err: unknown): string | null {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (!detail) return null
  if (typeof detail === 'string') return detail
  if (
    typeof detail === 'object' &&
    detail !== null &&
    'reason' in detail &&
    typeof (detail as { reason?: unknown }).reason === 'string'
  ) {
    return (detail as { reason: string }).reason
  }
  return null
}

export default function RosterTab({ staffId }: RosterTabProps) {
  const { weekStart, weekStartIso, goPrevWeek, goNextWeek, goThisWeek } =
    useRosterWeek()

  const [sending, setSending] = useState<'email' | 'sms' | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)

  const sendEmailRoster = async () => {
    setSending('email')
    setToast(null)
    try {
      const res = await apiClient.post<RosterSendResponse>(
        `/api/v2/staff/${staffId}/email-roster`,
        { week_start: weekStartIso },
      )
      const ok = res.data?.ok ?? false
      const reason = res.data?.reason ?? null
      if (ok) {
        setToast({ kind: 'success', text: 'Roster emailed successfully.' })
      } else {
        setToast({
          kind: 'error',
          text: reason
            ? `Could not email roster: ${reason}.`
            : 'Could not email roster.',
        })
      }
    } catch (err) {
      const reason = readErrorReason(err)
      setToast({
        kind: 'error',
        text: reason
          ? `Could not email roster: ${reason}.`
          : 'Failed to email roster. Please try again.',
      })
    } finally {
      setSending(null)
    }
  }

  const sendSmsRoster = async () => {
    setSending('sms')
    setToast(null)
    try {
      const res = await apiClient.post<RosterSendResponse>(
        `/api/v2/staff/${staffId}/sms-roster`,
        { week_start: weekStartIso },
      )
      const ok = res.data?.ok ?? false
      const reason = res.data?.reason ?? null
      if (ok) {
        setToast({ kind: 'success', text: 'Roster SMS sent.' })
      } else {
        setToast({
          kind: 'error',
          text: reason
            ? `Could not send roster SMS: ${reason}.`
            : 'Could not send roster SMS.',
        })
      }
    } catch (err) {
      const reason = readErrorReason(err)
      setToast({
        kind: 'error',
        text: reason
          ? `Could not send roster SMS: ${reason}.`
          : 'Failed to send roster SMS. Please try again.',
      })
    } finally {
      setSending(null)
    }
  }

  const weekLabel = weekStart.toLocaleDateString('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

  return (
    <div className="p-4 md:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {/* WeekNavigator */}
        <div
          className="flex flex-wrap items-center gap-2"
          role="group"
          aria-label="Roster week navigator"
        >
          <button
            type="button"
            onClick={goPrevWeek}
            aria-label="Previous week"
            className="min-h-[44px] rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            ←
          </button>
          <button
            type="button"
            onClick={goThisWeek}
            className="min-h-[44px] rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            This week
          </button>
          <button
            type="button"
            onClick={goNextWeek}
            aria-label="Next week"
            className="min-h-[44px] rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            →
          </button>
          <span
            className="ml-2 text-sm text-gray-700 dark:text-gray-300"
            data-testid="week-label"
          >
            Week of {weekLabel}
          </span>
        </div>

        {/* Email + SMS actions */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={sendEmailRoster}
            disabled={sending !== null}
            className="min-h-[44px] rounded border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            {sending === 'email' ? 'Sending email…' : 'Email roster'}
          </button>
          <button
            type="button"
            onClick={sendSmsRoster}
            disabled={sending !== null}
            className="min-h-[44px] rounded border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            {sending === 'sms' ? 'Sending SMS…' : 'Send roster SMS'}
          </button>
        </div>
      </div>

      {toast && (
        <div
          role={toast.kind === 'error' ? 'alert' : 'status'}
          aria-live="polite"
          data-testid={`toast-${toast.kind}`}
          className={`mb-4 rounded p-3 text-sm ${
            toast.kind === 'success'
              ? 'bg-green-50 text-green-800 dark:bg-green-900/30 dark:text-green-200'
              : 'bg-red-50 text-red-800 dark:bg-red-900/30 dark:text-red-200'
          }`}
        >
          {toast.text}
        </div>
      )}

      <div className="rounded border border-gray-200 dark:border-gray-700">
        <ScheduleCalendar focusStaffId={staffId} />
      </div>
    </div>
  )
}
