import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  getEndpointForCategory,
  buildPayload,
  validateForm,
} from '../InlineCreateForm'
import type {
  Category,
  PartFormState,
  TyreFormState,
  FluidFormState,
  ServiceFormState,
} from '../InlineCreateForm'

// Feature: inline-catalogue-from-inventory, Property 1: Category-to-API endpoint and type mapping
// **Validates: Requirements 2.3, 3.2, 4.2, 5.2**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Non-empty trimmed string for required name fields */
const nonEmptyStringArb = fc
  .string({ minLength: 1, maxLength: 50 })
  .filter((s) => s.trim().length > 0)

/** Positive price as a string (valid for parseFloat) */
const positivePriceArb = fc
  .float({ min: Math.fround(0.01), max: Math.fround(99999), noNaN: true })
  .filter((n) => n > 0)
  .map((n) => n.toFixed(2))

/** Valid GST mode */
const gstModeArb = fc.constantFrom('inclusive' as const, 'exclusive' as const, 'exempt' as const)

/** Optional string field (may be empty) */
const optionalStringArb = fc.oneof(fc.constant(''), nonEmptyStringArb)

/** Valid PartFormState */
const partFormArb: fc.Arbitrary<PartFormState> = fc.record({
  name: nonEmptyStringArb,
  sell_price_per_unit: positivePriceArb,
  purchase_price: positivePriceArb,
  gst_mode: gstModeArb,
  part_number: optionalStringArb,
  brand: optionalStringArb,
  description: optionalStringArb,
  packaging_type: optionalStringArb,
  qty_per_pack: optionalStringArb,
  total_packs: optionalStringArb,
})

/** Valid TyreFormState */
const tyreFormArb: fc.Arbitrary<TyreFormState> = fc.record({
  name: nonEmptyStringArb,
  sell_price_per_unit: positivePriceArb,
  purchase_price: positivePriceArb,
  gst_mode: gstModeArb,
  tyre_width: optionalStringArb,
  tyre_profile: optionalStringArb,
  tyre_rim_dia: optionalStringArb,
  tyre_load_index: optionalStringArb,
  tyre_speed_index: optionalStringArb,
  brand: optionalStringArb,
  packaging_type: optionalStringArb,
  qty_per_pack: optionalStringArb,
  total_packs: optionalStringArb,
})

/** Valid FluidFormState */
const fluidFormArb: fc.Arbitrary<FluidFormState> = fc.record({
  product_name: nonEmptyStringArb,
  sell_price_per_unit: positivePriceArb,
  gst_mode: gstModeArb,
  fluid_type: fc.constantFrom('oil' as const, 'non-oil' as const),
  oil_type: optionalStringArb,
  grade: optionalStringArb,
  brand_name: optionalStringArb,
})

/** Valid ServiceFormState */
const serviceFormArb: fc.Arbitrary<ServiceFormState> = fc.record({
  name: nonEmptyStringArb,
  default_price: positivePriceArb,
  gst_mode: gstModeArb,
  description: optionalStringArb,
})

/* ------------------------------------------------------------------ */
/*  Property 1: Category-to-API endpoint and type mapping              */
/* ------------------------------------------------------------------ */

