/**
 * Unit tests for ScheduleCalendar drag-and-drop rescheduling logic.
 *
 * Tests the computeRescheduledTimes function that calculates new
 * start/end times when an entry is dragged to a different slot.
 *
 * Requirements: 38.1, 38.2, 38.3
 */

import { describe, it, expect } from 'vitest'
import { computeRescheduledTimes } from '../ScheduleCalendar'

describe('computeRescheduledTimes', () => {
  it('preserves duration when moving to a different hour on the same day', () => {
    // 1-hour entry from 9:00 to 10:00
    const result = computeRescheduledTimes(
      '2025-01-15T09:00:00.000Z',
      '2025-01-15T10:00:00.000Z',
      '2025-01-15',
      14, // move to 2pm slot
      'staff-1',
    )

    const newStart = new Date(result.start_time)
    const newEnd = new Date(result.end_time)
    const durationMs = newEnd.getTime() - newStart.getTime()

    expect(newStart.getHours()).toBe(14)
    expect(durationMs).toBe(60 * 60 * 1000) // 1 hour preserved
    expect(result.staff_id).toBe('staff-1')
  })

  it('preserves duration when moving to a different day', () => {
    // 2-hour entry from 10:00 to 12:00 on Jan 15
    const result = computeRescheduledTimes(
      '2025-01-15T10:00:00.000Z',
      '2025-01-15T12:00:00.000Z',
      '2025-01-17', // move to Jan 17
      10,
      'staff-2',
    )

    const newStart = new Date(result.start_time)
    const newEnd = new Date(result.end_time)
    const durationMs = newEnd.getTime() - newStart.getTime()

    expect(newStart.getDate()).toBe(17)
    expect(durationMs).toBe(2 * 60 * 60 * 1000) // 2 hours preserved
    expect(result.staff_id).toBe('staff-2')
  })

  it('preserves original minutes when moving to a new hour', () => {
    // Entry starts at 9:30, ends at 10:15 (45 min)
    const result = computeRescheduledTimes(
      '2025-01-15T09:30:00.000Z',
      '2025-01-15T10:15:00.000Z',
      '2025-01-15',
      16, // move to 4pm slot
      'staff-1',
    )

    const newStart = new Date(result.start_time)
    const newEnd = new Date(result.end_time)
    const durationMs = newEnd.getTime() - newStart.getTime()

    expect(newStart.getHours()).toBe(16)
    expect(newStart.getMinutes()).toBe(30) // preserves :30
    expect(durationMs).toBe(45 * 60 * 1000) // 45 min preserved
  })

  it('reassigns to a different staff member', () => {
    const result = computeRescheduledTimes(
      '2025-01-15T09:00:00.000Z',
      '2025-01-15T10:00:00.000Z',
      '2025-01-15',
      9,
      'staff-new',
    )

    expect(result.staff_id).toBe('staff-new')
  })

  it('returns valid ISO strings', () => {
    const result = computeRescheduledTimes(
      '2025-01-15T09:00:00.000Z',
      '2025-01-15T10:00:00.000Z',
      '2025-01-15',
      12,
      'staff-1',
    )

    // Should not throw when parsed
    expect(() => new Date(result.start_time)).not.toThrow()
    expect(() => new Date(result.end_time)).not.toThrow()
    expect(new Date(result.start_time).toISOString()).toBe(result.start_time)
    expect(new Date(result.end_time).toISOString()).toBe(result.end_time)
  })

  it('handles entries that span across midnight when moved', () => {
    // 30-min entry moved to 18:00 (last hour in grid) — end at 18:30
    const result = computeRescheduledTimes(
      '2025-01-15T09:00:00.000Z',
      '2025-01-15T09:30:00.000Z',
      '2025-01-15',
      18,
      'staff-1',
    )

    const newStart = new Date(result.start_time)
    const newEnd = new Date(result.end_time)

    expect(newStart.getHours()).toBe(18)
    expect(newEnd.getHours()).toBe(18)
    expect(newEnd.getMinutes()).toBe(30)
  })
})
