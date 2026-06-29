/**
 * fieldColors.ts — deterministic, high-contrast recipient colour palette
 * (feature: esignature-field-placement, task 2.2).
 *
 * Field placement colour-codes every placed field by its assigned recipient so
 * the Org_Sender can see at a glance which person each field belongs to (R4.4).
 * This module owns the single source of truth for that mapping: it maps a
 * recipient's 0-based index in the Send_Flow recipient list to a distinct,
 * high-contrast colour.
 *
 * The mapping is:
 *   - **Deterministic** — the same index always yields the same colour, so the
 *     editor, legend, and overlay agree without sharing state.
 *   - **Pairwise-distinct within capacity** — for any recipient list whose size
 *     is ≤ {@link FIELD_COLOR_PALETTE_CAPACITY}, every recipient receives a
 *     colour different from every other recipient (Property 7, R4.4). Indices
 *     beyond the palette capacity wrap (modulo) so a colour is always returned,
 *     accepting that two recipients may then share a colour.
 *   - **Pure, no I/O** — trivially testable.
 *
 * Colours are chosen for high contrast against a white PDF page and against
 * each other (distinct hues spread around the wheel), and each carries a
 * matching translucent fill plus a readable on-colour text colour so callers
 * can render solid borders, soft fills, and labels from one entry.
 *
 * _Requirements: 4.4_
 */

/** A recipient colour with derived variants for borders, fills, and labels. */
export interface FieldColor {
  /** Solid colour for borders / handles / the recipient swatch (hex, e.g. `#2563eb`). */
  readonly solid: string
  /** Translucent fill for the field box interior (rgba). */
  readonly fill: string
  /** Readable text colour to place on top of {@link solid} (hex). */
  readonly onSolid: string
}

/**
 * The fixed, high-contrast palette. Hues are spread around the colour wheel and
 * kept visually distinct from one another and from a white page background.
 * Order is stable — never reorder, only append — so a recipient's colour does
 * not change between releases for the same index.
 */
export const FIELD_COLOR_PALETTE: readonly FieldColor[] = [
  { solid: '#2563eb', fill: 'rgba(37, 99, 235, 0.18)', onSolid: '#ffffff' }, // blue
  { solid: '#dc2626', fill: 'rgba(220, 38, 38, 0.18)', onSolid: '#ffffff' }, // red
  { solid: '#16a34a', fill: 'rgba(22, 163, 74, 0.18)', onSolid: '#ffffff' }, // green
  { solid: '#d97706', fill: 'rgba(217, 119, 6, 0.18)', onSolid: '#ffffff' }, // amber
  { solid: '#9333ea', fill: 'rgba(147, 51, 234, 0.18)', onSolid: '#ffffff' }, // purple
  { solid: '#0891b2', fill: 'rgba(8, 145, 178, 0.18)', onSolid: '#ffffff' }, // cyan
  { solid: '#db2777', fill: 'rgba(219, 39, 119, 0.18)', onSolid: '#ffffff' }, // pink
  { solid: '#65a30d', fill: 'rgba(101, 163, 13, 0.18)', onSolid: '#ffffff' }, // lime
  { solid: '#4f46e5', fill: 'rgba(79, 70, 229, 0.18)', onSolid: '#ffffff' }, // indigo
  { solid: '#ea580c', fill: 'rgba(234, 88, 12, 0.18)', onSolid: '#ffffff' }, // orange
  { solid: '#0d9488', fill: 'rgba(13, 148, 136, 0.18)', onSolid: '#ffffff' }, // teal
  { solid: '#be123c', fill: 'rgba(190, 18, 60, 0.18)', onSolid: '#ffffff' }, // rose
]

/**
 * The number of distinct colours available. For recipient lists no larger than
 * this, {@link recipientColor} returns a unique colour per recipient (R4.4).
 */
export const FIELD_COLOR_PALETTE_CAPACITY = FIELD_COLOR_PALETTE.length

/**
 * Map a recipient's 0-based index to its colour. Deterministic and total:
 * negative indices are normalised and indices ≥ the palette capacity wrap
 * modulo the palette length so a colour is always returned.
 *
 * @param index 0-based position of the recipient in the Send_Flow recipient list.
 * @returns the {@link FieldColor} for that recipient.
 */
export function recipientColor(index: number): FieldColor {
  const len = FIELD_COLOR_PALETTE.length
  // Normalise to a non-negative integer in [0, len) without throwing on
  // out-of-range / non-integer input.
  const normalized = ((Math.trunc(index) % len) + len) % len
  return FIELD_COLOR_PALETTE[normalized]
}
