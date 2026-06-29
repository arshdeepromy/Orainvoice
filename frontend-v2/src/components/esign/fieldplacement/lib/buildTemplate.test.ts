import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import { buildTemplate, type RecipientKeyToRole } from './buildTemplate'
import type { PlacedFieldLike, FieldType } from '@/api/esign'

// Feature: esignature-field-placement, Property 24: Saved templates store roles, never people
// **Validates: Requirements 17.1**
//
// A Field_Template (R17.1) is durable, org-scoped data that stores its fields
// against abstract Template_Recipient_Role slots rather than specific people.
// For any Field_Set and any assignment of its fields to recipients, the template
// produced by `buildTemplate` must, per field, preserve the field's type, page,
// Normalized_Coordinates, required flag, and (for `text`) label/placeholder,
// together with a `template_role` slot — and its serialized form must contain
// NO recipient name and NO recipient email anywhere.
//
// This file holds ONE property: it generates an arbitrary Field_Set plus
// arbitrary source recipient identities (name + email per recipient key), builds
// a complete recipientKey→role mapping, then asserts (a) each template field
// faithfully carries its geometry/type/required/text-meta + a role slot and
// (b) JSON.stringify(template) leaks none of the source names/emails.

/* ------------------------------------------------------------------ */
/*  Arbitraries.                                                       */
/* ------------------------------------------------------------------ */

const FIELD_TYPES: readonly FieldType[] = [
  'signature',
  'initials',
  'name',
  'date',
  'email',
  'text',
]

const fieldTypeArb: fc.Arbitrary<FieldType> = fc.constantFrom(...FIELD_TYPES)

// A small pool of recipient keys so a generated Field_Set reuses recipients
// (multiple fields per recipient) rather than every field inventing a unique
// recipient. Keys are the stable client keys carried by PlacedFieldLike.
const RECIPIENT_KEYS = [0, 1, 2, 3] as const

// A recipient identity: a name and an email. These are the PII that must NEVER
// appear in the serialized template. We wrap each generated value in a
// distinctive, deterministic marker (a `«…»` envelope plus a PII tag) so the
// "absence" assertion is meaningful even for empty/short generated strings, and
// so an arbitrary field label/placeholder cannot accidentally collide with it.
// (No Math.random — values must stay deterministic for fast-check shrinking.)
const nameArb: fc.Arbitrary<string> = fc
  .string({ maxLength: 20 })
  .map((s) => `«PII-NAME:${s}»`)
const emailArb: fc.Arbitrary<string> = fc
  .string({ maxLength: 20 })
  .map((s) => `«PII-EMAIL:${s}»@pii.invalid`)

interface Identity {
  name: string
  email: string
}

// One placed field with valid-ish normalized geometry referencing one of the
// recipient keys. label/placeholder are sometimes present so we assert they are
// carried over iff defined.
const placedFieldArb: fc.Arbitrary<PlacedFieldLike> = fc.record({
  type: fieldTypeArb,
  page: fc.integer({ min: 1, max: 10 }),
  rect: fc.record({
    positionX: fc.double({ min: 0, max: 95, noNaN: true }),
    positionY: fc.double({ min: 0, max: 95, noNaN: true }),
    width: fc.double({ min: 1, max: 50, noNaN: true }),
    height: fc.double({ min: 1, max: 50, noNaN: true }),
  }),
  recipientKey: fc.constantFrom(...RECIPIENT_KEYS),
  required: fc.boolean(),
  // Strip the PII-marker delimiter so a generated label/placeholder can never
  // accidentally equal a recipient name/email marker (keeps the no-PII
  // assertion sound).
  label: fc.option(
    fc.string().map((s) => s.replace(/[«»]/g, '')),
    { nil: undefined },
  ),
  placeholder: fc.option(
    fc.string().map((s) => s.replace(/[«»]/g, '')),
    { nil: undefined },
  ),
})

// A Field_Set: a (possibly empty) list of placed fields.
const fieldSetArb: fc.Arbitrary<PlacedFieldLike[]> = fc.array(placedFieldArb, {
  minLength: 0,
  maxLength: 14,
})

