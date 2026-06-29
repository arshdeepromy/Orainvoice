/**
 * Field_Set contract types for the mobile esign pure core.
 *
 * These are the *contract* symbols that `fieldValidation.ts` depends on. In
 * `frontend-v2/` they live in `@/api/esign` (`SigningRole`) and the editor hook
 * `components/esign/fieldplacement/hooks/useFieldSet` (`FIELD_TYPES`,
 * `FieldType`, `PlacedField`). The mobile pure-core copy is kept self-contained
 * (no dependency on the not-yet-built mobile editor hook / api module from
 * tasks 24.x), so the same definitions are duplicated here **verbatim** from the
 * frontend-v2 sources. Keep them byte-for-byte in sync so validation parity
 * (R16.9, Property 23) holds.
 */

import type { NormalizedRect } from './coordinateMapping'

/** Signer recipients require ≥1 signature field; viewers are exempt (R4.6). Mirrors `@/api/esign`. */
export type SigningRole = 'signer' | 'viewer'

export const FIELD_TYPES = ['signature', 'initials', 'name', 'date', 'email', 'text'] as const

/** The kind of a placed field. Maps 1:1 to a Documenso field type on send (R2.4). */
export type FieldType = (typeof FIELD_TYPES)[number]

/** One placed field in the Field_Set. Geometry is stored normalized (R7). */
export interface PlacedField {
  /** Stable local key (e.g. `crypto.randomUUID()`); never sent to Documenso. */
  clientId: string
  /** The field's type (R2.1). */
  type: FieldType
  /** 1-based page the field sits on. */
  page: number
  /** Position + size in normalized page units (percent 0–100, origin top-left). */
  rect: NormalizedRect
  /** References a SendForSignatureModal recipient row's key (R4.1). */
  recipientKey: number
  /** Required/optional flag; defaults per type on add (R2.3, R5.1). */
  required: boolean
  /** Label for `text` fields only (R5.2). */
  label?: string
  /** Placeholder for `text` fields only (R5.2). */
  placeholder?: string
}