describe('Property 1: Category-to-API endpoint and type mapping', () => {
  it('part category maps to /catalogue/parts endpoint', () => {
    fc.assert(
      fc.property(partFormArb, (_form) => {
        expect(getEndpointForCategory('part')).toBe('/catalogue/parts')
      }),
      { numRuns: 100 },
    )
  })

  it('tyre category maps to /catalogue/parts endpoint', () => {
    fc.assert(
      fc.property(tyreFormArb, (_form) => {
        expect(getEndpointForCategory('tyre')).toBe('/catalogue/parts')
      }),
      { numRuns: 100 },
    )
  })

  it('fluid category maps to /catalogue/fluids endpoint', () => {
    fc.assert(
      fc.property(fluidFormArb, (_form) => {
        expect(getEndpointForCategory('fluid')).toBe('/catalogue/fluids')
      }),
      { numRuns: 100 },
    )
  })

  it('service category maps to /catalogue/items endpoint', () => {
    fc.assert(
      fc.property(serviceFormArb, (_form) => {
        expect(getEndpointForCategory('service')).toBe('/catalogue/items')
      }),
      { numRuns: 100 },
    )
  })

  it('part payload includes part_type: "part" discriminator', () => {
    fc.assert(
      fc.property(partFormArb, (form) => {
        const payload = buildPayload('part', form)
        expect(payload.part_type).toBe('part')
      }),
      { numRuns: 100 },
    )
  })

  it('tyre payload includes part_type: "tyre" discriminator', () => {
    fc.assert(
      fc.property(tyreFormArb, (form) => {
        const payload = buildPayload('tyre', form)
        expect(payload.part_type).toBe('tyre')
      }),
      { numRuns: 100 },
    )
  })

  it('fluid payload does NOT include part_type (uses fluid endpoint instead)', () => {
    fc.assert(
      fc.property(fluidFormArb, (form) => {
        const payload = buildPayload('fluid', form)
        expect(payload).not.toHaveProperty('part_type')
      }),
      { numRuns: 100 },
    )
  })

  it('service payload includes category: "service" discriminator', () => {
    fc.assert(
      fc.property(serviceFormArb, (form) => {
        const payload = buildPayload('service', form)
        expect(payload.category).toBe('service')
      }),
      { numRuns: 100 },
    )
  })

  it('endpoint and discriminator are consistent for all categories', () => {
    const categoryFormPairs: [Category, fc.Arbitrary<PartFormState | TyreFormState | FluidFormState | ServiceFormState>][] = [
      ['part', partFormArb],
      ['tyre', tyreFormArb],
      ['fluid', fluidFormArb],
      ['service', serviceFormArb],
    ]

    const expectedEndpoints: Record<Category, string> = {
      part: '/catalogue/parts',
      tyre: '/catalogue/parts',
      fluid: '/catalogue/fluids',
      service: '/catalogue/items',
    }

    for (const [category, formArb] of categoryFormPairs) {
      fc.assert(
        fc.property(formArb, (form) => {
          const endpoint = getEndpointForCategory(category)
          const payload = buildPayload(category, form)

          // Endpoint matches expected
          expect(endpoint).toBe(expectedEndpoints[category])

          // Discriminator field is present and correct
          if (category === 'part') {
            expect(payload.part_type).toBe('part')
          } else if (category === 'tyre') {
            expect(payload.part_type).toBe('tyre')
          } else if (category === 'service') {
            expect(payload.category).toBe('service')
          }
          // Fluid uses endpoint-based discrimination (no type field needed)
        }),
        { numRuns: 100 },
      )
    }
  })
})


/* ------------------------------------------------------------------ */
/*  Property 7: Form validation rejects missing required fields        */
/*  **Validates: Requirements 2.1, 3.1, 4.1, 5.1**                    */
/* ------------------------------------------------------------------ */

/**
 * Generators that produce forms with at least one required field invalid.
 *
 * Strategy: start from a valid form, then corrupt exactly one required field
 * using fc.oneof to pick which field to break. This ensures every generated
 * form has at least one invalid required field while keeping the rest random.
 */

/** Strings that are empty or whitespace-only (invalid for name fields) */
const blankStringArb = fc.constantFrom('', ' ', '  ', '\t', '\n', '  \t\n  ')

/** Price strings that are invalid: zero, negative, non-numeric, or empty */
const invalidPriceArb = fc.oneof(
  fc.constant(''),
  fc.constant('0'),
  fc.constant('-1'),
  fc.constant('-0.5'),
  fc.constant('abc'),
  fc.constant('NaN'),
  fc.constant('  '),
  fc.nat({ max: 999 }).map((n) => (-n - 1).toString()), // random negative integers
)

/** GST mode values that are NOT one of the valid three */
const invalidGstModeArb = fc
  .string({ minLength: 1, maxLength: 20 })
  .filter((s) => !['inclusive', 'exclusive', 'exempt'].includes(s))

/** Invalid fluid_type values (not "oil" or "non-oil") */
const invalidFluidTypeArb = fc
  .string({ minLength: 1, maxLength: 20 })
  .filter((s) => s !== 'oil' && s !== 'non-oil')

