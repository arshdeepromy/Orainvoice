import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import {
  overlayToNormalized,
  normalizedToOverlay,
  type OverlayRect,
  type PageDims,
} from './coordinateMapping'

// Feature: esignature-field-placement, Property 1: Coordinate round-trip is identity within 1 px (per page)
// **Validates: Requirements 7.1, 7.3, 7.5**
//
// For any page rendered at strictly-positive CSS dimensions (including
// non-square pages and, across generated cases, pages that differ from one
// another — R7.5) and any field box that fits within that page, converting the
// field's Overlay_Coordinates to Normalized_Coordinates and back to
// Overlay_Coordinates at the **same** page dimensions reproduces the original
// box within a tolerance of one CSS pixel on `x`, `y`, `width`, and `height`
// (R7.3 round-trip property). The transform uses the specific page's
// dimensions (R7.1), so the property is asserted per page.

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

// Strictly-positive page dimensions. Width and height are drawn independently
// so the generated cases include non-square pages and, across runs, pages of
// differing dimensions (R7.5). The precondition of the transform is
// cssWidth > 0 && cssHeight > 0.
const dimArb: fc.Arbitrary<PageDims> = fc.record({
  cssWidth: fc.double({ min: 1, max: 5000, noNaN: true, noDefaultInfinity: true }),
  cssHeight: fc.double({ min: 1, max: 5000, noNaN: true, noDefaultInfinity: true }),
})

// A unit fraction in [0, 1].
const fractionArb: fc.Arbitrary<number> = fc.double({
  min: 0,
  max: 1,
  noNaN: true,
  noDefaultInfinity: true,
})

/**
 * Build an overlay rect that fits entirely within the page from four unit
 * fractions: the origin fraction plus a size fraction scaled into the
 * remaining space, so `x + w <= cssWidth` and `y + h <= cssHeight`.
 */
function overlayRectIn(
  dims: PageDims,
  fx: number,
  fy: number,
  fwRaw: number,
  fhRaw: number,
): OverlayRect {
  const fw = fwRaw * (1 - fx)
  const fh = fhRaw * (1 - fy)
  return {
    xPx: fx * dims.cssWidth,
    yPx: fy * dims.cssHeight,
    wPx: fw * dims.cssWidth,
    hPx: fh * dims.cssHeight,
  }
}

/* ------------------------------------------------------------------ */
/*  Property 1: round-trip identity within 1 px (per page)             */
/* ------------------------------------------------------------------ */

describe('Property 1: Coordinate round-trip is identity within 1 px (per page)', () => {
  it('reproduces the original overlay rect within 1 CSS px after overlay→normalized→overlay', () => {
    fc.assert(
      fc.property(
        dimArb,
        fractionArb,
        fractionArb,
        fractionArb,
        fractionArb,
        (dims, fx, fy, fw, fh) => {
          const rect = overlayRectIn(dims, fx, fy, fw, fh)

          const roundTripped = normalizedToOverlay(overlayToNormalized(rect, dims), dims)

          // Round-trip identity to within one CSS pixel on every component
          // (R7.3). The transforms are exact scalar inverses, so this holds
          // comfortably inside the 1 px tolerance.
          expect(Math.abs(roundTripped.xPx - rect.xPx)).toBeLessThanOrEqual(1)
          expect(Math.abs(roundTripped.yPx - rect.yPx)).toBeLessThanOrEqual(1)
          expect(Math.abs(roundTripped.wPx - rect.wPx)).toBeLessThanOrEqual(1)
          expect(Math.abs(roundTripped.hPx - rect.hPx)).toBeLessThanOrEqual(1)
        },
      ),
      { numRuns: 200 },
    )
  })
})
