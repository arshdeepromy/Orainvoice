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
 *
 * Logic copied verbatim; presentation remapped onto the design-system tokens.
 */

import { useState } from 'react'
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

const navBtnCls =
  'min-h-[44px] rounded-ctl border border-border px-3 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent'

const actionBtnCls =
  'min-h-[44px] rounded-ctl border border-border bg-card px-3 py-2 text-sm font-medium text-text hover:bg-canvas focus:outline-none focus:ring-2 focus:ring-accent disabled:cursor-not-allowed disabled:opacity-60'

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
            className={navBtnCls}
          >
            ←
          </button>
          <button
            type="button"
            onClick={goThisWeek}
            className={navBtnCls}
          >
            This week
          </button>
          <button
            type="button"
            onClick={goNextWeek}
            aria-label="Next week"
            className={navBtnCls}
          >
            →
          </button>
          <span
            className="ml-2 text-sm text-text"
            data-testid="week-label"
          >
            Week of <span className="mono">{weekLabel}</span>
          </span>
        </div>

        {/* Email + SMS actions */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={sendEmailRoster}
            disabled={sending !== null}
            className={actionBtnCls}
          >
            {sending === 'email' ? 'Sending email…' : 'Email roster'}
          </button>
          <button
            type="button"
            onClick={sendSmsRoster}
            disabled={sending !== null}
            className={actionBtnCls}
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
          className={`mb-4 rounded-ctl p-3 text-sm ${
            toast.kind === 'success'
              ? 'bg-ok-soft text-ok'
              : 'bg-danger-soft text-danger'
          }`}
        >
          {toast.text}
        </div>
      )}

      <div className="rounded-card border border-border">
        <ScheduleCalendar focusStaffId={staffId} />
      </div>
    </div>
  )
}
