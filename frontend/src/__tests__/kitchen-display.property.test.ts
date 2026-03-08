import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  getUrgencyLevel,
  getBackoffDelay,
  filterByStation,
  type KitchenOrderItem,
} from '../pages/kitchen/KitchenDisplay'

// Feature: production-readiness-gaps, Property 1: Kitchen order urgency level is deterministic
// Feature: production-readiness-gaps, Property 2: Station filtering returns only matching orders
// Feature: production-readiness-gaps, Property 3: WebSocket reconnection follows exponential backoff
// **Validates: Requirements 1.4, 1.6, 1.7**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const stationArb = fc.constantFrom('main', 'grill', 'fry', 'cold', 'bar', 'dessert')

const kitchenOrderArb = (station?: string): fc.Arbitrary<KitchenOrderItem> =>
  fc.record({
    id: fc.uuid(),
    org_id: fc.uuid(),
    pos_transaction_id: fc.option(fc.uuid(), { nil: null }),
    table_id: fc.option(fc.uuid(), { nil: null }),
    item_name: fc.string({ minLength: 1, maxLength: 50 }),
    quantity: fc.integer({ min: 1, max: 100 }),
    modifications: fc.option(fc.string({ minLength: 1, maxLength: 100 }), { nil: null }),
    station: station ? fc.constant(station) : stationArb,
    status: fc.constantFrom('pending', 'preparing', 'ready'),
    created_at: fc
      .integer({ min: new Date('2024-01-01').getTime(), max: new Date('2026-01-01').getTime() })
      .map((ts) => new Date(ts).toISOString()),
    prepared_at: fc.option(
      fc
        .integer({ min: new Date('2024-01-01').getTime(), max: new Date('2026-01-01').getTime() })
        .map((ts) => new Date(ts).toISOString()),
      { nil: null },
    ),
  })

/* ------------------------------------------------------------------ */
/*  Property 1: Kitchen order urgency level is deterministic           */
/* ------------------------------------------------------------------ */

describe('Property 1: Kitchen order urgency level is deterministic', () => {
  it('returns "normal" when elapsed < threshold', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 120 }), // threshold in minutes
        (threshold) => {
          // Create a timestamp that is (threshold - 1) minutes ago
          const minutesAgo = threshold - 1
          const createdAt = new Date(Date.now() - minutesAgo * 60_000).toISOString()
          expect(getUrgencyLevel(createdAt, threshold)).toBe('normal')
        },
      ),
      { numRuns: 100 },
    )
  })

  it('returns "warning" when threshold <= elapsed < 2 * threshold', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2, max: 120 }), // threshold in minutes (min 2 to allow fractional midpoint)
        (threshold) => {
          // Create a timestamp that is exactly threshold + half-threshold minutes ago (midpoint of warning range)
          const minutesAgo = threshold + Math.floor(threshold / 2)
          const createdAt = new Date(Date.now() - minutesAgo * 60_000).toISOString()
          expect(getUrgencyLevel(createdAt, threshold)).toBe('warning')
        },
      ),
      { numRuns: 100 },
    )
  })

  it('returns "critical" when elapsed >= 2 * threshold', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 60 }), // threshold in minutes
        fc.integer({ min: 0, max: 60 }), // extra minutes beyond 2*threshold
        (threshold, extra) => {
          const minutesAgo = 2 * threshold + extra
          const createdAt = new Date(Date.now() - minutesAgo * 60_000).toISOString()
          expect(getUrgencyLevel(createdAt, threshold)).toBe('critical')
        },
      ),
      { numRuns: 100 },
    )
  })

  it('urgency level is one of normal, warning, or critical for any valid input', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: new Date('2020-01-01').getTime(), max: Date.now() }).map((ts) => new Date(ts)),
        fc.integer({ min: 1, max: 120 }),
        (createdDate, threshold) => {
          const result = getUrgencyLevel(createdDate.toISOString(), threshold)
          expect(['normal', 'warning', 'critical']).toContain(result)
        },
      ),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 2: Station filtering returns only matching orders         */
/* ------------------------------------------------------------------ */

describe('Property 2: Station filtering returns only matching orders', () => {
  it('filtering by a station returns only orders for that station', () => {
    fc.assert(
      fc.property(
        fc.array(kitchenOrderArb(), { minLength: 0, maxLength: 30 }),
        stationArb,
        (orders, station) => {
          const filtered = filterByStation(orders, station)
          // Every returned order must have the selected station
          for (const order of filtered) {
            expect(order.station).toBe(station)
          }
          // Count must match the number of orders with that station
          const expected = orders.filter((o) => o.station === station)
          expect(filtered.length).toBe(expected.length)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('filtering by "all" returns all orders', () => {
    fc.assert(
      fc.property(
        fc.array(kitchenOrderArb(), { minLength: 0, maxLength: 30 }),
        (orders) => {
          const filtered = filterByStation(orders, 'all')
          expect(filtered.length).toBe(orders.length)
          // Same references
          for (let i = 0; i < orders.length; i++) {
            expect(filtered[i]).toBe(orders[i])
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('filtering preserves order identity (no duplicates, no missing)', () => {
    fc.assert(
      fc.property(
        fc.array(kitchenOrderArb(), { minLength: 0, maxLength: 30 }),
        stationArb,
        (orders, station) => {
          const filtered = filterByStation(orders, station)
          const filteredIds = new Set(filtered.map((o) => o.id))
          // No duplicates
          expect(filteredIds.size).toBe(filtered.length)
          // Every matching order is included
          for (const order of orders) {
            if (order.station === station) {
              expect(filteredIds.has(order.id)).toBe(true)
            }
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 3: WebSocket reconnection follows exponential backoff     */
/* ------------------------------------------------------------------ */

describe('Property 3: WebSocket reconnection follows exponential backoff', () => {
  it('delay equals min(2^N * 1000, 30000) for any attempt N', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 100 }),
        (attempt) => {
          const delay = getBackoffDelay(attempt)
          const expected = Math.min(Math.pow(2, attempt) * 1000, 30000)
          expect(delay).toBe(expected)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('delay is always between 1000 and 30000 inclusive', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 100 }),
        (attempt) => {
          const delay = getBackoffDelay(attempt)
          expect(delay).toBeGreaterThanOrEqual(1000)
          expect(delay).toBeLessThanOrEqual(30000)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('delay is non-decreasing as attempt increases', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 99 }),
        (attempt) => {
          const delay1 = getBackoffDelay(attempt)
          const delay2 = getBackoffDelay(attempt + 1)
          expect(delay2).toBeGreaterThanOrEqual(delay1)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('produces the exact expected sequence for attempts 0-6', () => {
    const expectedSequence = [1000, 2000, 4000, 8000, 16000, 30000, 30000]
    for (let i = 0; i < expectedSequence.length; i++) {
      expect(getBackoffDelay(i)).toBe(expectedSequence[i])
    }
  })
})
