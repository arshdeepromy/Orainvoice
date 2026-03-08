import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { distributeTips } from '../utils/tippingCalcs'

// Feature: production-readiness-gaps, Property 30: Tip distribution allocation is correct
// **Validates: Requirements 15.3**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Positive tip amount in cents precision (0.01 – 10 000.00) */
const tipAmountArb = fc
  .integer({ min: 1, max: 1_000_000 })
  .map((cents) => cents / 100)

/** A single staff member with a positive share */
const staffMemberArb = fc.record({
  id: fc.uuid(),
  share: fc.integer({ min: 1, max: 1000 }),
})

/** Non-empty list of staff members with unique IDs */
const staffListArb = fc
  .array(staffMemberArb, { minLength: 1, maxLength: 20 })
  .map((list) => {
    const seen = new Set<string>()
    return list.filter((s) => {
      if (seen.has(s.id)) return false
      seen.add(s.id)
      return true
    })
  })
  .filter((list) => list.length > 0)

/** Staff list where all shares are equal */
const equalShareStaffArb = fc
  .tuple(
    fc.integer({ min: 1, max: 1000 }),
    fc.array(fc.uuid(), { minLength: 2, maxLength: 15 }),
  )
  .map(([share, ids]) => {
    const unique = [...new Set(ids)]
    return unique.map((id) => ({ id, share }))
  })
  .filter((list) => list.length >= 2)

/* ------------------------------------------------------------------ */
/*  Property 30: Tip distribution allocation is correct                */
/* ------------------------------------------------------------------ */

describe('Property 30: Tip distribution allocation is correct', () => {
  it('sum of all allocations equals totalTip (to the cent)', () => {
    fc.assert(
      fc.property(tipAmountArb, staffListArb, (totalTip, staff) => {
        const result = distributeTips(totalTip, staff)
        const sum = result.reduce((s, r) => s + r.amount, 0)
        expect(Math.round(sum * 100)).toBe(Math.round(totalTip * 100))
      }),
      { numRuns: 100 },
    )
  })

  it('each allocation is non-negative', () => {
    fc.assert(
      fc.property(tipAmountArb, staffListArb, (totalTip, staff) => {
        const result = distributeTips(totalTip, staff)
        for (const alloc of result) {
          expect(alloc.amount).toBeGreaterThanOrEqual(0)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('equal shares produce equal or near-equal amounts (differ by at most 1 cent)', () => {
    fc.assert(
      fc.property(tipAmountArb, equalShareStaffArb, (totalTip, staff) => {
        const result = distributeTips(totalTip, staff)
        const amounts = result.map((r) => r.amount)
        const minAmount = Math.min(...amounts)
        const maxAmount = Math.max(...amounts)
        // With largest-remainder rounding, equal shares differ by at most 1 cent
        expect(Math.round((maxAmount - minAmount) * 100)).toBeLessThanOrEqual(1)
      }),
      { numRuns: 100 },
    )
  })

  it('result preserves original staff order', () => {
    fc.assert(
      fc.property(tipAmountArb, staffListArb, (totalTip, staff) => {
        const result = distributeTips(totalTip, staff)
        expect(result).toHaveLength(staff.length)
        for (let i = 0; i < staff.length; i++) {
          expect(result[i].id).toBe(staff[i].id)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('empty staff or zero/negative tip returns empty array', () => {
    fc.assert(
      fc.property(tipAmountArb, (totalTip) => {
        expect(distributeTips(totalTip, [])).toEqual([])
        expect(distributeTips(0, [{ id: 'x', share: 1 }])).toEqual([])
        expect(distributeTips(-totalTip, [{ id: 'x', share: 1 }])).toEqual([])
      }),
      { numRuns: 100 },
    )
  })
})
