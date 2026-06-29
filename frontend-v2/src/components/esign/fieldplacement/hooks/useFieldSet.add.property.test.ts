import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import {
  fieldSetReducer,
  defaultRequiredFor,
  FIELD_TYPES,
  type FieldSetState,
  type FieldType,
  type PlacedField,
} from './useFieldSet'
import type { NormalizedRect, PageDims } from '../lib/coordinateMapping'

// Feature: esignature-field-placement, Property 4: Add records the chosen type, page, and per-type default required flag
// **Validates: Requirements 2.2, 2.3**
//
// When an Org_Sender adds a field of a chosen type to a page (R2.2), the pure
// `fieldSetReducer` `add` action grows the Field_Set by exactly one field that
// carries the chosen type and page. The per-type default required flag (R2.3)
// is applied: a `signature`, `initials`, `name`, `email`, or `date` field
// defaults to required, and a `text` field defaults to optional — i.e.
// `required === (type !== 'text')`. We test the pure reducer directly with no
// React render, over arbitrary prior states, field types, pages, recipients,
// rects, and page dimensions.

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

const fieldTypeArb: fc.Arbitrary<FieldType> = fc.constantFrom(...FIELD_TYPES)

// Strictly-positive page dimensions (the clamp precondition); width and height
// drawn independently so cases include non-square pages.
const dimsArb: fc.Arbitrary<PageDims> = fc.record({
  cssWidth: fc.double({ min: 1, max: 5000, noNaN: true, noDefaultInfinity: true }),
  cssHeight: fc.double({ min: 1, max: 5000, noNaN: true, noDefaultInfinity: true }),
})

// A normalized rect inside [0,100] in both axes (origin + size that fits).
const rectArb: fc.Arbitrary<NormalizedRect> = fc
  .record({
    fx: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
    fy: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
    fw: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
    fh: fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true }),
  })
  .map(({ fx, fy, fw, fh }) => ({
    positionX: fx * 100,
    positionY: fy * 100,
    width: fw * (1 - fx) * 100,
    height: fh * (1 - fy) * 100,
  }))

const pageArb: fc.Arbitrary<number> = fc.integer({ min: 1, max: 50 })
const recipientKeyArb: fc.Arbitrary<number> = fc.integer({ min: 0, max: 9 })

// An arbitrary prior Field_Set so the property holds regardless of existing
// state. Built by running a sequence of `add` actions through the reducer so
// the prior state is itself a valid Field_Set (no hand-rolled invalid fields).
const priorStateArb: fc.Arbitrary<FieldSetState> = fc
  .array(
    fc.record({
      type: fieldTypeArb,
      page: pageArb,
      rect: rectArb,
      recipientKey: recipientKeyArb,
      dims: dimsArb,
    }),
    { minLength: 0, maxLength: 6 },
  )
  .map((adds) =>
    adds.reduce<FieldSetState>(
      (state, a, i) =>
        fieldSetReducer(state, {
          kind: 'add',
          clientId: `prior_${i}`,
          type: a.type,
          page: a.page,
          rect: a.rect,
          recipientKey: a.recipientKey,
          dims: a.dims,
        }),
      [],
    ),
  )

/* ------------------------------------------------------------------ */
/*  Property 4: add records type, page, and per-type default required  */
/* ------------------------------------------------------------------ */

describe('Property 4: Add records the chosen type, page, and per-type default required flag', () => {
  it('grows the set by exactly one field carrying the chosen type/page, required iff type is not text', () => {
    fc.assert(
      fc.property(
        priorStateArb,
        fieldTypeArb,
        pageArb,
        rectArb,
        recipientKeyArb,
        dimsArb,
        (prior, type, page, rect, recipientKey, dims) => {
          const clientId = 'added_field'
          const next = fieldSetReducer(prior, {
            kind: 'add',
            clientId,
            type,
            page,
            rect,
            recipientKey,
            dims,
          })

          // Grows the set by exactly one (R2.2).
          expect(next.length).toBe(prior.length + 1)

          // The prior fields are preserved unchanged and in order; the new
          // field is appended at the end.
          expect(next.slice(0, prior.length)).toEqual(prior)

          const added = next[next.length - 1] as PlacedField

          // Carries the chosen type, page, and recipient (R2.2).
          expect(added.clientId).toBe(clientId)
          expect(added.type).toBe(type)
          expect(added.page).toBe(page)
          expect(added.recipientKey).toBe(recipientKey)

          // Per-type default required flag: required iff type is not `text`
          // (R2.3).
          expect(added.required).toBe(type !== 'text')
          expect(added.required).toBe(defaultRequiredFor(type))
        },
      ),
      { numRuns: 200 },
    )
  })
})
