/**
 * useRosterGridData — central data fetch for the Roster Grid Editor
 * (Workstream B / task B4).
 *
 * Fetches three things in parallel inside a single `useEffect` with
 * one shared `AbortController`:
 *
 *   1. Active staff: `GET /api/v2/staff?is_active=true&page_size=200`
 *      Response shape: `{ staff: StaffMemberResponse[], total, page,
 *      page_size, compliance_summary }`. Read as `res.data?.staff ?? []`.
 *      Note: `/api/v2/staff` does NOT accept a `branch_id` query
 *      param at the time of writing this spec — branch filtering is
 *      applied client-side in the consumer (CODE-GAP-9).
 *
 *   2. Schedule entries: `GET /api/v2/schedule?start=...&end=...` via
 *      the typed `listEntries` from `@/api/schedule`.
 *
 *   3. Approved leave overlapping the window:
 *      `GET /api/v2/leave/approvals?status=approved&start_lte=...&end_gte=...&limit=500`
 *      (uses the `start_lte` / `end_gte` query params added by task A7).
 *      Response shape `{ items: [...], total }`. We expand each
 *      leave_request into a per-(staff_id, YYYY-MM-DD) overlay map for
 *      O(1) cell lookup during rendering.
 *
 * Validates: R2.7, R3.7, R16.1, R16.4.
 */

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/api/client'
import { listEntries } from '@/api/schedule'
import type { ScheduleEntryResponse } from '@/types/schedule'

/* ------------------------------------------------------------------ */
/*  Local types                                                        */
/* ------------------------------------------------------------------ */

/**
 * Subset of `StaffMemberResponse` (see `app/modules/staff/schemas.py`)
 * needed by the grid. Kept narrow on purpose so the typing pressure
 * doesn't bleed into adjacent components — the grid only renders name,
 * position, and intersects `location_assignments` for branch filtering.
 */
export interface StaffMember {
  id: string
  first_name: string
  last_name: string | null
  /** Service-resolved display name. */
  name: string
  position: string | null
  is_active: boolean
  /**
   * Working arrangement (`rostered` | `fixed` | `casual` | ...). When
   * `fixed`, the staff member's recurring hours are defined by
   * `availability_schedule` and the roster grid renders them read-only —
   * they can only be changed by editing the staff member's working
   * arrangement under Staff.
   */
  working_arrangement?: string
  location_assignments?: Array<{
    id: string
    staff_id: string
    location_id: string
    assigned_at: string
  }>
  /** JSONB shape: `{ "monday": { "start": "09:00", "end": "17:00" }, ... }`. */
  availability_schedule?: Record<string, { start: string; end: string }>
}

/**
 * Per-cell overlay data for an approved leave_request that covers
 * a given (staff_id, date) pair.
 */
export interface LeaveOverlay {
  leave_type_label: string
  leave_type_code: string
}

/**
 * Wire shape returned by `GET /api/v2/staff` — only the keys we need.
 */
interface StaffListWireResponse {
  staff?: StaffMember[]
  total?: number
}

/**
 * Wire shape returned by `GET /api/v2/leave/approvals` — only the
 * keys we need from each item.
 */
interface LeaveApprovalsItem {
  staff_id?: string
  start_date?: string // YYYY-MM-DD
  end_date?: string // YYYY-MM-DD
  leave_type_code?: string | null
  leave_type_name?: string | null
}

