// Feature: esignature-field-placement, Property 23 (parity): shared pure core behaves identically across web and mobile
// **Validates: Requirements 16.9**

/**
 * Parity test for the duplicated e-sign pure core (task 23.2).
 *
 * Task 23.1 chose **verbatim duplication** over a shared `@shared/esign/`
 * package (frontend-v2 is deliberately self-contained — see
 * `mobile/src/lib/esign/index.ts` for the rationale). Because the modules are
 * copies rather than a single shared instance, this test asserts — over
 * generated inputs — that the **web** and **mobile** copies of the pure core
 * produce byte-identical results:
 *
 *   - `coordinateMapping`: `overlayToNormalized`, `normalizedToOverlay`, `clampToPage`
 *   - `dependencyGraph`:   `addDependency`, `isAcyclic`
 *   - `fieldValidation`:   `validateFieldSet`
 *
 * Approach: the mobile copies are imported via the local relative path; the web
 * (canonical) copies are imported via a relative path reaching into
 * `frontend-v2/` (resolvable under mobile's vitest — the same mechanism the
 * repo already uses for the `@email-contract` alias into frontend-v2). The web
 * `fieldValidation.ts` pulls `FIELD_TYPES` from the editor's `useFieldSet` hook
 * (React + coordinateMapping only) and a *type-only* `SigningRole` from
 * `@/api/esign` (erased at compile time), so it loads cleanly here.
 *
 * Generators deliberately exercise the edge cases called out by the task:
 * out-of-bounds rects, self-loops, cycles, signers without a signature field,
 * viewers, and varied (non-square, differing) page dimensions.
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// --- mobile (local) copies ----------------------------------------------------
import * as mobCoord from './coordinateMapping'
import * as mobDep from './dependencyGraph'
import { validateFieldSet as mobValidate } from './fieldValidation'
import type { FieldValidationRecipient } from './fieldValidation'
import type { PlacedField } from './fieldSetTypes'

// --- web (canonical) copies, reaching into frontend-v2 ------------------------
import * as webCoord from '../../../../frontend-v2/src/components/esign/fieldplacement/lib/coordinateMapping'
import * as webDep from '../../../../frontend-v2/src/components/esign/lib/dependencyGraph'
import { validateFieldSet as webValidate } from '../../../../frontend-v2/src/components/esign/fieldplacement/lib/fieldValidation'

const RUNS = 200

// -----------------------------------------------------------------------------
// Arbitraries
// -----------------------------------------------------------------------------

const finite = (min: number, max: number) =>
  fc.double({ min, max, noNaN: true, noDefaultInfinity: true })

/** Strictly-positive page dimensions (precondition of the transforms). */
const posDim = fc.double({ min: 1, max: 3000, noNaN: true, noDefaultInfinity: true })

/** Page dims, including non-square / differing widths and heights. */
const pageDimsArb = fc.record({ cssWidth: posDim, cssHeight: posDim })

/** Overlay rect, allowed to go out of bounds (negative / oversized). */
const overlayRectArb = fc.record({
  xPx: finite(-1000, 3000),
  yPx: finite(-1000, 3000),
  wPx: finite(-200, 4000),
  hPx: finite(-200, 4000),
})

/** Normalized rect, allowed to exceed [0,100] so inverse/round-trip is exercised. */
const normalizedRectArb = fc.record({
  positionX: finite(-50, 150),
  positionY: finite(-50, 150),
  width: finite(-50, 150),
  height: finite(-50, 150),
})

// dependencyGraph arbitraries ---------------------------------------------------

/** Small id pool so self-loops and cycles actually form. */
const clientIdArb = fc.constantFrom('a', 'b', 'c', 'd', 'e')

const conditionArb = fc.constantFrom(
  'is_checked',
  'is_not_checked',
  'equals',
  'not_equals',
  'is_filled',
  'is_empty',
)
const effectArb = fc.constantFrom('show', 'require')

const dependencyArb = fc.record(
  {
    dependentClientId: clientIdArb,
    triggerClientId: clientIdArb,
    condition: conditionArb,
    effect: effectArb,
    value: fc.option(fc.string(), { nil: undefined }),
  },
  { requiredKeys: ['dependentClientId', 'triggerClientId', 'condition', 'effect'] },
) as fc.Arbitrary<webDep.FieldDependency>

