import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import {
  recipientColor,
  FIELD_COLOR_PALETTE_CAPACITY,
} from './fieldColors'

// Feature: esignature-field-placement, Property 7: Recipients receive pairwise-distinct colours
// **Validates: Requirements 4.4**
//
// Field placement colour-codes every placed field by its assigned recipient so
// the Org_Sender can tell at a glance which person each field belongs to (R4.4).
// The guarantee under test: within the palette capacity, each recipient's
// colour differs from every other recipient's — i.e. for any recipient list of
// size n ≤ FIELD_COLOR_PALETTE_CAPACITY, the mapping index -> colour is
// injective (pairwise distinct).
//
// We generate a recipient list as a set of distinct 0-based indices drawn from
// [0, FIELD_COLOR_PALETTE_CAPACITY) and assert that the `solid` colours assigned
// to those recipients are pairwise distinct. The `solid` value is the canonical
// identity of a palette entry (borders/handles/swatch), so distinct solids ⇒
// distinct FieldColors.

/* ------------------------------------------------------------------ */
/*  Arbitrary — a set of distinct recipient indices within capacity.   */
/* ------------------------------------------------------------------ */

// A non-empty set of distinct indices in [0, capacity). Using a Set guarantees
// the indices model a real recipient list (no recipient appears twice), and
// the cardinality is therefore ≤ FIELD_COLOR_PALETTE_CAPACITY.
const indicesWithinCapacityArb: fc.Arbitrary<number[]> = fc
  .uniqueArray(fc.integer({ min: 0, max: FIELD_COLOR_PALETTE_CAPACITY - 1 }), {
    minLength: 1,
    maxLength: FIELD_COLOR_PALETTE_CAPACITY,
  })

/* ------------------------------------------------------------------ */
/*  Property 7: pairwise-distinct colours within palette capacity.     */
/* ------------------------------------------------------------------ */

describe('Property 7: Recipients receive pairwise-distinct colours', () => {
  it('assigns each recipient a colour distinct from every other recipient within palette capacity', () => {
    fc.assert(
      fc.property(indicesWithinCapacityArb, (indices) => {
        const solids = indices.map((i) => recipientColor(i).solid)

        // Within capacity the index -> colour mapping is injective: as many
        // distinct solid colours as there are distinct recipients (R4.4).
        const distinctSolids = new Set(solids)
        expect(distinctSolids.size).toBe(indices.length)

        // Stated as an explicit pairwise check: no two distinct recipients
        // share a colour.
        for (let a = 0; a < indices.length; a++) {
          for (let b = a + 1; b < indices.length; b++) {
            expect(recipientColor(indices[a]).solid).not.toBe(
              recipientColor(indices[b]).solid,
            )
          }
        }
      }),
      { numRuns: 200 },
    )
  })
})
