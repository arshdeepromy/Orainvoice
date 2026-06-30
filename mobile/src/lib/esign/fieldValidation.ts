/**
 * fieldValidation.ts — pure client-side Field_Set validation
 * (feature: esignature-field-placement, task 3.1).
 *
 * This mirrors the server-side rules in
 * `app/modules/esignatures/field_validation.py` so the editor can gate the send
 * control entirely client-side: the send button stays disabled while the
 * Field_Set is invalid (R6.4) and re-enables the moment every failure is
 * corrected (R6.5). The server still re-validates the submitted Field_Set
 * before any Documenso call (R6.6) — this client check is a fast, leak-free
 * pre-flight, never the only guard.
 *
 * The rules enforced by {@link validateFieldSet}:
 *
 *   - **R6.2** — every field references an existing recipient: its
 *     `recipientKey` matches a recipient in the Send_Flow recipient list;
 *     otherwise the field is treated as unassigned.
 *   - **R2.4** — every field carries a supported {@link FieldType}.
 *   - **R6.3** — every field is in bounds: `x >= 0`, `y >= 0`, `x + w <= 100`,
 *     `y + h <= 100`, `w > 0`, `h > 0` (normalized percent coordinates).
 *   - **R6.1** — every signer recipient (signing role `signer`) carries at
 *     least one signature-type field. This is the `esignature-integration` R17
 *     safety rule re-expressed over the sender Field_Set.
 *   - **R4.6** — viewer recipients are exempt: a viewer may have no fields.
 *
 * The result is a structured pass/fail object listing **every** offending field
 * (by `clientId`) and signer (by `recipientKey`) so the editor can surface all
 * problems at once and re-enable send only when the list is empty. Messages are
 * humanized and leak-free (R12). Pure, no I/O.
 *
 * _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 4.6, 2.4_
 */

// NOTE (esign shared pure core, task 23.1): mobile-local copy. The *only*
// change from the frontend-v2 source is these two import specifiers — the
// contract symbols (`SigningRole`, `FIELD_TYPES`, `FieldType`, `PlacedField`)
// are re-homed to the self-contained `./fieldSetTypes` so the validation logic
// below stays byte-for-byte identical to the web copy (R16.9 parity).
import type { SigningRole } from './fieldSetTypes'
import { FIELD_TYPES, type FieldType, type PlacedField } from './fieldSetTypes'

/**
 * Machine-readable validation codes. These mirror the central server-side
 * codes (`field_unassigned`, `invalid_field_type`, `field_out_of_bounds`,
 * `signature_field_missing`) so the client and server speak the same vocabulary.
 */
export type FieldValidationCode =
  | 'field_unassigned'
  | 'invalid_field_type'
  | 'field_out_of_bounds'
  | 'signature_field_missing'
  | 'field_options_missing'

/**
 * The minimal recipient shape the validator needs: a stable `key` (matching a
 * field's `recipientKey`) and the recipient's `signing_role`. `name`/`email`
 * are used only to humanize the signature-missing message. Mirrors the
 * SendForSignatureModal recipient row.
 */
export interface FieldValidationRecipient {
  /** Stable key referenced by a field's `recipientKey` (R4.1). */
  key: number
  /** Signer recipients require ≥1 signature field; viewers are exempt (R4.6). */
  signing_role: SigningRole
  /** Optional display name, used to humanize messages. */
  name?: string
  /** Optional email, used as a fallback display name. */
  email?: string
}

/** One validation failure, naming the offending field or signer(s). */
export interface FieldValidationIssue {
  /** Machine-readable code (mirrors the server codes). */
  code: FieldValidationCode
  /** Human-readable, leak-free message describing the problem (R12.1). */
  message: string
  /** `clientId` of the offending field, for field-level issues. */
  clientId?: string
  /** Keys of the signer(s) missing a signature field (signature_field_missing). */
  recipientKeys?: number[]
}

/** Outcome of {@link validateFieldSet}. */
export interface FieldValidationResult {
  /** `true` only when every rule holds (the Field_Set may be sent). */
  ok: boolean
  /** Every failure found; empty iff `ok` is `true`. */
  issues: FieldValidationIssue[]
}

/** The supported field types as a fast membership set (R2.4). */
const SUPPORTED_FIELD_TYPES: ReadonlySet<string> = new Set(FIELD_TYPES)

/** The signature-type field a signer must carry at least one of (R6.1). */
const SIGNATURE_FIELD_TYPE: FieldType = 'signature'

/**
 * The field types that require a sender-authored options list (≥1 non-empty
 * option) before they can be sent. `checkbox` is a single box and needs no
 * options; `number` behaves like `text`. Mirrors the server's
 * `OPTION_BEARING_FIELD_TYPES`.
 */
const OPTION_BEARING_FIELD_TYPES: ReadonlySet<string> = new Set<FieldType>(['radio', 'dropdown'])

/** Return `true` when a field carries at least one non-empty option. */
function hasNonEmptyOption(field: PlacedField): boolean {
  return (field.options ?? []).some((option) => typeof option === 'string' && option.trim() !== '')
}

