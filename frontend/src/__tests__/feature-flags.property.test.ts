import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  canOverrideFlag,
  groupFlagsByCategory,
  validateFlagCategory,
} from '../utils/featureFlagCalcs'

// Feature: production-readiness-gaps, Property 22: Feature flag override respects can_override
// Feature: production-readiness-gaps, Property 23: Feature flags grouped by category with required fields
// **Validates: Requirements 11.2, 11.3, 11.4**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Generate a non-empty trimmed string for category/key names */
const nonEmptyStringArb = fc
  .string({ minLength: 1, maxLength: 50 })
  .filter((s) => s.trim().length > 0)

/** Generate a category name from a realistic set */
const categoryArb = fc.constantFrom(
  'core',
  'advanced',
  'beta',
  'experimental',
  'Uncategorized',
)

/** Generate a single feature flag with category info */
const flagWithCategoryArb = fc.record({
  category: categoryArb,
  key: nonEmptyStringArb,
  enabled: fc.boolean(),
  can_override: fc.boolean(),
})

/** Generate a list of feature flags */
const flagListArb = fc.array(flagWithCategoryArb, { minLength: 0, maxLength: 30 })

/** Generate a valid flag for validation (non-empty category and key) */
const validFlagForValidationArb = fc.record({
  category: nonEmptyStringArb,
  key: nonEmptyStringArb,
  description: fc.option(fc.string({ maxLength: 100 }), { nil: undefined }),
})

/** Generate whitespace-only or empty strings */
const emptyOrWhitespaceArb = fc.constantFrom('', ' ', '  ', '\t', '\n', '  \t\n  ')

/* ------------------------------------------------------------------ */
/*  Property 22: Feature flag override respects can_override           */
/* ------------------------------------------------------------------ */

describe('Property 22: Feature flag override respects can_override', () => {
  it('returns true when can_override is true', () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        const flag = { can_override: true, enabled }
        expect(canOverrideFlag(flag)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('returns false when can_override is false', () => {
    fc.assert(
      fc.property(fc.boolean(), (enabled) => {
        const flag = { can_override: false, enabled }
        expect(canOverrideFlag(flag)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('result matches the can_override field exactly', () => {
    fc.assert(
      fc.property(fc.boolean(), fc.boolean(), (canOverride, enabled) => {
        const flag = { can_override: canOverride, enabled }
        expect(canOverrideFlag(flag)).toBe(canOverride)
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 23: Feature flags grouped by category with required fields */
/* ------------------------------------------------------------------ */

describe('Property 23: Feature flags grouped by category with required fields', () => {
  it('groups flags by category preserving all flags', () => {
    fc.assert(
      fc.property(flagListArb, (flags) => {
        const grouped = groupFlagsByCategory(flags)
        // Total count across all groups must equal input count
        const totalGrouped = Object.values(grouped).reduce(
          (sum, arr) => sum + arr.length,
          0,
        )
        expect(totalGrouped).toBe(flags.length)
      }),
      { numRuns: 100 },
    )
  })

  it('each flag appears in its own category group', () => {
    fc.assert(
      fc.property(flagListArb, (flags) => {
        const grouped = groupFlagsByCategory(flags)
        for (const flag of flags) {
          const cat = flag.category || 'Uncategorized'
          expect(grouped[cat]).toBeDefined()
          expect(grouped[cat]).toContainEqual(flag)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('no flag appears in a different category group', () => {
    fc.assert(
      fc.property(flagListArb, (flags) => {
        const grouped = groupFlagsByCategory(flags)
        for (const [cat, catFlags] of Object.entries(grouped)) {
          for (const flag of catFlags) {
            const expectedCat = flag.category || 'Uncategorized'
            expect(expectedCat).toBe(cat)
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  it('every grouped flag has required fields: key, enabled, can_override', () => {
    fc.assert(
      fc.property(flagListArb, (flags) => {
        const grouped = groupFlagsByCategory(flags)
        for (const catFlags of Object.values(grouped)) {
          for (const flag of catFlags) {
            expect(flag).toHaveProperty('key')
            expect(flag).toHaveProperty('enabled')
            expect(flag).toHaveProperty('can_override')
            expect(flag).toHaveProperty('category')
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  it('validates flags with non-empty category and key', () => {
    fc.assert(
      fc.property(validFlagForValidationArb, (flag) => {
        expect(validateFlagCategory(flag)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects flags with empty or whitespace-only category', () => {
    fc.assert(
      fc.property(emptyOrWhitespaceArb, nonEmptyStringArb, (category, key) => {
        const flag = { category, key }
        expect(validateFlagCategory(flag)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('rejects flags with empty or whitespace-only key', () => {
    fc.assert(
      fc.property(nonEmptyStringArb, emptyOrWhitespaceArb, (category, key) => {
        const flag = { category, key }
        expect(validateFlagCategory(flag)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('returns empty record for empty flag list', () => {
    const grouped = groupFlagsByCategory([])
    expect(Object.keys(grouped)).toHaveLength(0)
  })
})
