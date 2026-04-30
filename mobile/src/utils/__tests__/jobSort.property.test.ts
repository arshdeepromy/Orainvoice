// Feature: mobile-konsta-redesign, Property 4: Job card sorting invariant
// **Validates: Requirements 25.1, 56.3**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { sortJobCards, STATUS_ORDER } from '@/utils/jobSort'

/**
 * Property 4: Job card sorting invariant.
 *
 * For any list of job cards (each with a status in {open, in_progress,
 * completed, invoiced} and a created_at ISO timestamp), sorting with the
 * sortJobCards function SHALL produce a list where:
 * (a) all `in_progress` jobs appear before all `open` jobs,
 * (b) all `open` jobs appear before all `completed` and `invoiced` jobs, and
 * (c) within each status group, jobs are ordered by `created_at` descending
 *     (most recent first).
 */
describe('Property 4: Job card sorting invariant', () => {
  const statusArb = fc.constantFrom('open', 'in_progress', 'completed', 'invoiced')

  // Generate ISO timestamps within a reasonable range using integer milliseconds
  const timestampArb = fc
    .integer({
      min: new Date('2020-01-01').getTime(),
      max: new Date('2030-12-31').getTime(),
    })
    .map((ms) => new Date(ms).toISOString())

  const jobCardArb = fc.record({
    id: fc.uuid(),
    status: statusArb,
    created_at: timestampArb,
  })

  const jobCardsArb = fc.array(jobCardArb, { minLength: 0, maxLength: 30 })

  it('in_progress jobs appear before open jobs', () => {
    fc.assert(
      fc.property(jobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)

        let lastInProgressIdx = -1
        let firstOpenIdx = sorted.length

        sorted.forEach((card, idx) => {
          if (card.status === 'in_progress') lastInProgressIdx = idx
          if (card.status === 'open' && idx < firstOpenIdx) firstOpenIdx = idx
        })

        // If both groups exist, in_progress should come before open
        if (lastInProgressIdx >= 0 && firstOpenIdx < sorted.length) {
          expect(lastInProgressIdx).toBeLessThan(firstOpenIdx)
        }
      }),
      { numRuns: 200 },
    )
  })

  it('open jobs appear before completed and invoiced jobs', () => {
    fc.assert(
      fc.property(jobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)

        let lastOpenIdx = -1
        let firstCompletedIdx = sorted.length

        sorted.forEach((card, idx) => {
          if (card.status === 'open') lastOpenIdx = idx
          if (
            (card.status === 'completed' || card.status === 'invoiced') &&
            idx < firstCompletedIdx
          ) {
            firstCompletedIdx = idx
          }
        })

        if (lastOpenIdx >= 0 && firstCompletedIdx < sorted.length) {
          expect(lastOpenIdx).toBeLessThan(firstCompletedIdx)
        }
      }),
      { numRuns: 200 },
    )
  })

  it('within each status group, jobs are ordered by created_at descending', () => {
    fc.assert(
      fc.property(jobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)

        // Group by status order
        const groups = new Map<number, typeof sorted>()
        for (const card of sorted) {
          const order = STATUS_ORDER[card.status] ?? 99
          if (!groups.has(order)) groups.set(order, [])
          groups.get(order)!.push(card)
        }

        // Within each group, created_at should be descending
        for (const [, group] of groups) {
          for (let i = 1; i < group.length; i++) {
            const prev = group[i - 1].created_at
            const curr = group[i].created_at
            expect(prev >= curr).toBe(true)
          }
        }
      }),
      { numRuns: 200 },
    )
  })

  it('preserves all elements (no items lost or duplicated)', () => {
    fc.assert(
      fc.property(jobCardsArb, (cards) => {
        const sorted = sortJobCards(cards)
        expect(sorted).toHaveLength(cards.length)

        // All original IDs should be present
        const originalIds = cards.map((c) => c.id).sort()
        const sortedIds = sorted.map((c) => c.id).sort()
        expect(sortedIds).toEqual(originalIds)
      }),
      { numRuns: 200 },
    )
  })

  it('empty array returns empty array', () => {
    expect(sortJobCards([])).toEqual([])
  })
})
