import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

import { applyTemplate, type TemplateLike, type RoleToRecipientKey } from './applyTemplate'
import type { PlacedField } from '../hooks/useFieldSet'
import type { TemplateFieldIn, FieldType } from '@/api/esign'

// Feature: esignature-field-placement, Property: Template apply maps roles to recipients
// (design Property 26: Applying a template is faithful and total over roles)
// **Validates: Requirements 17.5, 17.6, 17.8**
//
// A Field_Template stores its fields against abstract Template_Recipient_Role
// slots (e.g. `signer 1`, `viewer`) — never specific people (R17.1). Applying a
// template (R17.5) maps each role onto one of the current send's recipients and
// copies every template field into a fresh PlacedField, carrying its type, page,
// Normalized_Coordinates, required flag, and (for text) label/placeholder, with a
// freshly-generated clientId. The apply is **total over roles** (R17.6): it
// succeeds only when every role the template references is mapped, otherwise it
// fails — naming exactly the de-duplicated set of unmapped roles and producing
// **no** fields, so no applied field is ever left unassigned (feeding the same
// send validation as any hand-placed set, R17.8).
//
// This file holds ONE property with two faces (mapped vs. unmapped) over the same
// generated template, exercised across both an always-complete mapping and a
// possibly-incomplete one so both the ok=true and ok=false branches are hit with
// ≥100 examples.

/* ------------------------------------------------------------------ */
/*  Arbitraries — a template carrying various role slots + a mapping.  */
/* ------------------------------------------------------------------ */

const FIELD_TYPES: readonly FieldType[] = [
  'signature',
  'initials',
  'name',
  'date',
  'email',
  'text',
]

// A small pool of role slot names so a generated template reuses roles (which
// exercises de-duplication of the unmapped-role report) rather than every field
// inventing a unique role.
const ROLE_POOL = ['signer 1', 'signer 2', 'signer 3', 'viewer', 'approver'] as const

const fieldTypeArb: fc.Arbitrary<FieldType> = fc.constantFrom(...FIELD_TYPES)
const roleArb: fc.Arbitrary<string> = fc.constantFrom(...ROLE_POOL)

// One template field with valid-ish normalized geometry and a role slot. label /
// placeholder are sometimes present (as undefined when absent) so we can assert
// they are carried over iff defined.
const templateFieldArb: fc.Arbitrary<TemplateFieldIn> = fc.record({
  type: fieldTypeArb,
  page: fc.integer({ min: 1, max: 10 }),
  position_x: fc.double({ min: 0, max: 95, noNaN: true }),
  position_y: fc.double({ min: 0, max: 95, noNaN: true }),
  width: fc.double({ min: 1, max: 50, noNaN: true }),
  height: fc.double({ min: 1, max: 50, noNaN: true }),
  required: fc.boolean(),
  label: fc.option(fc.string(), { nil: undefined }),
  placeholder: fc.option(fc.string(), { nil: undefined }),
  template_role: roleArb,
})

// A template is just a non-empty list of fields (TemplateLike only needs `fields`).
const templateArb: fc.Arbitrary<TemplateLike> = fc
  .array(templateFieldArb, { minLength: 1, maxLength: 12 })
  .map((fields) => ({ fields }))

// A mapping that maps an arbitrary SUBSET of the role pool to distinct recipient
// keys — sometimes complete, sometimes omitting roles the template uses. Using a
// subset of the whole pool means some examples cover every role the template
// references (ok=true) and others omit one or more (ok=false).
const mappingArb: fc.Arbitrary<RoleToRecipientKey> = fc
  .uniqueArray(roleArb, { minLength: 0, maxLength: ROLE_POOL.length })
  .map((roles) => {
    const map: Record<string, number> = {}
    roles.forEach((role, idx) => {
      map[role] = idx
    })
    return map
  })

// A mapping guaranteed to cover EVERY role in the template, so the ok=true face
// is always reachable regardless of which roles the template happened to use.
function completeMappingFor(template: TemplateLike): RoleToRecipientKey {
  const map: Record<string, number> = {}
  let next = 0
  for (const f of template.fields) {
    if (!(f.template_role in map)) {
      map[f.template_role] = next
      next += 1
    }
  }
  return map
}

