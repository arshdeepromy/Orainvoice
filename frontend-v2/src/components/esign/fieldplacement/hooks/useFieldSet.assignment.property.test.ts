import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import {
  fieldSetReducer,
  FIELD_TYPES,
  type FieldSetState,
  type FieldSetAction,
  type FieldType,
} from './useFieldSet'
import type { NormalizedRect, PageDims } from '../lib/coordinateMapping'

// Feature: esignature-field-placement, Property 5: Every field references exactly one valid recipient
// **Validates: Requirements 4.1, 4.3**
//
// The Field_Placement_Editor associates every placed field with exactly one
// recipient from the Send_Flow's recipient list (R4.1), and changing the
// recipient assigned to a field updates only that field's recipient (R4.3).
//
// This drives the PURE `fieldSetReducer` over generated action sequences against
// a FIXED recipient list and asserts two things hold after every action:
//   (a) every field's `recipientKey` is exactly one key drawn from the fixed
//       recipient list — never dangling, never multivalued (R4.1); and
//   (b) an `assign` action changes only the target field's `recipientKey` and
//       leaves every other field (and every other property of the target)
//       untouched (R4.3).
//
// The recipient list is held fixed for the whole sequence (no `removeRecipient`
// / `reset`), matching the property's "fixed recipient list" framing, and both
// `add` and `assign` only ever reference keys that exist in that list.

/* ------------------------------------------------------------------ */
/*  Fixed dims + rect generators (geometry is incidental to Prop 5).   */
/* ------------------------------------------------------------------ */

// A single, strictly-positive page dimension reused for every geometric action.
// Clamping behaviour is exercised by Property 3; here geometry is irrelevant to
// the recipient-assignment invariant, so a fixed page keeps the model simple.
const DIMS: PageDims = { cssWidth: 800, cssHeight: 1000 }

// A fractional rect comfortably inside [0,100] so `add` never has its recipient
// affected by clamping (clamping only touches geometry, never recipientKey).
const rectArb: fc.Arbitrary<NormalizedRect> = fc.record({
  positionX: fc.double({ min: 0, max: 50, noNaN: true }),
  positionY: fc.double({ min: 0, max: 50, noNaN: true }),
  width: fc.double({ min: 5, max: 40, noNaN: true }),
  height: fc.double({ min: 5, max: 40, noNaN: true }),
})

const fieldTypeArb: fc.Arbitrary<FieldType> = fc.constantFrom(...FIELD_TYPES)

/* ------------------------------------------------------------------ */
/*  Command model — interpreted against the current state.             */
/* ------------------------------------------------------------------ */

// Commands are resolved against the live state into concrete reducer actions so
// that `assign` / `move` / `resize` / `delete` always reference a field that
// actually exists. `ridx` / `fieldIdx` are reduced modulo the relevant length.
type Command =
  | { t: 'add'; type: FieldType; page: number; rect: NormalizedRect; ridx: number }
  | { t: 'assign'; fieldIdx: number; ridx: number }
  | { t: 'move'; fieldIdx: number; rect: NormalizedRect }
  | { t: 'resize'; fieldIdx: number; rect: NormalizedRect }
  | { t: 'setRequired'; fieldIdx: number; required: boolean }
  | { t: 'delete'; fieldIdx: number }

const commandArb: fc.Arbitrary<Command> = fc.oneof(
  fc.record({
    t: fc.constant('add' as const),
    type: fieldTypeArb,
    page: fc.integer({ min: 1, max: 5 }),
    rect: rectArb,
    ridx: fc.nat(),
  }),
  fc.record({ t: fc.constant('assign' as const), fieldIdx: fc.nat(), ridx: fc.nat() }),
  fc.record({ t: fc.constant('move' as const), fieldIdx: fc.nat(), rect: rectArb }),
  fc.record({ t: fc.constant('resize' as const), fieldIdx: fc.nat(), rect: rectArb }),
  fc.record({ t: fc.constant('setRequired' as const), fieldIdx: fc.nat(), required: fc.boolean() }),
  fc.record({ t: fc.constant('delete' as const), fieldIdx: fc.nat() }),
)

/* ------------------------------------------------------------------ */
/*  Property 5: every field references exactly one valid recipient.    */
/* ------------------------------------------------------------------ */

describe('Property 5: Every field references exactly one valid recipient', () => {
  it('keeps every field assigned to one existing recipient, and re-assigning changes only that field', () => {
    fc.assert(
      fc.property(
        // A fixed recipient list: a non-empty set of distinct recipient keys.
        fc.uniqueArray(fc.integer({ min: 0, max: 999 }), { minLength: 1, maxLength: 8 }),
        fc.array(commandArb, { maxLength: 60 }),
        (recipientKeys, commands) => {
          const validKeys = new Set(recipientKeys)
          let state: FieldSetState = []
          let addCounter = 0

          for (const cmd of commands) {
            // Resolve the command into a concrete action against current state.
            let action: FieldSetAction | null = null

            if (cmd.t === 'add') {
              action = {
                kind: 'add',
                clientId: `f${addCounter++}`,
                type: cmd.type,
                page: cmd.page,
                rect: cmd.rect,
                recipientKey: recipientKeys[cmd.ridx % recipientKeys.length],
                dims: DIMS,
              }
            } else if (state.length > 0) {
              const target = state[cmd.fieldIdx % state.length]
              switch (cmd.t) {
                case 'assign':
                  action = {
                    kind: 'assign',
                    clientId: target.clientId,
                    recipientKey: recipientKeys[cmd.ridx % recipientKeys.length],
                  }
                  break
                case 'move':
                  action = { kind: 'move', clientId: target.clientId, rect: cmd.rect, dims: DIMS }
                  break
                case 'resize':
                  action = { kind: 'resize', clientId: target.clientId, rect: cmd.rect, dims: DIMS }
                  break
                case 'setRequired':
                  action = {
                    kind: 'setRequired',
                    clientId: target.clientId,
                    required: cmd.required,
                  }
                  break
                case 'delete':
                  action = { kind: 'delete', clientId: target.clientId }
                  break
              }
            }

            if (action === null) continue

            const prev = state
            const next = fieldSetReducer(prev, action)

            // (a) After every action, every field references exactly one key
            //     from the fixed recipient list — never dangling (R4.1).
            for (const f of next) {
              expect(validKeys.has(f.recipientKey)).toBe(true)
            }

            // (b) An `assign` changes ONLY the target field's recipientKey,
            //     leaving every other field unchanged and every other property
            //     of the target unchanged (R4.3).
            if (action.kind === 'assign') {
              const targetId = action.clientId
              expect(next.length).toBe(prev.length)
              for (let i = 0; i < next.length; i++) {
                const before = prev[i]
                const after = next[i]
                expect(after.clientId).toBe(before.clientId)
                if (after.clientId === targetId) {
                  // Only the recipientKey may differ on the target field.
                  expect(after.recipientKey).toBe(action.recipientKey)
                  expect({ ...after, recipientKey: 0 }).toEqual({
                    ...before,
                    recipientKey: 0,
                  })
                } else {
                  // Every other field is byte-for-byte unchanged.
                  expect(after).toEqual(before)
                }
              }
            }

            state = next
          }
        },
      ),
      { numRuns: 200 },
    )
  })
})
