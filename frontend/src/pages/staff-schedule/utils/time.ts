/**
 * Time parsing helpers shared by paint-mode + apply-template flows
 * (Workstream B / tasks B7, B8, B9, B10).
 *
 * Closes CODE-GAP-13 — `ShiftTemplateResponse.start_time` /
 * `end_time` are serialised as `HH:MM:SS` (e.g. "09:00:00"), not
 * "09:00". Helpers that consume template times must accept both forms.
 */

export interface ParsedTime {
  hours: number
  minutes: number
  seconds: number
}

/**
 * Parse an `HH:MM` or `HH:MM:SS` string into hour/minute/second
 * components. Returns null if the string is malformed or out of range.
 */
export function parseHHMM(input: string | null | undefined): ParsedTime | null {
  if (!input) return null
  const parts = input.split(':')
  if (parts.length !== 2 && parts.length !== 3) return null
  const h = parseInt(parts[0], 10)
  const m = parseInt(parts[1], 10)
  const s = parts.length === 3 ? parseInt(parts[2], 10) : 0
  if (!Number.isFinite(h) || !Number.isFinite(m) || !Number.isFinite(s))
    return null
  if (h < 0 || h > 23) return null
  if (m < 0 || m > 59) return null
  if (s < 0 || s > 59) return null
  return { hours: h, minutes: m, seconds: s }
}

/**
 * Combine a calendar date and an `HH:MM`/`HH:MM:SS` string into an
 * ISO-8601 UTC datetime string (`YYYY-MM-DDTHH:MM:SS.000Z` after
 * conversion through the local timezone — same semantics as
 * `new Date(year, month-1, day, hh, mm, ss).toISOString()`).
 *
 * Returns null if the time string is malformed.
 */
export function combineDateAndTime(
  date: Date,
  hhmm: string | null | undefined,
): string | null {
  const parsed = parseHHMM(hhmm)
  if (!parsed) return null
  const d = new Date(date)
  d.setHours(parsed.hours, parsed.minutes, parsed.seconds, 0)
  return d.toISOString()
}

/**
 * Format a date as `YYYY-MM-DD` in local time. Used as cell keys.
 */
export function toIsoDate(date: Date): string {
  const yyyy = date.getFullYear()
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/**
 * Format `Date` as a `<input type="datetime-local">` value
 * (`YYYY-MM-DDTHH:MM`) in local time.
 */
export function toDatetimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
