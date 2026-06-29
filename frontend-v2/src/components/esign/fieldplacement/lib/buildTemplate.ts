/**
 * buildTemplate.ts — pure client-side "serialise the current Field_Set into a
 * reusable Field_Template" (R17.1) (feature: esignature-field-placement,
 * task 21.5). The exact inverse of {@link applyTemplate} (`lib/applyTemplate.ts`).
 *
 * A Field_Template (R17.1) is durable, named, org-scoped data that stores its
 * fields against abstract **Template_Recipient_Role** slots (e.g. `signer 1`,
 * `viewer 1`) rather than against specific people — it must contain **no**
 * recipient name and **no** recipient email anywhere. This helper takes the
 * Field_Set the sender has placed plus a mapping from each recipient key to its
 * abstract role slot, and produces a {@link FieldTemplateCreate} ready to POST
 * to `createFieldTemplate`:
 *
 *   - each placed field becomes a {@link TemplateFieldIn} carrying its
 *     `type`, `page`, Normalized_Coordinates, `required` flag, and (for `text`
 *     fields) `label`/`placeholder` verbatim, plus the `template_role` slot its
 *     recipient maps to — never the recipient's identity;
 *   - `roles[]` is the set of distinct Template_Recipient_Role slots the
 *     template's fields refer to, de-duplicated and in first-seen order, used at
 *     apply time to drive the role→recipient mapping (R17.5, R17.6).
 *
 * Because the output references recipients only by abstract role, the produced
 * template is round-trippable through {@link applyTemplate} against any current
 * send whose roles resolve, and its serialized form leaks no PII (R17.1).
 *
 * Pure, no I/O. A field whose `recipientKey` has no role in
 * `recipientKeyToRole` is a programming error (the editor always supplies a
 * complete mapping derived from the live recipient list) and throws rather than
 * silently dropping the field or emitting an `undefined` role.
 *
 * _Requirements: 17.1_
 */

import type {
  AgreementType,
  FieldTemplateCreate,
  PlacedFieldLike,
  TemplateFieldIn,
} from '@/api/esign'

/**
 * A mapping from each current-send recipient key (the stable `recipientKey`
 * carried by a {@link PlacedFieldLike}) to the abstract Template_Recipient_Role
 * slot it should be stored under. Every distinct recipient a placed field
 * references MUST be present here.
 */
export type RecipientKeyToRole = Readonly<Record<number, string>>

/** Optional template metadata that isn't derivable from the Field_Set itself. */
export interface BuildTemplateOptions {
  /** The template's display name (R17.1). Defaults to an empty string. */
  name?: string
  /** Optional agreement-type association (R17.2). */
  agreementType?: AgreementType
}

/**
 * Serialise a placed Field_Set into a {@link FieldTemplateCreate} that stores
 * roles, never people (R17.1).
 *
 * @param fields The current Field_Set (the editor's `PlacedField[]` satisfies
 *   {@link PlacedFieldLike} structurally).
 * @param recipientKeyToRole Map of each recipient key → its abstract role slot.
 * @param options Template name + optional agreement-type.
 * @throws If a placed field references a recipient key absent from
 *   `recipientKeyToRole`.
 */
export function buildTemplate(
  fields: readonly PlacedFieldLike[],
  recipientKeyToRole: RecipientKeyToRole,
  options: BuildTemplateOptions = {},
): FieldTemplateCreate {
  const roles: string[] = []
  const seenRoles = new Set<string>()

  const templateFields: TemplateFieldIn[] = (fields ?? []).map((field) => {
    const role = recipientKeyToRole[field.recipientKey]
    if (role === undefined) {
      throw new Error(
        `Placed field references recipient key ${field.recipientKey}, ` +
          'which has no Template_Recipient_Role mapping.',
      )
    }
    if (!seenRoles.has(role)) {
      seenRoles.add(role)
      roles.push(role)
    }

    const out: TemplateFieldIn = {
      type: field.type,
      page: field.page,
      position_x: field.rect.positionX,
      position_y: field.rect.positionY,
      width: field.rect.width,
      height: field.rect.height,
      required: field.required,
      template_role: role,
    }
    // Carry text metadata verbatim, only when present (text fields only).
    if (field.label !== undefined) out.label = field.label
    if (field.placeholder !== undefined) out.placeholder = field.placeholder
    return out
  })

  const template: FieldTemplateCreate = {
    name: options.name ?? '',
    fields: templateFields,
    roles,
  }
  if (options.agreementType !== undefined) template.agreement_type = options.agreementType
  return template
}

export default buildTemplate
