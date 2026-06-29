/**
 * Coordinate_Mapping (R7) — the critical overlay↔normalized transform.
 *
 * The field-placement editor works in **overlay CSS pixels** relative to a
 * rendered PDF page element, while Documenso's `field/create-many` endpoint
 * accepts each field as **normalised page units** (percent 0–100, origin
 * top-left). These pure functions convert between the two **per page**, using
 * that specific page's rendered dimensions, so the result is independent of the
 * on-screen render scale (R7.1, R7.2) and correct for PDFs whose pages differ in
 * size (R7.5).
 *
 * No rounding is applied inside the transforms — they are pure scalar
 * multiply/divide with no I/O — so the round-trip
 * `normalizedToOverlay(overlayToNormalized(rect, dims), dims)` reproduces the
 * original rect within floating-point epsilon, comfortably inside the ≤1 CSS px
 * tolerance (R7.3).
 */

/** A field box in on-screen overlay pixels, relative to the rendered page element. */
export interface OverlayRect {
  xPx: number
  yPx: number
  wPx: number
  hPx: number
}

/**
 * A field box in normalised page units (percent 0–100, origin top-left), held
 * internally by the editor. On the wire its fields serialise as
 * positionX→pageX, positionY→pageY, width→width, height→height.
 */
export interface NormalizedRect {
  positionX: number
  positionY: number
  width: number
  height: number
}

/** The rendered page's CSS pixel dimensions (from RenderedPage). */
export interface PageDims {
  cssWidth: number
  cssHeight: number
}

/**
 * Overlay px → normalized percent for one page. Divides out the rendered
 * dimensions so the result is independent of render scale (R7.1, R7.2).
 *
 * Pre: `dims.cssWidth > 0 && dims.cssHeight > 0`.
 */
export function overlayToNormalized(rect: OverlayRect, dims: PageDims): NormalizedRect {
  return {
    positionX: (rect.xPx / dims.cssWidth) * 100,
    positionY: (rect.yPx / dims.cssHeight) * 100,
    width: (rect.wPx / dims.cssWidth) * 100,
    height: (rect.hPx / dims.cssHeight) * 100,
  }
}

/**
 * Normalized percent → overlay px for one page, at the page's current rendered
 * dimensions. Exact inverse of {@link overlayToNormalized} at the same dims (R7.3).
 */
export function normalizedToOverlay(rect: NormalizedRect, dims: PageDims): OverlayRect {
  return {
    xPx: (rect.positionX / 100) * dims.cssWidth,
    yPx: (rect.positionY / 100) * dims.cssHeight,
    wPx: (rect.width / 100) * dims.cssWidth,
    hPx: (rect.height / 100) * dims.cssHeight,
  }
}

/**
 * Clamp a field, in overlay space, so its whole area stays on the page and it
 * remains at least the minimum displayable size.
 *
 * Enforces (R3.5, R3.6, R6.3):
 *   - `wPx >= minWpx` and `hPx >= minHpx` (min size never exceeds the page);
 *   - `xPx >= 0` and `yPx >= 0`;
 *   - `xPx + wPx <= dims.cssWidth` and `yPx + hPx <= dims.cssHeight`.
 *
 * Width/height are resolved first (capped to the page so the box can always
 * fit), then the position is shifted inward so the far edge stays on the page.
 * Pure, no rounding, no I/O.
 */
export function clampToPage(
  rect: OverlayRect,
  dims: PageDims,
  minWpx: number,
  minHpx: number,
): OverlayRect {
  // Resolve size first: at least the minimum, but never wider/taller than the page.
  const wPx = Math.min(Math.max(rect.wPx, minWpx), dims.cssWidth)
  const hPx = Math.min(Math.max(rect.hPx, minHpx), dims.cssHeight)

  // Position so the whole box stays within [0, cssWidth] × [0, cssHeight].
  const xPx = Math.min(Math.max(rect.xPx, 0), dims.cssWidth - wPx)
  const yPx = Math.min(Math.max(rect.yPx, 0), dims.cssHeight - hPx)

  return { xPx, yPx, wPx, hPx }
}
