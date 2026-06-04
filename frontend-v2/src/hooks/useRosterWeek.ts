/**
 * useRosterWeek — track the currently-active week for the per-staff
 * Roster tab toolbar (Phase 1, task E4).
 *
 * The embedded `ScheduleCalendar` self-manages its own week navigation,
 * but the toolbar's "Email roster" / "Send roster SMS" buttons need to
 * know which week to send. This hook holds that state independently;
 * it deliberately does NOT fetch any roster data — that's the
 * calendar's job.
 *
 * The week always starts on Monday (NZ convention; matches
 * `ScheduleCalendar.startOfWeek`).
 *
 * Usage:
 *   const { weekStart, weekStartIso, goPrevWeek, goNextWeek, goThisWeek } =
 *     useRosterWeek()
 */

import { useCallback, useMemo, useState } from 'react'

export interface UseRosterWeekResult {
  /** First day of the active week (Monday) at 00:00 local time. */
  weekStart: Date
  /** YYYY-MM-DD string for the weekStart date — what the API expects. */
  weekStartIso: string
  /** Move the active week back by 7 days. */
  goPrevWeek: () => void
  /** Move the active week forward by 7 days. */
  goNextWeek: () => void
  /** Snap back to the Monday of the current calendar week. */
  goThisWeek: () => void
}

/** Return the Monday-aligned start of the week containing `date`. */
function mondayOf(date: Date): Date {
  const d = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const day = d.getDay() // 0 = Sunday, 1 = Monday, ... 6 = Saturday
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  return d
}

/** Format a Date as YYYY-MM-DD using local time (avoids UTC shift bugs). */
function toIsoDate(date: Date): string {
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

export default function useRosterWeek(): UseRosterWeekResult {
  const [weekStart, setWeekStart] = useState<Date>(() => mondayOf(new Date()))

  const weekStartIso = useMemo(() => toIsoDate(weekStart), [weekStart])

  const goPrevWeek = useCallback(() => {
    setWeekStart((prev) => {
      const d = new Date(prev)
      d.setDate(d.getDate() - 7)
      return d
    })
  }, [])

  const goNextWeek = useCallback(() => {
    setWeekStart((prev) => {
      const d = new Date(prev)
      d.setDate(d.getDate() + 7)
      return d
    })
  }, [])

  const goThisWeek = useCallback(() => {
    setWeekStart(mondayOf(new Date()))
  }, [])

  return { weekStart, weekStartIso, goPrevWeek, goNextWeek, goThisWeek }
}
