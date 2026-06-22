/**
 * Helpers for fixed-working-arrangement staff in the Roster Grid Editor.
 *
 * A staff member with `working_arrangement === 'fixed'` has their recurring
 * hours defined by `availability_schedule` (a per-weekday `{ start, end }`
 * map). The roster grid renders those hours **read-only**: they are
 * pre-populated from the staff record and cannot be edited from the grid.
 * To change them, an admin must edit the staff member under Staff and change
 * their Working arrangement away from "Fixed".
 */

import type { StaffMember } from '../hooks/useRosterGridData'

/** Monday-first weekday keys matching the `availability_schedule` JSONB. */
const DAY_KEYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
] as const

/** Map a JS `Date` (Sun=0) onto the Monday-first `availability_schedule` key. */
export function dayKeyForDate(date: Date): string {
  const jsDay = date.getDay()
  return DAY_KEYS[jsDay === 0 ? 6 : jsDay - 1]
}

/** True when the staff member's hours are fixed (locked on the roster grid). */
export function isFixedArrangement(staff: Pick<StaffMember, 'working_arrangement'>): boolean {
  return (staff.working_arrangement ?? '').toLowerCase() === 'fixed'
}

/**
 * The configured fixed shift for `staff` on `date`, or `null` when the
 * staff member is not fixed, has no availability schedule, or has no
 * configured hours for that weekday.
 */
export function fixedShiftForDate(
  staff: Pick<StaffMember, 'working_arrangement' | 'availability_schedule'>,
  date: Date,
): { start: string; end: string } | null {
  if (!isFixedArrangement(staff)) return null
  const sched = staff.availability_schedule
  if (!sched) return null
  const entry = sched[dayKeyForDate(date)]
  if (!entry || !entry.start || !entry.end) return null
  return { start: entry.start, end: entry.end }
}

/** Display name for a staff member (falls back to first/last). */
export function staffDisplayName(
  staff: Pick<StaffMember, 'name' | 'first_name' | 'last_name'>,
): string {
  return (
    staff.name ??
    `${staff.first_name ?? ''} ${staff.last_name ?? ''}`.trim() ??
    'This staff member'
  )
}

/**
 * The message shown when an admin tries to edit a fixed-hours staff
 * member's roster. Directs them to change the working arrangement under
 * Staff (the only place fixed hours can be changed).
 */
export function fixedHoursEditMessage(
  staff: Pick<StaffMember, 'name' | 'first_name' | 'last_name'>,
): string {
  const name = staffDisplayName(staff)
  return (
    `${name} has fixed hours, so their roster can't be edited here. ` +
    `To change it, go to Staff, open ${name}, click Edit, and change their ` +
    `Working arrangement to Rostered (or another option) instead of Fixed.`
  )
}
