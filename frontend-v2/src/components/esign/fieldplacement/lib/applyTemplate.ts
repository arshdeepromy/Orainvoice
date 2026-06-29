/**
 * applyTemplate.ts — pure client-side "apply a Field_Template by role" (R17)
 * (feature: esignature-field-placement, task 21.3).
 *
 * A Field_Template (R17.1) stores its fields against abstract
 * **Template_Recipient_Role** slots (e.g. `signer 1`, `signer 2`, `viewer`)
 * rather than against specific people — no recipient name or email is ever
 * persisted. Applying a template to the current send therefore means mapping
 * each distinct role slot onto one of the send's actual recipients and copying
 * every template field into a fresh {@link PlacedField} assigned to the mapped
 * recipient.
 *
 * This is **entirely client-side** (R17.5): the template id is never sent to
 * Documenso. The output is an ordinary Field_Set, indistinguishable from one
 * the sender placed by hand, so it flows through the same send validation as
 * any other set (R17.8).
 *
 * If the template references a role that the caller's `roleToRecipientKey`
 * mapping does not resolve, the apply **fails** and names the unmapped roles so
 * the editor can prompt the sender to complete the mapping before applying
 * (R17.6, the role-overflow prompt). On failure **no** placed fields are
 * produced, so no applied field is ever left unassigned.
 *
 * Pure, no I/O, no randomness in the mapping itself — fresh `clientId`s are
 * generated for each placed field (off any shared mutable state) so applying a
 * template twice yields two independent Field_Sets.
 *
 * _Requirements: 17.5, 17.6, 17.8_
 */

import type { TemplateFieldIn } from '@/api/esign'
import type { NormalizedRect } from './coordinateMapping'
import type { PlacedField } from '../hooks/useFieldSet'

/**
 * The minimal template shape this helper needs: the list of template fields.
 * Structurally satisfied by `FieldTemplateOut` / `FieldTemplateCreate` from
 * `@/api/esign`, so callers can pass a fetched template straight in. Accepting
 * the field list (rather than the whole template object) keeps this pure helper
 * free of any dependency on the wider template response shape.
 */
export interface TemplateLike {
  fields: readonly TemplateFieldIn[]
}

/**
 * A mapping from each Template_Recipient_Role slot to one of the current send's
 * recipient keys (the same stable `recipientKey` used by the editor's
 * {@link PlacedField}). A role is "mapped" when its slot is present here with a
 * defined recipient key.
 */
export type RoleToRecipientKey = Readonly<Record<string, number>>

/**
 * The result of {@link applyTemplate}: a discriminated union so the caller must
 * handle the unmapped-role case before reading any fields.
 *
 *  - `{ ok: true, fields }` — every role resolved; `fields` is exactly one
 *    placed field per template field (R17.5).
 *  - `{ ok: false, unmappedRoles }` — one or more roles had no mapping; no
 *    fields are produced and the unmapped role slots are named for the prompt
 *    (R17.6). `unmappedRoles` is de-duplicated and preserves first-seen order.
 */
export type ApplyTemplateResult =
  | { ok: true; fields: PlacedField[] }
  | { ok: false; unmappedRoles: string[] }

/** A stable client id for a newly placed field (kept off any pure mapping). */
function newClientId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (c?.randomUUID) return c.randomUUID()
  // Fallback for environments without crypto.randomUUID.
  return `f_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`
}

/** True when `key` is a usable recipient key (present and a finite number). */
function isMapped(key: number | undefined): key is number {
  return typeof key === 'number' && Number.isFinite(key)
}

/**
 * Populate the current send's Field_Set from a Field_Template by mapping each
 * field's Template_Recipient_Role to one of the send's recipients.
 *
 * For each template field: a fresh `clientId` is generated, the
 * `type`, `page`, normalized geometry, `required` flag, and (for text fields)
 * `label`/`placeholder` are carried over verbatim, and `recipientKey` is set
 * from `roleToRecipientKey[field.template_role]`.
 *
 * If any template field's role is unmapped, the whole apply fails (R17.6) and
 * the unmapped role slots are returned (de-duplicated, first-seen order); no
 * placed fields are produced.
 *
 * @param template The template (or anything exposing its `fields`) to apply.
 * @param roleToRecipientKey Map of each role slot → a current recipient key.
 */
export function applyTemplate(
  template: TemplateLike,
  roleToRecipientKey: RoleToRecipientKey,
): ApplyTemplateResult {
  const templateFields = template.fields ?? []

  // First pass: collect every role that has no usable mapping, de-duplicated
  // and in first-seen order, so the prompt can list exactly the missing slots.
  const unmappedRoles: string[] = []
  const seenUnmapped = new Set<string>()
  for (const field of templateFields) {
    const role = field.template_role
    if (!isMapped(roleToRecipientKey[role]) && !seenUnmapped.has(role)) {
      seenUnmapped.add(role)
      unmappedRoles.push(role)
    }
  }

  if (unmappedRoles.length > 0) {
    // R17.6: refuse to apply until every role resolves — produce no fields so
    // no applied field is ever left unassigned.
    return { ok: false, unmappedRoles }
  }

  // Second pass: every role resolves — copy each template field into a fresh
  // placed field assigned to its mapped recipient (R17.5).
  const fields: PlacedField[] = templateFields.map((field) => {
    const rect: NormalizedRect = {
      positionX: field.position_x,
      positionY: field.position_y,
      width: field.width,
      height: field.height,
    }
    const placed: PlacedField = {
      clientId: newClientId(),
      type: field.type,
      page: field.page,
      rect,
      recipientKey: roleToRecipientKey[field.template_role],
      required: field.required,
    }
    if (field.label !== undefined) placed.label = field.label
    if (field.placeholder !== undefined) placed.placeholder = field.placeholder
    return placed
  })

  return { ok: true, fields }
}

export default applyTemplate
