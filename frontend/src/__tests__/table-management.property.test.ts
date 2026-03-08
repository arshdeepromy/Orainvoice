import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { getTableStatusColor } from '../utils/tableCalcs'

// Feature: production-readiness-gaps, Property 29: Table status colour coding is deterministic
// **Validates: Requirements 14.2**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Known statuses and their expected colours. */
const knownStatusMap: Record<string, string> = {
  Available: 'green',
  Occupied: 'amber',
  Reserved: 'blue',
  'Needs Cleaning': 'red',
}

/** Arbitrary that produces one of the four known statuses. */
const knownStatusArb = fc.constantFrom(...Object.keys(knownStatusMap))

/** Arbitrary that produces case/whitespace variants of known statuses. */
const caseVariantArb = knownStatusArb.chain((status) =>
  fc.constantFrom(
    status,
    status.toLowerCase(),
    status.toUpperCase(),
    status.replace(/ /g, '_'),
    status.toLowerCase().replace(/ /g, '_'),
    status.toUpperCase().replace(/ /g, '_'),
  ),
)

/** Arbitrary that produces strings that are NOT any known status (after normalisation). */
const unknownStatusArb = fc
  .string({ minLength: 1, maxLength: 30 })
  .filter((s) => {
    const normalised = s.toLowerCase().replace(/[\s_]+/g, '_')
    return !['available', 'occupied', 'reserved', 'needs_cleaning'].includes(normalised)
  })

/* ------------------------------------------------------------------ */
/*  Property 29: Table status colour coding is deterministic           */
/* ------------------------------------------------------------------ */

describe('Property 29: Table status colour coding is deterministic', () => {
  it('maps each known status to its defined colour', () => {
    fc.assert(
      fc.property(knownStatusArb, (status) => {
        const colour = getTableStatusColor(status)
        expect(colour).toBe(knownStatusMap[status])
      }),
      { numRuns: 100 },
    )
  })

  it('is case-insensitive and treats spaces/underscores equivalently', () => {
    fc.assert(
      fc.property(caseVariantArb, (variant) => {
        const colour = getTableStatusColor(variant)
        // Normalise to find the expected colour
        const normalised = variant.toLowerCase().replace(/[\s_]+/g, '_')
        const expected: Record<string, string> = {
          available: 'green',
          occupied: 'amber',
          reserved: 'blue',
          needs_cleaning: 'red',
        }
        expect(colour).toBe(expected[normalised])
      }),
      { numRuns: 100 },
    )
  })

  it('returns gray for any unrecognised status', () => {
    fc.assert(
      fc.property(unknownStatusArb, (status) => {
        expect(getTableStatusColor(status)).toBe('gray')
      }),
      { numRuns: 100 },
    )
  })

  it('calling twice with the same input always returns the same colour (pure function)', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 0, maxLength: 50 }), (status) => {
        const first = getTableStatusColor(status)
        const second = getTableStatusColor(status)
        expect(first).toBe(second)
      }),
      { numRuns: 100 },
    )
  })

  it('always returns one of the five valid colour tokens', () => {
    fc.assert(
      fc.property(fc.string({ minLength: 0, maxLength: 50 }), (status) => {
        const colour = getTableStatusColor(status)
        expect(['green', 'amber', 'blue', 'red', 'gray']).toContain(colour)
      }),
      { numRuns: 100 },
    )
  })
})
