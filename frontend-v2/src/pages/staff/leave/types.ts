/**
 * Shared types for the Leave tab on the staff record page.
 *
 * The full `StaffMember` shape lives in `frontend/src/pages/staff/tabs/OverviewTab.tsx`
 * but the leave components only care about a handful of fields, so we
 * declare a narrowed interface here. Callers that already hold the full
 * record pass it through unchanged (TypeScript structural typing).
 *
 * **Validates: Staff Management Phase 2 tasks D1–D5**
 */

export interface Staff {
  id: string
  name?: string
  employment_type: string
  /** Decimal serialised as string. Nullable in the DB. */
  standard_hours_per_week: string | null
  /** Default daily shift start — used to seed partial_day_start_time. */
  shift_start: string | null
  shift_end: string | null
  /** JSONB keyed by 'monday'..'sunday'. */
  availability_schedule: Record<string, { start: string; end: string } | undefined>
}

/** Compute the staff's standard working day in hours. */
export function stdDailyHours(staff: Staff): number {
  const weekly = parseFloat(staff?.standard_hours_per_week ?? '') || 40
  // Most NZ employment is 5-day; fallback to 5 if not set.
  return weekly / 5
}

/** Count weekdays (Mon–Fri) inclusive between two ISO YYYY-MM-DD dates. */
export function countWeekdaysInRange(startIso: string, endIso: string): number {
  if (!startIso || !endIso) return 0
  const start = new Date(`${startIso}T00:00:00Z`)
  const end = new Date(`${endIso}T00:00:00Z`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 0
  if (end < start) return 0
  let count = 0
  const cursor = new Date(start)
  // Cap at a year to defend against runaway loops on invalid input.
  for (let i = 0; i < 366 && cursor <= end; i += 1) {
    const dow = cursor.getUTCDay() // 0 = Sun .. 6 = Sat
    if (dow !== 0 && dow !== 6) count += 1
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return count
}

/** Pick the staff's shift_start for a given ISO date, defaulting to '09:00'. */
export function defaultPartialDayStart(staff: Staff, isoDate: string): string {
  if (staff?.shift_start) return staff.shift_start
  if (!isoDate) return '09:00'
  const d = new Date(`${isoDate}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return '09:00'
  const dow = d.getUTCDay()
  const keys = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
  const day = staff?.availability_schedule?.[keys[dow]]
  return day?.start ?? '09:00'
}
