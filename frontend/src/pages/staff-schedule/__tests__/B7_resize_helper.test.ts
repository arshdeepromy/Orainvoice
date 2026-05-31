/**
 * Tests for `computeResizedEndTime` (B7).
 *
 * Property: for any pointer delta in [-1000, 1000] px and any
 * starting hour, `end_time = start_time + k×15min` for some positive
 * integer k, never crosses midnight of cell's date.
 *
 * Validates: R5.2, R5.6, R14.
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { computeResizedEndTime } from '../utils/resize'

describe('computeResizedEndTime', () => {
  it('property: result is always start + k * 15min for positive k', () => {
    fc.assert(
      fc.property(
        // Cap hour at 22 so we always have ≥ 15min of room before
        // midnight (the function clamps to EOD when there's no room).
        fc.integer({ min: 0, max: 22 }),
        fc.integer({ min: 0, max: 44 }),
        fc.integer({ min: -1000, max: 1000 }),
        fc.integer({ min: 30, max: 240 }),
        (h, m, dx, ppx) => {
          const start = new Date(2025, 5, 2, h, m, 0, 0)
          const end = computeResizedEndTime(start, dx, ppx)
          const deltaMs = end.getTime() - start.getTime()
          // Must be a positive multiple of 15 minutes.
          expect(deltaMs % (15 * 60 * 1000)).toBe(0)
          expect(deltaMs).toBeGreaterThanOrEqual(15 * 60 * 1000)
          // Must NOT cross midnight of the start date.
          const eod = new Date(start)
          eod.setHours(23, 59, 59, 999)
          expect(end.getTime()).toBeLessThanOrEqual(eod.getTime())
          // Must NOT exceed start + 24h.
          expect(deltaMs).toBeLessThanOrEqual(24 * 60 * 60 * 1000)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('clamps to start + 15 min for very negative deltas', () => {
    const start = new Date(2025, 5, 2, 10, 0, 0, 0)
    const end = computeResizedEndTime(start, -10000, 60)
    expect(end.getTime() - start.getTime()).toBe(15 * 60 * 1000)
  })

  it('clamps to end of day when start is late and delta is large', () => {
    const start = new Date(2025, 5, 2, 23, 0, 0, 0)
    const end = computeResizedEndTime(start, 100000, 60)
    expect(end.getHours()).toBe(23)
    expect(end.getMinutes()).toBe(45)
  })
})