const depsArb = fc.array(dependencyArb, { maxLength: 8 })

// fieldValidation arbitraries ---------------------------------------------------

/** Field types incl. an unsupported value to exercise the invalid-type path. */
const fieldTypeArb = fc.constantFrom(
  'signature',
  'initials',
  'name',
  'date',
  'email',
  'text',
  'bogus', // unsupported on purpose
)

const placedFieldArb = fc.record(
  {
    clientId: fc.constantFrom('f1', 'f2', 'f3', 'f4', 'f5'),
    type: fieldTypeArb,
    page: fc.integer({ min: 1, max: 5 }),
    rect: fc.record({
      // allow out-of-bounds + non-positive sizes
      positionX: finite(-10, 110),
      positionY: finite(-10, 110),
      width: finite(-10, 120),
      height: finite(-10, 120),
    }),
    recipientKey: fc.integer({ min: 0, max: 4 }),
    required: fc.boolean(),
    label: fc.option(fc.string(), { nil: undefined }),
    placeholder: fc.option(fc.string(), { nil: undefined }),
  },
  { requiredKeys: ['clientId', 'type', 'page', 'rect', 'recipientKey', 'required'] },
) as fc.Arbitrary<PlacedField>

const recipientArb = fc.record(
  {
    key: fc.integer({ min: 0, max: 4 }),
    signing_role: fc.constantFrom('signer', 'viewer'),
    name: fc.option(fc.string(), { nil: undefined }),
    email: fc.option(fc.string(), { nil: undefined }),
  },
  { requiredKeys: ['key', 'signing_role'] },
) as fc.Arbitrary<FieldValidationRecipient>

// -----------------------------------------------------------------------------
// Parity properties
// -----------------------------------------------------------------------------

describe('Property 23 (parity): web and mobile pure cores behave identically', () => {
  it('coordinateMapping.overlayToNormalized is identical across copies', () => {
    fc.assert(
      fc.property(overlayRectArb, pageDimsArb, (rect, dims) => {
        expect(mobCoord.overlayToNormalized(rect, dims)).toEqual(
          webCoord.overlayToNormalized(rect, dims),
        )
      }),
      { numRuns: RUNS },
    )
  })

  it('coordinateMapping.normalizedToOverlay is identical across copies', () => {
    fc.assert(
      fc.property(normalizedRectArb, pageDimsArb, (rect, dims) => {
        expect(mobCoord.normalizedToOverlay(rect, dims)).toEqual(
          webCoord.normalizedToOverlay(rect, dims),
        )
      }),
      { numRuns: RUNS },
    )
  })

  it('coordinateMapping.clampToPage is identical across copies (incl. out-of-bounds)', () => {
    fc.assert(
      fc.property(
        overlayRectArb,
        pageDimsArb,
        finite(0, 200),
        finite(0, 200),
        (rect, dims, minW, minH) => {
          expect(mobCoord.clampToPage(rect, dims, minW, minH)).toEqual(
            webCoord.clampToPage(rect, dims, minW, minH),
          )
        },
      ),
      { numRuns: RUNS },
    )
  })

  it('dependencyGraph.addDependency is identical across copies (incl. self-loops & cycles)', () => {
    fc.assert(
      fc.property(depsArb, dependencyArb, (deps, edge) => {
        expect(mobDep.addDependency(deps, edge)).toEqual(webDep.addDependency(deps, edge))
      }),
      { numRuns: RUNS },
    )
  })

  it('dependencyGraph.isAcyclic is identical across copies', () => {
    fc.assert(
      fc.property(depsArb, (deps) => {
        expect(mobDep.isAcyclic(deps)).toEqual(webDep.isAcyclic(deps))
      }),
      { numRuns: RUNS },
    )
  })

  it('fieldValidation.validateFieldSet is identical across copies (signers/viewers, OOB, missing-signature)', () => {
    fc.assert(
      fc.property(
        fc.array(placedFieldArb, { maxLength: 8 }),
        fc.array(recipientArb, { maxLength: 5 }),
        (fields, recipients) => {
          expect(mobValidate(fields, recipients)).toEqual(webValidate(fields, recipients))
        },
      ),
      { numRuns: RUNS },
    )
  })
})
