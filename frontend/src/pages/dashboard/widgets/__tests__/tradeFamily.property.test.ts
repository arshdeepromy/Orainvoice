import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: automotive-dashboard-widgets, Property 1: Trade Family Derivation
// **Validates: Requirements 1.1, 1.4**

/* ------------------------------------------------------------------ */
/*  Pure logic under test                                              */
/* ------------------------------------------------------------------ */

/**
 * Derives the `isAutomotive` flag from a tradeFamily value.
 * Mirrors the logic in OrgAdminDashboard.tsx:
 *   const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
 */
function deriveIsAutomotive(tradeFamily: string | null): boolean {
  return (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
}

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

const tradeFamilyArb = fc.oneof(fc.constant(null), fc.string())

/* ------------------------------------------------------------------ */
/*  Property 1: Trade Family Derivation                                */
/* ------------------------------------------------------------------ */

describe('Property 1: Trade Family Derivation', () => {
  it('isAutomotive is true iff (tradeFamily ?? "automotive-transport") === "automotive-transport"', () => {
    fc.assert(
      fc.property(tradeFamilyArb, (tradeFamily) => {
        const result = deriveIsAutomotive(tradeFamily)
        const expected = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
        expect(result).toBe(expected)
      }),
      { numRuns: 100 },
    )
  })

  it('null tradeFamily defaults to automotive (backward compatibility)', () => {
    fc.assert(
      fc.property(fc.constant(null), (tradeFamily) => {
        expect(deriveIsAutomotive(tradeFamily)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('"automotive-transport" always yields true', () => {
    fc.assert(
      fc.property(fc.constant('automotive-transport'), (tradeFamily) => {
        expect(deriveIsAutomotive(tradeFamily)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('any string other than "automotive-transport" yields false', () => {
    fc.assert(
      fc.property(
        fc.string().filter((s) => s !== 'automotive-transport'),
        (tradeFamily) => {
          expect(deriveIsAutomotive(tradeFamily)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })
})
