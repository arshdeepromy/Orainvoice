import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: esignature-field-placement, Property 2: Normalized coordinates are independent of render scale
// **Validates: Requirements 7.2**
//
// A field placed on a PDF page occupies a fixed fraction of that page. When the
// same page is rendered at two different scales (e.g. a 320 px viewport vs a
// wide desktop viewport), the field's overlay CSS-pixel box scales with the page
// — but `overlayToNormalized` divides out the rendered dimensions, so the
// resulting NormalizedRect (percent, origin top-left) MUST be identical at both
// scales, within floating-point epsilon. This is the scale-independence
// guarantee (R7.2) that lets the editor store fields as percentages and survive
// any viewport resize.

import { overlayToNormalized, type OverlayRect, type PageDims } from './coordinateMapping'

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/*                                                                     */
/*  - A page's intrinsic CSS size at scale 1 (>=320 px wide so every   */
/*    rendered scale stays within the supported >=320 px viewport      */
/*    range, since scale >= 1).                                        */
/*  - A field as fractions of the page that fit inside it.             */
/*  - Two strictly-positive render scales.                             */
/* ------------------------------------------------------------------ */

const baseWidthArb = fc.double({ min: 320, max: 1200, noNaN: true, noDefaultInfinity: true })
const baseHeightArb = fc.double({ min: 320, max: 1600, noNaN: true, noDefaultInfinity: true })

// Strictly-positive render scales; >= 1 keeps the rendered width >= 320 px.
const scaleArb = fc.double({ min: 1, max: 6, noNaN: true, noDefaultInfinity: true })

const fractionArb = fc.double({ min: 0, max: 1, noNaN: true, noDefaultInfinity: true })

/** A field expressed as page fractions that fit fully within the page. */
const fieldFractionArb = fc
  .record({
    fx: fractionArb,
    fy: fractionArb,
    fw: fractionArb,
    fh: fractionArb,
  })
  .map(({ fx, fy, fw, fh }) => ({
    // Keep the box inside the page: x + w <= 1, y + h <= 1.
    fx: fx * (1 - fw),
    fy: fy * (1 - fh),
    fw,
    fh,
  }))

/** Build the overlay rect for a field at a given render scale of the page. */
function overlayAtScale(
  field: { fx: number; fy: number; fw: number; fh: number },
  baseWidth: number,
  baseHeight: number,
  scale: number,
): { rect: OverlayRect; dims: PageDims } {
  const dims: PageDims = { cssWidth: baseWidth * scale, cssHeight: baseHeight * scale }
  const rect: OverlayRect = {
    xPx: field.fx * dims.cssWidth,
    yPx: field.fy * dims.cssHeight,
    wPx: field.fw * dims.cssWidth,
    hPx: field.fh * dims.cssHeight,
  }
  return { rect, dims }
}

/* ------------------------------------------------------------------ */
/*  Property 2: scale independence                                     */
/* ------------------------------------------------------------------ */

describe('Property 2: Normalized coordinates are independent of render scale', () => {
  it('yields the same NormalizedRect for the same page fraction at any render scale', () => {
    fc.assert(
      fc.property(
        fieldFractionArb,
        baseWidthArb,
        baseHeightArb,
        scaleArb,
        scaleArb,
        (field, baseWidth, baseHeight, scale1, scale2) => {
          const a = overlayAtScale(field, baseWidth, baseHeight, scale1)
          const b = overlayAtScale(field, baseWidth, baseHeight, scale2)

          const na = overlayToNormalized(a.rect, a.dims)
          const nb = overlayToNormalized(b.rect, b.dims)

          // Both rendered widths must be inside the supported viewport range.
          expect(a.dims.cssWidth).toBeGreaterThanOrEqual(320)
          expect(b.dims.cssWidth).toBeGreaterThanOrEqual(320)

          const EPS = 1e-9
          expect(na.positionX).toBeCloseTo(nb.positionX, 9)
          expect(na.positionY).toBeCloseTo(nb.positionY, 9)
          expect(na.width).toBeCloseTo(nb.width, 9)
          expect(na.height).toBeCloseTo(nb.height, 9)

          // And each equals the underlying fraction * 100, independent of scale.
          expect(Math.abs(na.positionX - field.fx * 100)).toBeLessThanOrEqual(EPS)
          expect(Math.abs(na.positionY - field.fy * 100)).toBeLessThanOrEqual(EPS)
          expect(Math.abs(na.width - field.fw * 100)).toBeLessThanOrEqual(EPS)
          expect(Math.abs(na.height - field.fh * 100)).toBeLessThanOrEqual(EPS)
        },
      ),
      { numRuns: 100 },
    )
  })
})