interface LeaveApprovalsWireResponse {
  items?: LeaveApprovalsItem[]
  total?: number
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Format a Date as YYYY-MM-DD using local time. */
function toIsoDate(date: Date): string {
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/** Parse a YYYY-MM-DD string into a local-midnight Date. */
function parseIsoDate(s: string): Date {
  const [y, m, d] = s.split('-').map((p) => parseInt(p, 10))
  return new Date(y, (m ?? 1) - 1, d ?? 1)
}

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

export interface UseRosterGridDataResult {
  staff: StaffMember[]
  entries: ScheduleEntryResponse[]
  leaveByStaffDate: Map<string, Map<string, LeaveOverlay>>
  isLoading: boolean
  error: string | null
  refetch: () => void
  /** Mutate the entries cache without a refetch (used by B6 / B9). */
  setEntries: React.Dispatch<React.SetStateAction<ScheduleEntryResponse[]>>
}

export function useRosterGridData(visibleWindow: {
  start: Date
  end: Date
}): UseRosterGridDataResult {
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [entries, setEntries] = useState<ScheduleEntryResponse[]>([])
  const [leaveByStaffDate, setLeaveByStaffDate] = useState<
    Map<string, Map<string, LeaveOverlay>>
  >(new Map())
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refetchCounter, setRefetchCounter] = useState(0)

  const startIso = visibleWindow.start.toISOString()
  // `visibleWindow.end` is the START (local midnight) of the LAST visible day.
  // Fetch through the END of that day (next local midnight) so shifts that
  // fall on the final day — including ones stored on the previous UTC date for
  // +12/+13h timezones like NZ — are included. Without this, the last column
  // renders empty even though entries exist, and a "phantom" overlap appears
  // when adding a shift there.
  const fetchEnd = new Date(visibleWindow.end)
  fetchEnd.setDate(fetchEnd.getDate() + 1)
  const endIso = fetchEnd.toISOString()
  const startDate = toIsoDate(visibleWindow.start)
  const endDate = toIsoDate(visibleWindow.end)

  useEffect(() => {
    const controller = new AbortController()

    const load = async () => {
      setIsLoading(true)
      try {
        const [staffRes, entriesRes, leaveRes] = await Promise.all([
          apiClient.get<StaffListWireResponse>('/staff', {
            baseURL: '/api/v2',
            params: { is_active: true, page_size: 200 },
            signal: controller.signal,
          }),
          listEntries({
            start: startIso,
            end: endIso,
            signal: controller.signal,
          }),
          apiClient.get<LeaveApprovalsWireResponse>('/leave/approvals', {
            baseURL: '/api/v2',
            params: {
              status: 'approved',
              start_lte: endDate,
              end_gte: startDate,
              limit: 500,
            },
            signal: controller.signal,
          }),
        ])

        setStaff(staffRes.data?.staff ?? [])
        setEntries(entriesRes.entries ?? [])

        // Build the leave overlay map: for each leave_request, expand
        // its [start_date, end_date] inclusive range into per-day
        // entries keyed by staff_id then YYYY-MM-DD.
        const map = new Map<string, Map<string, LeaveOverlay>>()
        for (const lr of leaveRes.data?.items ?? []) {
          const staffId = lr.staff_id
          const startStr = lr.start_date
          const endStr = lr.end_date
          if (!staffId || !startStr || !endStr) continue

          if (!map.has(staffId)) map.set(staffId, new Map())
          const overlay: LeaveOverlay = {
            leave_type_label: lr.leave_type_name ?? 'Leave',
            leave_type_code: lr.leave_type_code ?? '',
          }
          const startD = parseIsoDate(startStr)
          const endD = parseIsoDate(endStr)
          for (
            const d = new Date(startD);
            d <= endD;
            d.setDate(d.getDate() + 1)
          ) {
            const key = toIsoDate(d)
            map.get(staffId)!.set(key, overlay)
          }
        }
        setLeaveByStaffDate(map)
        setError(null)
      } catch (err: unknown) {
        // Silently swallow aborted requests — the new fetch will fill
        // state. Anything else surfaces as a user-visible error.
        const e = err as
          | { code?: string; name?: string; message?: string }
          | undefined
        const isAbort =
          controller.signal.aborted ||
          e?.code === 'ERR_CANCELED' ||
          e?.name === 'CanceledError' ||
          e?.name === 'AbortError'
        if (isAbort) return
        setError('Failed to load roster')
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }

    load()
    return () => controller.abort()
  }, [startIso, endIso, startDate, endDate, refetchCounter])

  const refetch = useCallback(() => {
    setRefetchCounter((n) => n + 1)
  }, [])

  return {
    staff,
    entries,
    leaveByStaffDate,
    isLoading,
    error,
    refetch,
    setEntries,
  }
}