/**
 * Bounds tolerance. Coordinates are normalized percent in [0, 100]; a tiny
 * epsilon absorbs floating-point drift on the `x + w <= 100` / `y + h <= 100`
 * edge so a field the editor clamped exactly to the page edge is not spuriously
 * rejected. Mirrors the server's `_BOUNDS_EPS`.
 */
const BOUNDS_EPS = 1e-9

/**
 * Return `true` when a field's normalized rect is fully within the page (R6.3):
 * `x >= 0`, `y >= 0`, `x + w <= 100`, `y + h <= 100`, `w > 0`, `h > 0`. A
 * missing/non-finite coordinate is out of bounds (rejected).
 */
function isInBounds(field: PlacedField): boolean {
  const { positionX: x, positionY: y, width: w, height: h } = field.rect
  if (![x, y, w, h].every((n) => typeof n === 'number' && Number.isFinite(n))) {
    return false
  }
  if (w <= 0 || h <= 0) return false
  if (x < 0 || y < 0) return false
  if (x + w > 100 + BOUNDS_EPS || y + h > 100 + BOUNDS_EPS) return false
  return true
}

/** Best-effort display name for a recipient, falling back to email then generic. */
function recipientName(recipient: FieldValidationRecipient): string {
  if (recipient.name && recipient.name.trim()) return recipient.name.trim()
  if (recipient.email && recipient.email.trim()) return recipient.email.trim()
  return 'this signer'
}

/**
 * Join recipient names into a natural-language list:
 * `["A"] -> "A"`, `["A", "B"] -> "A and B"`, `["A","B","C"] -> "A, B, and C"`.
 */
function humanizeNames(names: string[]): string {
  if (names.length === 0) return 'this signer'
  if (names.length === 1) return names[0]
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`
}

/**
 * Validate a sender-defined Field_Set against the same rules the server
 * enforces. Returns a structured pass/fail result listing every offending field
 * and signer so the editor can keep send disabled until valid (R6.4) and
 * re-enable it on correction (R6.5).
 *
 * @param fields the placed Field_Set (geometry stored normalized, percent 0–100).
 * @param recipients the Send_Flow recipient list (keys + signing roles).
 * @returns a {@link FieldValidationResult}; `ok` is `true` iff `issues` is empty.
 *
 * Pure — no I/O, never throws.
 */
export function validateFieldSet(
  fields: readonly PlacedField[],
  recipients: readonly FieldValidationRecipient[],
): FieldValidationResult {
  const issues: FieldValidationIssue[] = []

  const recipientKeys = new Set(recipients.map((r) => r.key))

  // Field-level rules (R6.2, R2.4, R6.3), collected for every field so the
  // editor can surface all problems at once.
  for (const field of fields) {
    // R6.2 — assigned to an existing recipient.
    if (!recipientKeys.has(field.recipientKey)) {
      issues.push({
        code: 'field_unassigned',
        message: `A field on page ${field.page} isn't assigned to a recipient. Assign it before sending.`,
        clientId: field.clientId,
      })
      // Once unassigned, the remaining checks still run so every problem with
      // this field surfaces independently.
    }

    // R2.4 — supported field type.
    if (!SUPPORTED_FIELD_TYPES.has(field.type)) {
      issues.push({
        code: 'invalid_field_type',
        message: `A field on page ${field.page} has an unsupported type.`,
        clientId: field.clientId,
      })
    }

    // R6.3 — fully within the page bounds.
    if (!isInBounds(field)) {
      issues.push({
        code: 'field_out_of_bounds',
        message: `A field on page ${field.page} extends past the edge of the page. Move it fully onto the page.`,
        clientId: field.clientId,
      })
    }

    // A radio/dropdown field must carry at least one non-empty option (mirrors
    // the server rule) so a recipient is never shown an empty chooser.
    if (OPTION_BEARING_FIELD_TYPES.has(field.type) && !hasNonEmptyOption(field)) {
      issues.push({
        code: 'field_options_missing',
        message: `Add at least one option to the ${field.type} field.`,
        clientId: field.clientId,
      })
    }
  }

  // R6.1 — every signer recipient carries ≥1 signature-type field; viewers are
  // exempt (R4.6). Only count signature fields assigned to an existing signer.
  const signers = recipients.filter((r) => r.signing_role === 'signer')
  const signersWithSignature = new Set(
    fields
      .filter((f) => f.type === SIGNATURE_FIELD_TYPE && recipientKeys.has(f.recipientKey))
      .map((f) => f.recipientKey),
  )
  const missingSigners = signers.filter((s) => !signersWithSignature.has(s.key))
  if (missingSigners.length > 0) {
    issues.push({
      code: 'signature_field_missing',
      message: `Add a signature field for ${humanizeNames(
        missingSigners.map(recipientName),
      )} before sending.`,
      recipientKeys: missingSigners.map((s) => s.key),
    })
  }

  return { ok: issues.length === 0, issues }
}

export default validateFieldSet
