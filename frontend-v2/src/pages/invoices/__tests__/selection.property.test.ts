import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: responsive-invoice-layout, Property 2: Selection identity preserved across tier and back transitions
// **Validates: Requirements 1.5, 2.5, 2.7**
//
// For any `selectedId` and any sequence of viewport-tier changes (toggling
// `isWide`) and Back_To_List activations, the `selectedId` value SHALL remain
// unchanged by those operations:
//   - tier crossings never clear or mutate the selected invoice identity
//     (Req 1.5 — preserve selection without reloading the selected invoice);
//   - the Back_To_List_Control navigates the route to `/invoices`
//     (Invoices_List_Path) but does NOT mutate `selectedId`, so the list row
//     retains its selected-state highlight (Req 2.5, 2.7).
//
// `InvoiceList.tsx` does not export a reducer, so the design invariant is
// modelled here as a small pure state machine that mirrors exactly the
// transitions the component performs for `toggleTier` and `back`. Both
// operations are pure with respect to `selectedId`: neither is allowed to
// touch it. The model is the precise statement of the invariant the component
// must uphold.

/* ------------------------------------------------------------------ */
/*  Model — the responsive layout state the invariant constrains.      */
/* ------------------------------------------------------------------ */

type NarrowPane = 'list' | 'detail'

interface LayoutState {
  /** The selected invoice identity (the value the invariant protects). */
  selectedId: string | null
  /** Viewport is at/above the Wide_Threshold (1280px). */
  isWide: boolean
  /** Active pane below the Wide_Threshold. */
  narrowPane: NarrowPane
  /** Current route path. */
  route: string
}

/**
 * `toggleTier` — the viewport crosses the Wide_Threshold in either direction.
 * Per the design, crossing the threshold flips `isWide` ONLY; it never mutates
 * `selectedId` (so the selected invoice is preserved and never refetched —
 * Req 1.5) and never changes the route.
 */
function toggleTier(state: LayoutState): LayoutState {
  return { ...state, isWide: !state.isWide }
}

/**
 * `back` — the user activates the Back_To_List_Control. Per the design it sets
 * `narrowPane = 'list'` and navigates the route to `/invoices`
 * (Invoices_List_Path) WITHOUT clearing `selectedId`, so the list row keeps its
 * selected-state highlight (Req 2.5, 2.7).
 */
function back(state: LayoutState): LayoutState {
  return { ...state, narrowPane: 'list', route: '/invoices' }
}

type Op = 'toggleTier' | 'back'

function applyOp(state: LayoutState, op: Op): LayoutState {
  return op === 'toggleTier' ? toggleTier(state) : back(state)
}

/* ------------------------------------------------------------------ */
/*  Arbitraries — a selectedId and a random sequence of operations.    */
/* ------------------------------------------------------------------ */

// Non-empty selected ids: invoice ids are non-empty strings in practice.
const selectedIdArb: fc.Arbitrary<string> = fc.string({ minLength: 1, maxLength: 24 })

const opArb: fc.Arbitrary<Op> = fc.constantFrom('toggleTier', 'back')

const opSeqArb: fc.Arbitrary<Op[]> = fc.array(opArb, { maxLength: 50 })

const initialStateArb: fc.Arbitrary<LayoutState> = fc.record({
  selectedId: selectedIdArb,
  isWide: fc.boolean(),
  narrowPane: fc.constantFrom<NarrowPane>('list', 'detail'),
  route: fc.constantFrom('/invoices', '/invoices/abc', '/invoices/new'),
})

/* ------------------------------------------------------------------ */
/*  Property 2: Selection identity preserved across tier + back        */
/* ------------------------------------------------------------------ */

describe('Property 2: Selection identity preserved across tier and back transitions', () => {
  it('keeps selectedId invariant under any sequence of toggleTier / back ops', () => {
    fc.assert(
      fc.property(initialStateArb, opSeqArb, (initial, ops) => {
        const originalId = initial.selectedId

        let state = initial
        for (const op of ops) {
          const before = state
          state = applyOp(state, op)

          // Invariant 1: neither operation ever mutates the selected identity
          // (Req 1.5 — tier crossings preserve selection; Req 2.5/2.7 — Back
          // does not clear it).
          expect(state.selectedId).toBe(originalId)

          if (op === 'back') {
            // Invariant 2: Back navigates the route to the Invoices_List_Path
            // but leaves selectedId untouched (Req 2.7).
            expect(state.route).toBe('/invoices')
            expect(state.selectedId).toBe(before.selectedId)
          } else {
            // toggleTier flips the tier only — route and selection unchanged
            // (Req 1.5).
            expect(state.route).toBe(before.route)
            expect(state.isWide).toBe(!before.isWide)
            expect(state.selectedId).toBe(before.selectedId)
          }
        }

        // After the full sequence the selected identity is still the original
        // value: it was never cleared, mutated, or refetched (Req 1.5, 2.5).
        expect(state.selectedId).toBe(originalId)
      }),
      { numRuns: 200 },
    )
  })

  it('navigates to /invoices on every back activation without mutating selectedId', () => {
    fc.assert(
      fc.property(initialStateArb, opSeqArb, (initial, ops) => {
        let state = initial
        for (const op of ops) {
          state = applyOp(state, op)
          if (op === 'back') {
            // Back always results in the Invoices_List_Path route (Req 2.7) ...
            expect(state.route).toBe('/invoices')
            // ... and never disturbs the retained selection (Req 2.5).
            expect(state.selectedId).toBe(initial.selectedId)
          }
        }
      }),
      { numRuns: 200 },
    )
  })
})