// Expected de-duplicated, first-seen-order list of unmapped roles for a template
// under a mapping — mirrors the helper's own contract (the test's oracle).
function expectedUnmapped(template: TemplateLike, mapping: RoleToRecipientKey): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const f of template.fields) {
    const role = f.template_role
    const key = mapping[role]
    const mapped = typeof key === 'number' && Number.isFinite(key)
    if (!mapped && !seen.has(role)) {
      seen.add(role)
      out.push(role)
    }
  }
  return out
}

/* ------------------------------------------------------------------ */
/*  The property.                                                      */
/* ------------------------------------------------------------------ */

describe('Property: Template apply maps roles to recipients (Property 26)', () => {
  it('is faithful when every role is mapped and fails naming the unmapped roles otherwise', () => {
    fc.assert(
      fc.property(templateArb, mappingArb, (template, mapping) => {
        const unmapped = expectedUnmapped(template, mapping)

        // ---- Face A: the supplied (possibly incomplete) mapping. --------
        const result = applyTemplate(template, mapping)

        if (unmapped.length > 0) {
          // R17.6: any unmapped role ⇒ fail, name the de-duplicated set in
          // first-seen order, produce NO fields.
          expect(result.ok).toBe(false)
          if (result.ok) return // type-narrowing for the compiler
          expect(result.unmappedRoles).toEqual(unmapped)
        } else {
          // Every role resolved ⇒ success with one field per template field.
          expect(result.ok).toBe(true)
          if (!result.ok) return
          assertFaithful(template, mapping, result.fields)
        }

        // ---- Face B: a mapping that always covers every role. -----------
        // Guarantees the ok=true branch is exercised on every example so the
        // faithful-copy assertions always run.
        const complete = completeMappingFor(template)
        const ok = applyTemplate(template, complete)
        expect(ok.ok).toBe(true)
        if (!ok.ok) return
        assertFaithful(template, complete, ok.fields)
      }),
      { numRuns: 200 },
    )
  })
})

/**
 * Assert the success-case contract: exactly one placed field per template field,
 * in order, carrying type/page/geometry/required/label/placeholder and assigned
 * to the recipient its role maps to, with pairwise-unique fresh clientIds.
 */
function assertFaithful(
  template: TemplateLike,
  mapping: RoleToRecipientKey,
  fields: PlacedField[],
) {
  // One placed field per template field (R17.5).
  expect(fields.length).toBe(template.fields.length)

  template.fields.forEach((tf, i) => {
    const placed = fields[i]

    // Type, page, and required carried over verbatim.
    expect(placed.type).toBe(tf.type)
    expect(placed.page).toBe(tf.page)
    expect(placed.required).toBe(tf.required)

    // Normalized_Coordinates carried over verbatim (R17.5 / R7 geometry).
    expect(placed.rect.positionX).toBe(tf.position_x)
    expect(placed.rect.positionY).toBe(tf.position_y)
    expect(placed.rect.width).toBe(tf.width)
    expect(placed.rect.height).toBe(tf.height)

    // recipientKey comes from the role mapping (R17.5).
    expect(placed.recipientKey).toBe(mapping[tf.template_role])

    // Text metadata carried over iff present on the template field.
    if (tf.label !== undefined) {
      expect(placed.label).toBe(tf.label)
    } else {
      expect(placed.label).toBeUndefined()
    }
    if (tf.placeholder !== undefined) {
      expect(placed.placeholder).toBe(tf.placeholder)
    } else {
      expect(placed.placeholder).toBeUndefined()
    }
  })

  // Fresh clientIds — present, non-empty, and pairwise unique across the set.
  const ids = fields.map((f) => f.clientId)
  ids.forEach((id) => {
    expect(typeof id).toBe('string')
    expect(id.length).toBeGreaterThan(0)
  })
  expect(new Set(ids).size).toBe(ids.length)
}