// A source identity per recipient key — the people the sender assigned the
// fields to. The template must store roles for these recipients, never the
// identities themselves.
const identitiesArb: fc.Arbitrary<Record<number, Identity>> = fc
  .tuple(...RECIPIENT_KEYS.map(() => fc.record({ name: nameArb, email: emailArb })))
  .map((identities) => {
    const map: Record<number, Identity> = {}
    RECIPIENT_KEYS.forEach((key, idx) => {
      map[key] = identities[idx]
    })
    return map
  })

// An optional template name that itself contains no PII.
const nameOptionArb: fc.Arbitrary<string | undefined> = fc.option(
  fc.string({ maxLength: 30 }).map((s) => `tmpl_${s}`),
  { nil: undefined },
)

/* ------------------------------------------------------------------ */
/*  Helpers.                                                           */
/* ------------------------------------------------------------------ */

// Build a complete recipientKey→role mapping that covers every key referenced
// by the Field_Set (and harmlessly covers all keys in the pool). Each recipient
// maps to an abstract role slot derived only from its key — never its identity.
function completeMappingFor(fields: readonly PlacedFieldLike[]): RecipientKeyToRole {
  const map: Record<number, string> = {}
  for (const key of RECIPIENT_KEYS) {
    map[key] = `signer ${key + 1}`
  }
  // Defensive: ensure any out-of-pool key (shouldn't happen) is still covered.
  for (const f of fields) {
    if (!(f.recipientKey in map)) {
      map[f.recipientKey] = `signer ${f.recipientKey + 1}`
    }
  }
  return map
}

/* ------------------------------------------------------------------ */
/*  The property.                                                      */
/* ------------------------------------------------------------------ */

describe('Property 24: Saved templates store roles, never people', () => {
  it('preserves per-field type/page/coords/required/text-meta + a role slot, and leaks no recipient name/email', () => {
    fc.assert(
      fc.property(
        fieldSetArb,
        identitiesArb,
        nameOptionArb,
        (fields, identities, name) => {
          const mapping = completeMappingFor(fields)

          const template = buildTemplate(fields, mapping, { name })

          // ---- Faithful per-field copy + role slot. -------------------
          expect(template.fields.length).toBe(fields.length)

          fields.forEach((field, i) => {
            const tf = template.fields[i]

            // Type, page, required carried over verbatim.
            expect(tf.type).toBe(field.type)
            expect(tf.page).toBe(field.page)
            expect(tf.required).toBe(field.required)

            // Normalized_Coordinates carried over verbatim.
            expect(tf.position_x).toBe(field.rect.positionX)
            expect(tf.position_y).toBe(field.rect.positionY)
            expect(tf.width).toBe(field.rect.width)
            expect(tf.height).toBe(field.rect.height)

            // A Template_Recipient_Role slot is present — the role its
            // recipient maps to, never the recipient's identity.
            expect(tf.template_role).toBe(mapping[field.recipientKey])
            expect(typeof tf.template_role).toBe('string')
            expect(tf.template_role.length).toBeGreaterThan(0)

            // Text metadata carried over iff present on the source field.
            if (field.label !== undefined) {
              expect(tf.label).toBe(field.label)
            } else {
              expect(tf.label).toBeUndefined()
            }
            if (field.placeholder !== undefined) {
              expect(tf.placeholder).toBe(field.placeholder)
            } else {
              expect(tf.placeholder).toBeUndefined()
            }
          })

          // roles[] holds exactly the distinct slots the fields refer to.
          const referencedRoles = new Set(
            fields.map((f) => mapping[f.recipientKey]),
          )
          expect(new Set(template.roles)).toEqual(referencedRoles)

          // ---- No PII anywhere in the serialized form. ----------------
          const serialized = JSON.stringify(template)
          for (const key of RECIPIENT_KEYS) {
            expect(serialized).not.toContain(identities[key].name)
            expect(serialized).not.toContain(identities[key].email)
          }
        },
      ),
      { numRuns: 200 },
    )
  })
})
