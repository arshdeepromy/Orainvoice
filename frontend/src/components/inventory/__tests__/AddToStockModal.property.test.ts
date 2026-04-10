import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { isCategoryVisibleForTradeFamily } from '../AddToStockModal'

// Feature: inline-catalogue-from-inventory, Property 3: Trade family gating of create button
// **Validates: Requirements 1.4**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Trade family generator: known values, null, undefined, and random strings */
const tradeFamilyArb: fc.Arbitrary<string | null | undefined> = fc.oneof(
  fc.constantFrom<string | null | undefined>(
    'automotive-transport',
    'electrical',
    'plumbing',
    'construction',
    null,
    undefined,
  ),
  fc.string({ minLength: 1, maxLength: 30 }),
)

/** Non-automotive trade family: any string that is NOT 'automotive-transport', and not null/undefined */
const nonAutomotiveTradeFamilyArb: fc.Arbitrary<string> = fc.oneof(
  fc.constantFrom('electrical', 'plumbing', 'construction'),
  fc.string({ minLength: 1, maxLength: 30 }).filter(
    (s) => s !== 'automotive-transport',
  ),
)

/** Category generator from the valid set */
const categoryArb = fc.constantFrom('part', 'tyre', 'fluid')

/* ------------------------------------------------------------------ */
/*  Property 3: Trade family gating of create button                   */
/* ------------------------------------------------------------------ */

