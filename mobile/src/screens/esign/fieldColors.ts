/**
 * fieldColors (mobile) — deterministic, high-contrast recipient colour palette.
 *
 * The Mobile_Field_Placement_Editor colour-codes every placed field by its
 * assigned recipient so the Org_Sender can see at a glance which person each
 * field belongs to (R4.4). This mirrors the frontend-v2
 * `components/esign/fieldplacement/lib/fieldColors.ts` palette so the two
 * surfaces present identical recipient colours for the same index. Pure, no I/O.
 */

/** A recipient colour with derived variants for borders, fills, and labels. */
export interface FieldColor {
  /** Solid colour for borders / handles / the recipient swatch (hex). */
  readonly solid: string
  /** Translucent fill for the field box interior (rgba). */
  readonly fill: string
  /** Readable text colour to place on top of {@link solid} (hex). */
  readonly onSolid: string
}

/**
 * The fixed, high-contrast palette. Order is stable — never reorder, only
 * append — so a recipient's colour does not change for the same index.
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

/** The number of distinct colours available. */
export const FIELD_COLOR_PALETTE_CAPACITY = FIELD_COLOR_PALETTE.length

/**
 * Map a recipient's 0-based index to its colour. Deterministic and total:
 * negative / non-integer indices are normalised and indices ≥ capacity wrap
 * modulo the palette length so a colour is always returned.
 */
export function recipientColor(index: number): FieldColor {
  const len = FIELD_COLOR_PALETTE.length
  const normalized = ((Math.trunc(index) % len) + len) % len
  return FIELD_COLOR_PALETTE[normalized]
}
