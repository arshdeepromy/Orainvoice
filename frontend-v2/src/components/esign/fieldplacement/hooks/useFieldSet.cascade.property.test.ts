import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import {
  fieldSetReducer,
  FIELD_TYPES,
  type FieldType,
  type PlacedField,
  type FieldSetState,
} from './useFieldSet'
import type { NormalizedRect } from '../lib/coordinateMapping'

// Feature: esignature-field-placement, Property 6: Removing a recipient removes exactly that recipient's fields
// **Validates: Requirements 4.5**
//
// When a Recipient is removed in the Send_Flow, the editor cascade-deletes
// every Field assigned to that Recipient from the Field_Set (R4.5). The pure
// `removeRecipient` reducer action is the mechanism. The guarantee under test
// is two-sided:
//   (a) after `removeRecipient(k)`, no surviving field is assigned to `k`; and
//   (b) every field NOT assigned to `k` survives unchanged — same field
//       objects, in the same relative order (no field is dropped, mutated, or
//       reordered as a side effect).
//
// We generate a Field_Set drawn from a small pool of recipient keys (so the
// removed key frequently matches some fields, exercising real deletion as well
// as the no-op case where it matches none), then dispatch `removeRecipient`
// for an arbitrary key and assert both halves of the property.

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

// A normalized rect (percent 0–100, origin top-left). Geometry is irrelevant to
// cascade-delete, but we generate realistic in-bounds values so fields look
// like genuine placed fields rather than degenerate ones.
const normalizedRectArb: fc.Arbitrary<NormalizedRect> = fc.record({
  positionX: fc.double({ min: 0, max: 90, noNaN: true, noDefaultInfinity: true }),
  positionY: fc.double({ min: 0, max: 90, noNaN: true, noDefaultInfinity: true }),
  width: fc.double({ min: 1, max: 10, noNaN: true, noDefaultInfinity: true }),
  height: fc.double({ min: 1, max: 10, noNaN: true, noDefaultInfinity: true }),
})

const fieldTypeArb: fc.Arbitrary<FieldType> = fc.constantFrom(...FIELD_TYPES)

// Recipient keys are drawn from a small pool so that an arbitrary key to remove
// has a good chance of matching several fields (genuine cascade) while also
// covering the no-match case (removing a key no field references).
const RECIPIENT_KEY_POOL = [0, 1, 2, 3] as const
const recipientKeyArb: fc.Arbitrary<number> = fc.constantFrom(...RECIPIENT_KEY_POOL)

// One placed field. clientId is unique per field (see fieldSetArb) so we can
// assert object-identity preservation of survivors.
function placedFieldArb(clientId: string): fc.Arbitrary<PlacedField> {
  return fc.record({
    clientId: fc.constant(clientId),
    type: fieldTypeArb,
    page: fc.integer({ min: 1, max: 5 }),
    rect: normalizedRectArb,
    recipientKey: recipientKeyArb,
    required: fc.boolean(),
  })
}

// A Field_Set with unique clientIds (the real invariant — every placed field
// carries a stable, unique client id), of arbitrary length including empty.
const fieldSetArb: fc.Arbitrary<FieldSetState> = fc
  .integer({ min: 0, max: 12 })
  .chain((n) =>
    fc.tuple(...Array.from({ length: n }, (_, i) => placedFieldArb(`f_${i}`))),
  )
  .map((fields) => fields as FieldSetState)

/* ------------------------------------------------------------------ */
/*  Property 6: cascade delete removes exactly the recipient's fields  */
/* ------------------------------------------------------------------ */

describe("Property 6: Removing a recipient removes exactly that recipient's fields", () => {
  it('drops every field assigned to the removed recipient and leaves all other fields unchanged', () => {
    fc.assert(
      fc.property(fieldSetArb, recipientKeyArb, (fields, removedKey) => {
        const result = fieldSetReducer(fields, {
          kind: 'removeRecipient',
          recipientKey: removedKey,
        })

        // (a) No surviving field is assigned to the removed recipient.
        expect(result.every((f) => f.recipientKey !== removedKey)).toBe(true)

        // (b) Every field NOT assigned to the removed recipient survives,
        // unchanged and in the same relative order. We compare against the
        // input filtered to the survivors and assert object identity (===),
        // proving no survivor was mutated, dropped, or reordered.
        const expectedSurvivors = fields.filter((f) => f.recipientKey !== removedKey)
        expect(result.length).toBe(expectedSurvivors.length)
        result.forEach((f, i) => {
          expect(f).toBe(expectedSurvivors[i])
        })

        // Sanity: the count removed equals the count of matching fields, so the
        // partition is exact (no over- or under-deletion).
        const removedCount = fields.filter((f) => f.recipientKey === removedKey).length
        expect(fields.length - result.length).toBe(removedCount)
      }),
      { numRuns: 200 },
    )
  })
})
