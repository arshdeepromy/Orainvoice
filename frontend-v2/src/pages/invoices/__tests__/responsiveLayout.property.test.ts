import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: responsive-invoice-layout, Property 1: Pane-resolution truth table
// **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 6.3, 8.1, 8.2, 8.3**
//
// Exercises the pure `resolvePaneVisibility` helper across every combination of
// its four inputs (isWide, hasSelection, narrowPane, isCreating), asserting the
// full design truth table holds:
//   - wide                                  ⇒ showList && showDetail && !showBackControl
//   - not-wide                              ⇒ showList !== showDetail (exactly one pane)
//   - not-wide & isCreating                 ⇒ showDetail && showBackControl && !showList
//   - not-wide & !creating & no selection   ⇒ showList
//   - not-wide & !creating & selection
//                & narrowPane==='detail'    ⇒ showDetail
//   - showBackControl === (!isWide && showDetail)  (always)

import { resolvePaneVisibility, type NarrowPane } from '../responsiveLayout'

/* ------------------------------------------------------------------ */
/*  Arbitraries — the full (isWide, hasSelection, narrowPane,          */
/*  isCreating) input space.                                           */
/* ------------------------------------------------------------------ */

const narrowPaneArb: fc.Arbitrary<NarrowPane> = fc.constantFrom('list', 'detail')

const inputArb = fc.record({
  isWide: fc.boolean(),
  hasSelection: fc.boolean(),
  narrowPane: narrowPaneArb,
  isCreating: fc.boolean(),
})

/* ------------------------------------------------------------------ */
/*  Property 1: Pane-resolution truth table                           */
/* ------------------------------------------------------------------ */

describe('Property 1: Pane-resolution truth table', () => {
  it('satisfies the full resolvePaneVisibility truth table for all inputs', () => {
    fc.assert(
      fc.property(inputArb, ({ isWide, hasSelection, narrowPane, isCreating }) => {
        const { showList, showDetail, showBackControl } = resolvePaneVisibility(
          isWide,
          hasSelection,
          narrowPane,
          isCreating,
        )

        if (isWide) {
          // Wide tier: both panes side-by-side, no Back control, regardless of
          // the other inputs (including the Create_View) — Req 1.1, 6.3, 8.3.
          expect(showList).toBe(true)
          expect(showDetail).toBe(true)
          expect(showBackControl).toBe(false)
        } else {
          // Below Wide: exactly one of list/detail is visible — Req 1.2.
          expect(showList).not.toBe(showDetail)

          if (isCreating) {
            // Create_View is the sole pane with a Back control — Req 8.1, 8.2.
            expect(showDetail).toBe(true)
            expect(showBackControl).toBe(true)
            expect(showList).toBe(false)
          } else if (!hasSelection) {
            // No selection ⇒ list — Req 1.3, 1.6.
            expect(showList).toBe(true)
          } else if (narrowPane === 'detail') {
            // Selection + explicit detail intent ⇒ detail — Req 1.4, 2.1.
            expect(showDetail).toBe(true)
          }
        }

        // showBackControl is shown iff the detail pane is shown below Wide — Req 2.1, 2.2.
        expect(showBackControl).toBe(!isWide && showDetail)
      }),
      { numRuns: 200 },
    )
  })
})
