import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { filterActiveJobs, sortJobCards } from '../pages/jobs/JobsPage'
import type { JobCard } from '../pages/jobs/JobsPage'

// Feature: booking-to-job-workflow, Property 16: Active jobs filtering
// Feature: booking-to-job-workflow, Property 17: Jobs page sort order

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const ACTIVE_STATUSES = ['open', 'in_progress'] as const
const INACTIVE_STATUSES = ['completed', 'invoiced'] as const
const ALL_STATUSES = [...ACTIVE_STATUSES, ...INACTIVE_STATUSES] as const

const activeStatusArb = fc.constantFrom(...ACTIVE_STATUSES)
const inactiveStatusArb = fc.constantFrom(...INACTIVE_STATUSES)
const anyStatusArb = fc.constantFrom(...ALL_STATUSES)

/** Generate a JobCard with a given status arbitrary */
function jobCardArb(statusArb: fc.Arbitrary<string>): fc.Arbitrary<JobCard> {
  return fc.record({
    id: fc.uuid(),
    customer_name: fc.option(fc.string({ minLength: 1, maxLength: 30 }), { nil: null }),
    vehicle_rego: fc.option(fc.string({ minLength: 1, maxLength: 10 }), { nil: null }),
    status: statusArb,
    description: fc.option(fc.string({ minLength: 1, maxLength: 40 }), { nil: null }),
    assigned_to: fc.option(fc.uuid(), { nil: null }),
    assigned_to_name: fc.option(fc.string({ minLength: 1, maxLength: 20 }), { nil: null }),
    assigned_to_user_id: fc.option(fc.uuid(), { nil: null }),
    created_at: fc
      .integer({ min: new Date('2024-01-01').getTime(), max: new Date('2026-12-31').getTime() })
      .map((ts) => new Date(ts).toISOString()),
  })
}

/** Array of JobCards with any status */
const anyJobCardsArb = fc.array(jobCardArb(anyStatusArb), { minLength: 0, maxLength: 20 })

/** Array of active-only JobCards */
const activeJobCardsArb = fc.array(jobCardArb(activeStatusArb), { minLength: 0, maxLength: 20 })

/* ------------------------------------------------------------------ */
/*  Property 16: Active jobs filtering                                 */
/*  **Validates: Requirements 5.1, 5.4**                               */
/* ------------------------------------------------------------------ */

describe('Property 16: Active jobs filtering', () => {
  it('result contains only cards with status open or in_progress', () => {
    fc.assert(
      fc.property(anyJobCardsArb, (cards) => {
        const result = filterActiveJobs(cards)
        for (const card of result) {
          expect(['open', 'in_progress']).toContain(card.status)
        }
      }),
      { numRuns: 5 },
    )
  })

  it('no cards with status completed or invoiced are included', () => {
    fc.assert(
      fc.property(anyJobCardsArb, (cards) => {
        const result = filterActiveJobs(cards)
        for (const card of result) {
          expect(card.status).not.toBe('completed')
          expect(card.status).not.toBe('invoiced')
        }
      }),
      { numRuns: 5 },
    )
  })

  it('all active cards from input are preserved in the result', () => {
    fc.assert(
      fc.property(anyJobCardsArb, (cards) => {
        const result = filterActiveJobs(cards)
        const expectedIds = cards
          .filter((c) => c.status === 'open' || c.status === 'in_progress')
          .map((c) => c.id)
        const resultIds = result.map((c) => c.id)
        expect(resultIds).toEqual(expectedIds)
      }),
      { numRuns: 5 },
    )
  })

  it('filtering a list of only inactive cards returns empty', () => {
    fc.assert(
      fc.property(fc.array(jobCardArb(inactiveStatusArb), { minLength: 1, maxLength: 10 }), (cards) => {
        expect(filterActiveJobs(cards)).toHaveLength(0)
      }),
      { numRuns: 5 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 17: Jobs page sort order                                  */
/*  **Validates: Requirements 5.3**                                    */
/* ------------------------------------------------------------------ */

describe('Property 17: Jobs page sort order', () => {
  it('all in_progress cards appear before all open cards', () => {
    fc.assert(
      fc.property(activeJobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)
        const lastInProgress = sorted.reduce(
          (acc, c, i) => (c.status === 'in_progress' ? i : acc),
          -1,
        )
        const firstOpen = sorted.findIndex((c) => c.status === 'open')
        if (lastInProgress >= 0 && firstOpen >= 0) {
          expect(lastInProgress).toBeLessThan(firstOpen)
        }
      }),
      { numRuns: 5 },
    )
  })

  it('within in_progress group, cards are sorted by created_at descending', () => {
    fc.assert(
      fc.property(activeJobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)
        const inProgressCards = sorted.filter((c) => c.status === 'in_progress')
        for (let i = 1; i < inProgressCards.length; i++) {
          const prev = new Date(inProgressCards[i - 1].created_at).getTime()
          const curr = new Date(inProgressCards[i].created_at).getTime()
          expect(prev).toBeGreaterThanOrEqual(curr)
        }
      }),
      { numRuns: 5 },
    )
  })

  it('within open group, cards are sorted by created_at descending', () => {
    fc.assert(
      fc.property(activeJobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)
        const openCards = sorted.filter((c) => c.status === 'open')
        for (let i = 1; i < openCards.length; i++) {
          const prev = new Date(openCards[i - 1].created_at).getTime()
          const curr = new Date(openCards[i].created_at).getTime()
          expect(prev).toBeGreaterThanOrEqual(curr)
        }
      }),
      { numRuns: 5 },
    )
  })

  it('sort does not add or remove cards', () => {
    fc.assert(
      fc.property(activeJobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)
        expect(sorted).toHaveLength(cards.length)
        const sortedIds = sorted.map((c) => c.id).sort()
        const inputIds = [...cards].map((c) => c.id).sort()
        expect(sortedIds).toEqual(inputIds)
      }),
      { numRuns: 5 },
    )
  })
})