describe('Property 3: Trade family gating of create button', () => {
  it('parts are ALWAYS visible regardless of trade family', () => {
    fc.assert(
      fc.property(tradeFamilyArb, (tradeFamily) => {
        expect(isCategoryVisibleForTradeFamily('part', tradeFamily)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('tyres are visible ONLY when tradeFamily is automotive-transport or null/undefined', () => {
    fc.assert(
      fc.property(tradeFamilyArb, (tradeFamily) => {
        const result = isCategoryVisibleForTradeFamily('tyre', tradeFamily)
        const shouldBeVisible =
          tradeFamily === 'automotive-transport' ||
          tradeFamily === null ||
          tradeFamily === undefined
        expect(result).toBe(shouldBeVisible)
      }),
      { numRuns: 100 },
    )
  })

  it('fluids are visible ONLY when tradeFamily is automotive-transport or null/undefined', () => {
    fc.assert(
      fc.property(tradeFamilyArb, (tradeFamily) => {
        const result = isCategoryVisibleForTradeFamily('fluid', tradeFamily)
        const shouldBeVisible =
          tradeFamily === 'automotive-transport' ||
          tradeFamily === null ||
          tradeFamily === undefined
        expect(result).toBe(shouldBeVisible)
      }),
      { numRuns: 100 },
    )
  })

  it('for non-automotive trade families, tyres and fluids are NOT visible', () => {
    fc.assert(
      fc.property(nonAutomotiveTradeFamilyArb, (tradeFamily) => {
        expect(isCategoryVisibleForTradeFamily('tyre', tradeFamily)).toBe(false)
        expect(isCategoryVisibleForTradeFamily('fluid', tradeFamily)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('for automotive-transport, all categories are visible', () => {
    fc.assert(
      fc.property(categoryArb, (category) => {
        expect(
          isCategoryVisibleForTradeFamily(category, 'automotive-transport'),
        ).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('for null/undefined tradeFamily, all categories are visible (defaults to automotive)', () => {
    fc.assert(
      fc.property(
        categoryArb,
        fc.constantFrom<null | undefined>(null, undefined),
        (category, tradeFamily) => {
          expect(
            isCategoryVisibleForTradeFamily(category, tradeFamily),
          ).toBe(true)
        },
      ),
      { numRuns: 100 },
    )
  })
})

import { mapResponseToCatalogueItem } from '../InlineCreateForm'
import type { Category } from '../InlineCreateForm'

// Feature: inline-catalogue-from-inventory, Property 5: Successful inline creation advances to stock details
// **Validates: Requirements 6.1**

/* ------------------------------------------------------------------ */
/*  Generators for random API responses per category                   */
/* ------------------------------------------------------------------ */

/** Random UUID-like string (non-empty) */
const uuidArb = fc.uuid()

/** Random non-empty string for name fields */
const nameArb = fc
  .string({ minLength: 1, maxLength: 60 })
  .filter((s) => s.trim().length > 0)

/** Optional string or null */
const optionalStringArb = fc.oneof(fc.constant(null), fc.string({ minLength: 1, maxLength: 40 }))

/** Optional positive number or null */
const optionalNumberArb = fc.oneof(fc.constant(null), fc.float({ min: Math.fround(0.01), max: Math.fround(99999), noNaN: true }))

/**
 * Parts/Tyres API response shape: { part: { id, name, ... } }
 */
const partResponseArb = fc.record({
  part: fc.record({
    id: uuidArb,
    name: nameArb,
    part_number: optionalStringArb,
    brand: optionalStringArb,
    sell_price_per_unit: optionalNumberArb,
    part_type: fc.constantFrom('part', 'tyre'),
    description: optionalStringArb,
    tyre_width: optionalStringArb,
    tyre_profile: optionalStringArb,
    tyre_rim_dia: optionalStringArb,
    category_name: optionalStringArb,
  }),
})

/**
 * Fluids API response shape: { product: { id, product_name, ... } }
 */
const fluidResponseArb = fc.record({
  product: fc.record({
    id: uuidArb,
    product_name: nameArb,
    brand_name: optionalStringArb,
    sell_price_per_unit: optionalNumberArb,
    fluid_type: fc.constantFrom('oil', 'non-oil'),
    oil_type: optionalStringArb,
    grade: optionalStringArb,
    description: optionalStringArb,
    pack_size: optionalStringArb,
  }),
})

/**
 * Services API response shape: { item: { id, name, ... } }
 */
const serviceResponseArb = fc.record({
  item: fc.record({
    id: uuidArb,
    name: nameArb,
    default_price: optionalNumberArb,
    description: optionalStringArb,
  }),
})

/* ------------------------------------------------------------------ */
/*  Property 5: Successful creation advances to stock details          */
/* ------------------------------------------------------------------ */

describe('Property 5: Successful inline creation advances to stock details', () => {
  it('mapResponseToCatalogueItem extracts non-empty id from part responses', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('part', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.part.id)
        expect(item.id.length).toBeGreaterThan(0)
      }),
      { numRuns: 100 },
    )
  })

  it('mapResponseToCatalogueItem extracts non-empty id from tyre responses', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('tyre', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.part.id)
        expect(item.id.length).toBeGreaterThan(0)
      }),
      { numRuns: 100 },
    )
  })

  it('mapResponseToCatalogueItem extracts non-empty id from fluid responses', () => {
    fc.assert(
      fc.property(fluidResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('fluid', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.product.id)
        expect(item.id.length).toBeGreaterThan(0)
      }),
      { numRuns: 100 },
    )
  })

  it('mapResponseToCatalogueItem extracts non-empty id from service responses', () => {
    fc.assert(
      fc.property(serviceResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('service', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.item.id)
        expect(item.id.length).toBeGreaterThan(0)
      }),
      { numRuns: 100 },
    )
  })

  it('mapped item id matches response id for all categories', () => {
    const categoryResponsePairs: [Category, fc.Arbitrary<Record<string, unknown>>][] = [
      ['part', partResponseArb as fc.Arbitrary<Record<string, unknown>>],
      ['tyre', partResponseArb as fc.Arbitrary<Record<string, unknown>>],
      ['fluid', fluidResponseArb as fc.Arbitrary<Record<string, unknown>>],
      ['service', serviceResponseArb as fc.Arbitrary<Record<string, unknown>>],
    ]

    const idExtractors: Record<Category, (resp: Record<string, unknown>) => string> = {
      part: (r) => (r.part as Record<string, unknown>).id as string,
      tyre: (r) => (r.part as Record<string, unknown>).id as string,
      fluid: (r) => (r.product as Record<string, unknown>).id as string,
      service: (r) => (r.item as Record<string, unknown>).id as string,
    }

    for (const [category, responseArb] of categoryResponsePairs) {
      fc.assert(
        fc.property(responseArb, (response) => {
          const item = mapResponseToCatalogueItem(category, response)
          const expectedId = idExtractors[category](response)
          expect(item.id).toBe(expectedId)
          expect(item.id.length).toBeGreaterThan(0)
        }),
        { numRuns: 100 },
      )
    }
  })
})


// Feature: inline-catalogue-from-inventory, Property 6: Response-to-CatalogueItem mapping consistency
// **Validates: Requirements 6.2**

/* ------------------------------------------------------------------ */
/*  Property 6: Inline-created item populates stock form identically   */
/* ------------------------------------------------------------------ */

describe('Property 6: Inline-created item populates stock form identically', () => {
  it('parts: name maps from response.part.name', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('part', response as unknown as Record<string, unknown>)
        expect(item.name).toBe(response.part.name)
      }),
      { numRuns: 100 },
    )
  })

  it('parts: sell_price maps from response.part.sell_price_per_unit', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('part', response as unknown as Record<string, unknown>)
        if (response.part.sell_price_per_unit != null) {
          expect(item.sell_price).toBe(String(response.part.sell_price_per_unit))
        } else if (response.part.sell_price_per_unit == null) {
          // Falls back to default_price or null — sell_price should still be defined
          expect(item.sell_price === null || typeof item.sell_price === 'string').toBe(true)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('parts: brand maps from response.part.brand', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('part', response as unknown as Record<string, unknown>)
        if (response.part.brand != null) {
          expect(item.brand).toBe(String(response.part.brand))
        } else {
          expect(item.brand).toBeNull()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('parts: part_type is set from response', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('part', response as unknown as Record<string, unknown>)
        expect(item.part_type).toBe(String(response.part.part_type))
      }),
      { numRuns: 100 },
    )
  })

  it('tyres: name maps from response.part.name', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('tyre', response as unknown as Record<string, unknown>)
        expect(item.name).toBe(response.part.name)
      }),
      { numRuns: 100 },
    )
  })

  it('tyres: sell_price maps from response.part.sell_price_per_unit', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('tyre', response as unknown as Record<string, unknown>)
        if (response.part.sell_price_per_unit != null) {
          expect(item.sell_price).toBe(String(response.part.sell_price_per_unit))
        } else {
          expect(item.sell_price === null || typeof item.sell_price === 'string').toBe(true)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('tyres: brand maps from response.part.brand', () => {
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('tyre', response as unknown as Record<string, unknown>)
        if (response.part.brand != null) {
          expect(item.brand).toBe(String(response.part.brand))
        } else {
          expect(item.brand).toBeNull()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('fluids: name maps from response.product.product_name', () => {
    fc.assert(
      fc.property(fluidResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('fluid', response as unknown as Record<string, unknown>)
        expect(item.name).toBe(response.product.product_name)
      }),
      { numRuns: 100 },
    )
  })

  it('fluids: sell_price maps from response.product.sell_price_per_unit', () => {
    fc.assert(
      fc.property(fluidResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('fluid', response as unknown as Record<string, unknown>)
        if (response.product.sell_price_per_unit != null) {
          expect(item.sell_price).toBe(String(response.product.sell_price_per_unit))
        } else {
          expect(item.sell_price).toBeNull()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('fluids: brand maps from response.product.brand_name', () => {
    fc.assert(
      fc.property(fluidResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('fluid', response as unknown as Record<string, unknown>)
        if (response.product.brand_name != null) {
          expect(item.brand).toBe(String(response.product.brand_name))
        } else {
          expect(item.brand).toBeNull()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('fluids: part_type is always "fluid"', () => {
    fc.assert(
      fc.property(fluidResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('fluid', response as unknown as Record<string, unknown>)
        expect(item.part_type).toBe('fluid')
      }),
      { numRuns: 100 },
    )
  })

  it('services: name maps from response.item.name', () => {
    fc.assert(
      fc.property(serviceResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('service', response as unknown as Record<string, unknown>)
        expect(item.name).toBe(response.item.name)
      }),
      { numRuns: 100 },
    )
  })

  it('services: sell_price maps from response.item.default_price', () => {
    fc.assert(
      fc.property(serviceResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('service', response as unknown as Record<string, unknown>)
        if (response.item.default_price != null) {
          expect(item.sell_price).toBe(String(response.item.default_price))
        } else {
          expect(item.sell_price).toBeNull()
        }
      }),
      { numRuns: 100 },
    )
  })

  it('services: brand is always null', () => {
    fc.assert(
      fc.property(serviceResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('service', response as unknown as Record<string, unknown>)
        expect(item.brand).toBeNull()
      }),
      { numRuns: 100 },
    )
  })

  it('services: part_type is always "service"', () => {
    fc.assert(
      fc.property(serviceResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('service', response as unknown as Record<string, unknown>)
        expect(item.part_type).toBe('service')
      }),
      { numRuns: 100 },
    )
  })

  it('all categories: mapped item always has a valid id, name, and part_type', () => {
    // Parts
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('part', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.part.id)
        expect(item.name).toBe(response.part.name)
        expect(typeof item.part_type).toBe('string')
      }),
      { numRuns: 100 },
    )
    // Tyres
    fc.assert(
      fc.property(partResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('tyre', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.part.id)
        expect(item.name).toBe(response.part.name)
        expect(typeof item.part_type).toBe('string')
      }),
      { numRuns: 100 },
    )
    // Fluids
    fc.assert(
      fc.property(fluidResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('fluid', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.product.id)
        expect(item.name).toBe(response.product.product_name)
        expect(item.part_type).toBe('fluid')
      }),
      { numRuns: 100 },
    )
    // Services
    fc.assert(
      fc.property(serviceResponseArb, (response) => {
        const item = mapResponseToCatalogueItem('service', response as unknown as Record<string, unknown>)
        expect(item.id).toBe(response.item.id)
        expect(item.name).toBe(response.item.name)
        expect(item.part_type).toBe('service')
      }),
      { numRuns: 100 },
    )
  })
})