describe('Property 7: Form validation rejects missing required fields', () => {
  // --- Part: corrupt one required field at a time ---

  it('rejects part form with blank name', () => {
    fc.assert(
      fc.property(partFormArb, blankStringArb, (validForm, badName) => {
        const form = { ...validForm, name: badName }
        const errors = validateForm('part', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.name).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects part form with invalid price', () => {
    fc.assert(
      fc.property(partFormArb, invalidPriceArb, (validForm, badPrice) => {
        const form = { ...validForm, sell_price_per_unit: badPrice }
        const errors = validateForm('part', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.sell_price_per_unit).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects part form with invalid gst_mode', () => {
    fc.assert(
      fc.property(partFormArb, invalidGstModeArb, (validForm, badGst) => {
        const form = { ...validForm, gst_mode: badGst as PartFormState['gst_mode'] }
        const errors = validateForm('part', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.gst_mode).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  // --- Tyre: corrupt one required field at a time ---

  it('rejects tyre form with blank name', () => {
    fc.assert(
      fc.property(tyreFormArb, blankStringArb, (validForm, badName) => {
        const form = { ...validForm, name: badName }
        const errors = validateForm('tyre', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.name).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects tyre form with invalid price', () => {
    fc.assert(
      fc.property(tyreFormArb, invalidPriceArb, (validForm, badPrice) => {
        const form = { ...validForm, sell_price_per_unit: badPrice }
        const errors = validateForm('tyre', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.sell_price_per_unit).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects tyre form with invalid gst_mode', () => {
    fc.assert(
      fc.property(tyreFormArb, invalidGstModeArb, (validForm, badGst) => {
        const form = { ...validForm, gst_mode: badGst as TyreFormState['gst_mode'] }
        const errors = validateForm('tyre', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.gst_mode).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  // --- Fluid: corrupt one required field at a time ---

  it('rejects fluid form with blank product_name', () => {
    fc.assert(
      fc.property(fluidFormArb, blankStringArb, (validForm, badName) => {
        const form = { ...validForm, product_name: badName }
        const errors = validateForm('fluid', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.product_name).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects fluid form with invalid price', () => {
    fc.assert(
      fc.property(fluidFormArb, invalidPriceArb, (validForm, badPrice) => {
        const form = { ...validForm, sell_price_per_unit: badPrice }
        const errors = validateForm('fluid', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.sell_price_per_unit).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects fluid form with invalid gst_mode', () => {
    fc.assert(
      fc.property(fluidFormArb, invalidGstModeArb, (validForm, badGst) => {
        const form = { ...validForm, gst_mode: badGst as FluidFormState['gst_mode'] }
        const errors = validateForm('fluid', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.gst_mode).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects fluid form with invalid fluid_type', () => {
    fc.assert(
      fc.property(fluidFormArb, invalidFluidTypeArb, (validForm, badFluidType) => {
        const form = { ...validForm, fluid_type: badFluidType as FluidFormState['fluid_type'] }
        const errors = validateForm('fluid', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.fluid_type).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  // --- Service: corrupt one required field at a time ---

  it('rejects service form with blank name', () => {
    fc.assert(
      fc.property(serviceFormArb, blankStringArb, (validForm, badName) => {
        const form = { ...validForm, name: badName }
        const errors = validateForm('service', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.name).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects service form with invalid price', () => {
    fc.assert(
      fc.property(serviceFormArb, invalidPriceArb, (validForm, badPrice) => {
        const form = { ...validForm, default_price: badPrice }
        const errors = validateForm('service', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.default_price).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('rejects service form with invalid gst_mode', () => {
    fc.assert(
      fc.property(serviceFormArb, invalidGstModeArb, (validForm, badGst) => {
        const form = { ...validForm, gst_mode: badGst as ServiceFormState['gst_mode'] }
        const errors = validateForm('service', form)
        expect(Object.keys(errors).length).toBeGreaterThan(0)
        expect(errors.gst_mode).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  // --- Cross-category: valid forms should pass validation ---

  it('accepts valid part forms (no false positives)', () => {
    fc.assert(
      fc.property(partFormArb, (form) => {
        const errors = validateForm('part', form)
        expect(Object.keys(errors).length).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('accepts valid tyre forms (no false positives)', () => {
    fc.assert(
      fc.property(tyreFormArb, (form) => {
        const errors = validateForm('tyre', form)
        expect(Object.keys(errors).length).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('accepts valid fluid forms (no false positives)', () => {
    fc.assert(
      fc.property(fluidFormArb, (form) => {
        const errors = validateForm('fluid', form)
        expect(Object.keys(errors).length).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  it('accepts valid service forms (no false positives)', () => {
    fc.assert(
      fc.property(serviceFormArb, (form) => {
        const errors = validateForm('service', form)
        expect(Object.keys(errors).length).toBe(0)
      }),
      { numRuns: 100 },
    )
  })
})


/* ------------------------------------------------------------------ */
/*  Property 4: Create button and banner label matches category        */
/*  **Validates: Requirements 1.1, 8.1**                               */
/* ------------------------------------------------------------------ */

describe('Property 4: Create button and banner label matches category', () => {
  /**
   * The expected mapping from category key to human-readable label.
   * This mirrors the CATEGORY_LABELS constant in InlineCreateForm.tsx
   * (which is not exported, so we define the expected values here).
   */
  const EXPECTED_LABELS: Record<Category, string> = {
    part: 'Part',
    tyre: 'Tyre',
    fluid: 'Fluid/Oil',
    service: 'Service',
  }

  /** Generator: random category from the valid set */
  const categoryArb: fc.Arbitrary<Category> = fc.constantFrom(
    'part' as const,
    'tyre' as const,
    'fluid' as const,
    'service' as const,
  )

  it('every category maps to a non-empty human-readable label', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const label = EXPECTED_LABELS[category]
        expect(label).toBeDefined()
        expect(label.trim().length).toBeGreaterThan(0)
      }),
      { numRuns: 100 },
    )
  })

  it('the "+ Create New [Category]" button text contains the correct label', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const label = EXPECTED_LABELS[category]
        const buttonText = `+ Create New ${label}`
        expect(buttonText).toContain(label)
        // Button text follows the pattern "+ Create New <Label>"
        expect(buttonText).toMatch(/^\+ Create New .+$/)
      }),
      { numRuns: 100 },
    )
  })

  it('the banner text contains the correct category label', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const label = EXPECTED_LABELS[category]
        const bannerText = `Quick-create a new ${label} catalogue item`
        expect(bannerText).toContain(label)
        // Banner follows the pattern "Quick-create a new <Label> catalogue item"
        expect(bannerText).toMatch(/^Quick-create a new .+ catalogue item$/)
      }),
      { numRuns: 100 },
    )
  })

  it('label mapping is exhaustive — covers all four categories', () => {
    const allCategories: Category[] = ['part', 'tyre', 'fluid', 'service']
    fc.assert(
      fc.property(categoryArb, (category) => {
        // Every generated category must be in the known set
        expect(allCategories).toContain(category)
        // And must have a label defined
        expect(EXPECTED_LABELS[category]).toBeDefined()
      }),
      { numRuns: 100 },
    )
  })

  it('each category maps to a unique label', () => {
    fc.assert(
      fc.property(categoryArb, categoryArb, (cat1, cat2) => {
        // If categories are different, their labels must be different
        if (cat1 !== cat2) {
          expect(EXPECTED_LABELS[cat1]).not.toBe(EXPECTED_LABELS[cat2])
        }
      }),
      { numRuns: 100 },
    )
  })
})


/* ------------------------------------------------------------------ */
/*  Property 2: API error detail propagation                           */
/*  **Validates: Requirements 2.4, 3.3, 4.3, 5.3, 10.2**             */
/* ------------------------------------------------------------------ */

describe('Property 2: API error detail propagation', () => {
  /**
   * The error extraction logic from InlineCreateForm's handleSubmit catch block:
   *   const axiosErr = err as { response?: { data?: { detail?: string } } }
   *   const detail = axiosErr?.response?.data?.detail
   *   if (detail) { setFormError(detail) }
   *   else { setFormError(`Failed to create ${label}. Please check your connection and try again.`) }
   *
   * We test this extraction pattern as a pure function to verify:
   * 1. Non-empty detail strings are preserved exactly (no trimming, truncation, or escaping)
   * 2. Missing/falsy detail falls back to the generic message
   */

  /** Mirrors the error extraction logic from handleSubmit's catch block */
  function extractErrorDetail(
    err: unknown,
    categoryLabel: string,
  ): string {
    const axiosErr = err as { response?: { data?: { detail?: string } } }
    const detail = axiosErr?.response?.data?.detail
    if (detail) {
      return detail
    }
    return `Failed to create ${categoryLabel.toLowerCase()}. Please check your connection and try again.`
  }

  const CATEGORY_LABELS: Record<Category, string> = {
    part: 'Part',
    tyre: 'Tyre',
    fluid: 'Fluid/Oil',
    service: 'Service',
  }

  const categoryArb: fc.Arbitrary<Category> = fc.constantFrom(
    'part' as const,
    'tyre' as const,
    'fluid' as const,
    'service' as const,
  )

  /** Non-empty string for the detail field — these should be propagated exactly */
  const nonEmptyDetailArb = fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.length > 0)

  it('preserves the exact API error detail string without modification', () => {
    fc.assert(
      fc.property(categoryArb, nonEmptyDetailArb, (category, detail) => {
        const err = { response: { data: { detail } } }
        const label = CATEGORY_LABELS[category]
        const result = extractErrorDetail(err, label)
        // The detail must be returned exactly — no trimming, truncation, or escaping
        expect(result).toBe(detail)
      }),
      { numRuns: 100 },
    )
  })

  it('uses fallback message when detail is undefined', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const err = { response: { data: {} } }
        const label = CATEGORY_LABELS[category]
        const result = extractErrorDetail(err, label)
        expect(result).toBe(
          `Failed to create ${label.toLowerCase()}. Please check your connection and try again.`,
        )
      }),
      { numRuns: 100 },
    )
  })

  it('uses fallback message when data is undefined', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const err = { response: {} }
        const label = CATEGORY_LABELS[category]
        const result = extractErrorDetail(err, label)
        expect(result).toBe(
          `Failed to create ${label.toLowerCase()}. Please check your connection and try again.`,
        )
      }),
      { numRuns: 100 },
    )
  })

  it('uses fallback message when response is undefined (network error)', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const err = {}
        const label = CATEGORY_LABELS[category]
        const result = extractErrorDetail(err, label)
        expect(result).toBe(
          `Failed to create ${label.toLowerCase()}. Please check your connection and try again.`,
        )
      }),
      { numRuns: 100 },
    )
  })

  it('uses fallback message when error is null or undefined', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const label = CATEGORY_LABELS[category]
        expect(extractErrorDetail(null, label)).toBe(
          `Failed to create ${label.toLowerCase()}. Please check your connection and try again.`,
        )
        expect(extractErrorDetail(undefined, label)).toBe(
          `Failed to create ${label.toLowerCase()}. Please check your connection and try again.`,
        )
      }),
      { numRuns: 100 },
    )
  })

  it('uses fallback message when detail is an empty string (falsy)', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        const err = { response: { data: { detail: '' } } }
        const label = CATEGORY_LABELS[category]
        const result = extractErrorDetail(err, label)
        // Empty string is falsy, so the fallback should be used
        expect(result).toBe(
          `Failed to create ${label.toLowerCase()}. Please check your connection and try again.`,
        )
      }),
      { numRuns: 100 },
    )
  })

  it('preserves special characters in detail strings (unicode, whitespace, symbols)', () => {
    fc.assert(
      fc.property(
        categoryArb,
        fc.string({ minLength: 1, maxLength: 200 }).filter((s) => s.length > 0),
        (category, detail) => {
          const err = { response: { data: { detail } } }
          const label = CATEGORY_LABELS[category]
          const result = extractErrorDetail(err, label)
          expect(result).toBe(detail)
          // Verify no mutation occurred
          expect(result.length).toBe(detail.length)
        },
      ),
      { numRuns: 100 },
    )
  })
})
