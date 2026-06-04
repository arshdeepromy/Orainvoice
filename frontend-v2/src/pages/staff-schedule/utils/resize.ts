/**
 * Pure helpers for the drag-resize handle on schedule entry blocks
 * (Workstream B / task B7).
 *
 * `computeResizedEndTime(start, pointerXDelta, pixelsPerHour)` snaps
 * the new end_time to the next 15-minute increment between
 * `start_time + 15 min` and `min(start_time + 24h, 23:59:59 of cell
 * date)`. Pure function — no DOM access, easy to property-test.
 *
 * Validates: R5.2, R5.6.
 */

/** Quarter-hour quantum in milliseconds. */
const QUARTER_HOUR_MS = 15 * 60 * 1000

/**
 * Return the end-of-day boundary (23:59:59.999) for the calendar day
 * the `date` falls on, in local time.
 */
function endOfDay(date: Date): Date {
  const out = new Date(date)
  out.setHours(23, 59, 59, 999)
  return out
}

/**
 * Compute the new end_time for a drag-resize gesture.
 *
 * @param start       Original entry start_time as a Date.
 * @param pointerXDelta Distance dragged in CSS pixels (signed; right
 *                    is positive, left is negative).
 * @param pixelsPerHour Conversion ratio in px / hour (e.g. 60 means
 *                    60px ≡ 1 hour).
 * @returns A new Date snapped to the nearest 15-minute increment that
 *          satisfies all of:
 *            - end > start (always at least start + 15min)
 *            - end <= start + 24h
 *            - end <= 23:59:59 of the same calendar date as `start`
 */
export function computeResizedEndTime(
  start: Date,
  pointerXDelta: number,
  pixelsPerHour: number,
): Date {
  if (pixelsPerHour <= 0) {
    throw new Error('pixelsPerHour must be > 0')
  }
  const startMs = start.getTime()
  // Convert px → ms.
  const deltaMs = (pointerXDelta / pixelsPerHour) * 60 * 60 * 1000

  // Snap the DELTA (offset from start) to a multiple of 15 min so the
  // resulting end is always start + k * 15min.
  const snappedDeltaMs = Math.round(deltaMs / QUARTER_HOUR_MS) * QUARTER_HOUR_MS

  // The minimum extension is +15min (R5.2).
  // The maximum extension is +24h (R5.2) AND must not cross midnight
  // of the start's calendar date (R5.6).
  const eodMs = endOfDay(start).getTime()
  // Largest multiple of 15min strictly within the day boundary.
  const maxByDayDeltaMs =
    Math.floor((eodMs - startMs) / QUARTER_HOUR_MS) * QUARTER_HOUR_MS
  const maxDeltaMs = Math.min(24 * 60 * 60 * 1000, maxByDayDeltaMs)

  const minDeltaMs = QUARTER_HOUR_MS
  const clampedDeltaMs = Math.max(
    minDeltaMs,
    Math.min(snappedDeltaMs, maxDeltaMs),
  )
  return new Date(startMs + clampedDeltaMs)
}
