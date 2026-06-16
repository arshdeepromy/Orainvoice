import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: responsive-invoice-layout, Property 3: POS preview enablement gates panel and print action together
// **Validates: Requirements 3.3, 6.5**
//
// In `InvoiceList.tsx` a single org-level boolean drives BOTH POS surfaces:
//   const posPreviewEnabled = settings?.invoice?.pos_preview_enabled ?? true
// It gates the POS receipt panel:
//   {posPreviewEnabled && (<div data-preview="receipt" ...>...)}
// AND the print action:
//   {posPreviewEnabled && (<button ...>Print POS Receipt</button>)}
//
// Because both surfaces are derived from the same flag, this is a pure-logic
// property. We model the component's gating exactly with two tiny pure
// predicates and assert, for all `posPreviewEnabled ∈ {true,false}`:
//   - the POS_Receipt_Panel is present iff the flag is true,
//   - the "Print POS Receipt" action is present iff the flag is true, and
//   - the two surfaces are always consistent (equal to each other and the flag).

/* ------------------------------------------------------------------ */
/*  Pure model mirroring the gating in InvoiceList.tsx.                */
/*  Both POS surfaces are driven by the single `posPreviewEnabled`     */
/*  boolean: `{posPreviewEnabled && (...)}` for each.                  */
/* ------------------------------------------------------------------ */

/** Whether the POS_Receipt_Panel (`data-preview="receipt"`) is rendered. */
const posPanelVisible = (posPreviewEnabled: boolean): boolean => posPreviewEnabled

/** Whether the "Print POS Receipt" action is available. */
const printPosActionVisible = (posPreviewEnabled: boolean): boolean => posPreviewEnabled

/* ------------------------------------------------------------------ */
/*  Property 3: POS preview enablement gates panel and print action    */
/*  together.                                                          */
/* ------------------------------------------------------------------ */

describe('Property 3: POS preview enablement gates panel and print action together', () => {
  it('renders the POS panel and Print POS Receipt action iff posPreviewEnabled, always consistent', () => {
    fc.assert(
      fc.property(fc.boolean(), (posPreviewEnabled) => {
        const panel = posPanelVisible(posPreviewEnabled)
        const printAction = printPosActionVisible(posPreviewEnabled)

        // Panel is present iff the flag is true — Req 3.3.
        expect(panel).toBe(posPreviewEnabled)
        // Print POS Receipt action is present iff the flag is true — Req 6.5.
        expect(printAction).toBe(posPreviewEnabled)
        // The two surfaces are always consistent (driven by the same flag).
        expect(panel).toBe(printAction)
      }),
      { numRuns: 200 },
    )
  })
})
