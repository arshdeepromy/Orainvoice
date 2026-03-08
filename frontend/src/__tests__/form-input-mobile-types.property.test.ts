import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { getInputAttributes, type FormFieldType } from '@/utils/formInputTypes'

// Feature: production-readiness-gaps, Property 36: Form inputs use correct mobile input types
// **Validates: Requirements 19.7**

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

const allFieldTypes: FormFieldType[] = ['phone', 'email', 'currency', 'numeric', 'text']

const fieldTypeArb: fc.Arbitrary<FormFieldType> = fc.constantFrom(...allFieldTypes)

/* ------------------------------------------------------------------ */
/*  Expected mappings                                                  */
/* ------------------------------------------------------------------ */

const expectedMappings: Record<FormFieldType, { type: string; inputMode?: string }> = {
  phone: { type: 'tel' },
  email: { type: 'email' },
  currency: { type: 'text', inputMode: 'numeric' },
  numeric: { type: 'text', inputMode: 'numeric' },
  text: { type: 'text' },
}

/* ------------------------------------------------------------------ */
/*  Property 36: Form inputs use correct mobile input types            */
/* ------------------------------------------------------------------ */

describe('Property 36: Form inputs use correct mobile input types', () => {
  it('returns the correct type attribute for any form field type', () => {
    fc.assert(
      fc.property(fieldTypeArb, (fieldType) => {
        const attrs = getInputAttributes(fieldType)
        expect(attrs.type).toBe(expectedMappings[fieldType].type)
      }),
      { numRuns: 100 },
    )
  })

  it('returns the correct inputMode attribute for any form field type', () => {
    fc.assert(
      fc.property(fieldTypeArb, (fieldType) => {
        const attrs = getInputAttributes(fieldType)
        const expectedInputMode = expectedMappings[fieldType].inputMode
        if (expectedInputMode) {
          expect(attrs.inputMode).toBe(expectedInputMode)
        } else {
          expect(attrs.inputMode).toBeUndefined()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('phone fields always have type="tel" to trigger phone dialer', () => {
    fc.assert(
      fc.property(fc.constant('phone' as FormFieldType), (fieldType) => {
        const attrs = getInputAttributes(fieldType)
        expect(attrs.type).toBe('tel')
        expect(attrs.inputMode).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('email fields always have type="email" to trigger email keyboard', () => {
    fc.assert(
      fc.property(fc.constant('email' as FormFieldType), (fieldType) => {
        const attrs = getInputAttributes(fieldType)
        expect(attrs.type).toBe('email')
        expect(attrs.inputMode).toBeUndefined()
      }),
      { numRuns: 100 },
    )
  })

  it('currency and numeric fields always have inputmode="numeric" for numeric keyboard', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('currency' as FormFieldType, 'numeric' as FormFieldType),
        (fieldType) => {
          const attrs = getInputAttributes(fieldType)
          expect(attrs.inputMode).toBe('numeric')
        },
      ),
      { numRuns: 100 },
    )
  })

  it('all field types return a non-empty type attribute', () => {
    fc.assert(
      fc.property(fieldTypeArb, (fieldType) => {
        const attrs = getInputAttributes(fieldType)
        expect(attrs.type).toBeTruthy()
        expect(typeof attrs.type).toBe('string')
        expect(attrs.type.length).toBeGreaterThan(0)
      }),
      { numRuns: 100 },
    )
  })

  it('the mapping is exhaustive — every FormFieldType has a defined mapping', () => {
    fc.assert(
      fc.property(fieldTypeArb, (fieldType) => {
        const attrs = getInputAttributes(fieldType)
        // Should never return undefined — the function handles all cases
        expect(attrs).toBeDefined()
        expect(attrs.type).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })
})
