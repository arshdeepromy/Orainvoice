import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import {
  fieldSetReducer,
  defaultRequiredFor,
  MIN_FIELD_WIDTH_PX,
  MIN_FIELD_HEIGHT_PX,
  FIELD_TYPES,
  type FieldSetState,
  type FieldSetAction,
  type FieldType,
} from './useFieldSet'
import type { NormalizedRect, PageDims } from '../lib/coordinateMapping'

// Feature: esignature-field-placement, Property 3: Every geometric action leaves a field in-bounds and at least minimum size
// **Validates: Requirements 3.2, 3.3, 3.5, 3.6**
//
// The pure `fieldSetReducer` runs every geometric action (`add`/`move`/`resize`)
// through `clampToPage` + min-size in overlay space and stores the result back
// in normalized percent (origin top-left). The guarantee under test: after ANY
// sequence of geometric actions, every committed field stays within its page
// (`x≥0, y≥0, x+w≤100, y+h≤100`) and at least the minimum displayable size
// (`w≥minWidth, h≥minHeight`, R3.5/R3.6), while a move/resize changes only the
// field's geometry — its page, type, and recipient are unchanged (R3.2/R3.3).
//
// Bounds are checked in normalized percent (0–100). The minimum size in percent
// is page-dependent: `minWidth% = MIN_FIELD_WIDTH_PX / cssWidth * 100` and
// `minHeight% = MIN_FIELD_HEIGHT_PX / cssHeight * 100`. Page dimensions are
// generated comfortably larger than the minimum field size so the min-size
// floor is never capped by a tiny page (the documented degenerate case where
// `clampToPage` caps width/height to the page size).

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

// Strictly-positive page dimensions, drawn well above the minimum field size so
// the min-size floor always fits. Width and height are independent so pages may
// be non-square and differ from one another (R7.5).
const dimArb: fc.Arbitrary<PageDims> = fc.record({
  cssWidth: fc.double({ min: 320, max: 3000, noNaN: true, noDefaultInfinity: true }),
  cssHeight: fc.double({ min: 320, max: 4000, noNaN: true, noDefaultInfinity: true }),
})

// 1–3 pages, each with its own dims, modelling a (possibly multi-page) document.
const pagesArb: fc.Arbitrary<PageDims[]> = fc.array(dimArb, { minLength: 1, maxLength: 3 })

// A normalized rect whose components may fall well outside [0, 100] so the
// clamping path is genuinely exercised on add/move/resize.
const rectArb: fc.Arbitrary<NormalizedRect> = fc.record({
  positionX: fc.double({ min: -50, max: 150, noNaN: true, noDefaultInfinity: true }),
  positionY: fc.double({ min: -50, max: 150, noNaN: true, noDefaultInfinity: true }),
  width: fc.double({ min: -50, max: 150, noNaN: true, noDefaultInfinity: true }),
  height: fc.double({ min: -50, max: 150, noNaN: true, noDefaultInfinity: true }),
})

const fieldTypeArb: fc.Arbitrary<FieldType> = fc.constantFrom(...FIELD_TYPES)

// An abstract operation. `pageSeed`/`targetSeed` are resolved against the live
// page list / field set during the fold so they always reference valid items.
type Op =
  | { tag: 'add'; pageSeed: number; rect: NormalizedRect; recipientKey: number; type: FieldType }
  | { tag: 'move'; targetSeed: number; rect: NormalizedRect }
  | { tag: 'resize'; targetSeed: number; rect: NormalizedRect }

const opArb: fc.Arbitrary<Op> = fc.oneof(
  fc.record({
    tag: fc.constant<'add'>('add'),
    pageSeed: fc.nat(),
    rect: rectArb,
    recipientKey: fc.integer({ min: 0, max: 5 }),
    type: fieldTypeArb,
  }),
  fc.record({ tag: fc.constant<'move'>('move'), targetSeed: fc.nat(), rect: rectArb }),
  fc.record({ tag: fc.constant<'resize'>('resize'), targetSeed: fc.nat(), rect: rectArb }),
)

const EPS = 1e-6

/* ------------------------------------------------------------------ */
/*  Property 3: geometric invariant over action sequences              */
/* ------------------------------------------------------------------ */

describe('Property 3: Every geometric action leaves a field in-bounds and at least minimum size', () => {
  it('keeps every committed field in-bounds and ≥ min-size, with page/type/recipient unchanged', () => {
    fc.assert(
      fc.property(pagesArb, fc.array(opArb, { maxLength: 40 }), (pages, ops) => {
        let state: FieldSetState = []
        // The page (1-based) each field was added on — geometry must stay clamped
        // to this page's dims, and page/type/recipient must never change after add.
        const fieldPage = new Map<string, number>()
        // Original page/type/recipient at add time, to verify move/resize leave them.
        const origin = new Map<string, { page: number; type: FieldType; recipientKey: number }>()

        let counter = 0
        for (const op of ops) {
          if (op.tag === 'add') {
            const page = (op.pageSeed % pages.length) + 1
            const dims = pages[page - 1]
            const clientId = `f${counter++}`
            const action: FieldSetAction = {
              kind: 'add',
              clientId,
              type: op.type,
              page,
              rect: op.rect,
              recipientKey: op.recipientKey,
              dims,
            }
            state = fieldSetReducer(state, action)
            fieldPage.set(clientId, page)
            origin.set(clientId, { page, type: op.type, recipientKey: op.recipientKey })
          } else {
            if (state.length === 0) continue
            const target = state[op.targetSeed % state.length]
            const dims = pages[target.page - 1]
            const action: FieldSetAction = {
              kind: op.tag,
              clientId: target.clientId,
              rect: op.rect,
              dims,
            }
            state = fieldSetReducer(state, action)
          }
        }

        // After any sequence of geometric actions, every committed field obeys
        // the bounds + min-size invariant against its own page's dimensions, and
        // carries the page/type/recipient it was given at add time.
        for (const f of state) {
          const page = fieldPage.get(f.clientId)!
          const dims = pages[page - 1]
          const minWidthPct = (MIN_FIELD_WIDTH_PX / dims.cssWidth) * 100
          const minHeightPct = (MIN_FIELD_HEIGHT_PX / dims.cssHeight) * 100
          const { positionX, positionY, width, height } = f.rect

          // In-bounds (R3.5).
          expect(positionX).toBeGreaterThanOrEqual(-EPS)
          expect(positionY).toBeGreaterThanOrEqual(-EPS)
          expect(positionX + width).toBeLessThanOrEqual(100 + EPS)
          expect(positionY + height).toBeLessThanOrEqual(100 + EPS)

          // At least minimum displayable size (R3.6).
          expect(width).toBeGreaterThanOrEqual(minWidthPct - EPS)
          expect(height).toBeGreaterThanOrEqual(minHeightPct - EPS)

          // Move/resize change only geometry: page/type/recipient are unchanged
          // from add (R3.2, R3.3).
          const o = origin.get(f.clientId)!
          expect(f.page).toBe(o.page)
          expect(f.type).toBe(o.type)
          expect(f.recipientKey).toBe(o.recipientKey)
          // The add default required flag is independent of geometric actions.
          expect(f.required).toBe(defaultRequiredFor(o.type))
        }
      }),
      { numRuns: 200 },
    )
  })
})
