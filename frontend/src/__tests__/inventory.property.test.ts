import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  detectPricingRuleOverlap,
  filterLowStockProducts,
  type PricingRuleForOverlap,
  type ProductStockLevel,
} from '../utils/inventoryCalcs'

// Feature: production-readiness-gaps, Property 17: Pricing rule overlap detection
// Feature: production-readiness-gaps, Property 18: Low stock threshold filtering
// **Validates: Requirements 9.4, 9.6**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Generate a YYYY-MM-DD date string from integer components */
const dateStrArb = fc
  .tuple(
    fc.integer({ min: 2020, max: 2030 }),
    fc.integer({ min: 1, max: 12 }),
    fc.integer({ min: 1, max: 28 }),
  )
  .map(([y, m, d]) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`)

/** Generate a product_id */
const productIdArb = fc
  .array(fc.constantFrom('a', 'b', 'c', 'd', 'e', '1', '2', '3'), {
    minLength: 1,
    maxLength: 8,
  })
  .map((chars) => chars.join(''))

/** Generate a pricing rule with start_date <= end_date */
const pricingRuleArb: fc.Arbitrary<PricingRuleForOverlap> = fc
  .tuple(dateStrArb, dateStrArb, productIdArb)
  .map(([d1, d2, product_id]) => ({
    start_date: d1 <= d2 ? d1 : d2,
    end_date: d1 <= d2 ? d2 : d1,
    product_id,
  }))

/** Generate a list of pricing rules */
const pricingRulesArb = fc.array(pricingRuleArb, { minLength: 0, maxLength: 20 })

/** Generate a product stock level entry */
const productStockArb: fc.Arbitrary<ProductStockLevel> = fc
  .tuple(
    fc.uuid(),
    fc.nat({ max: 1000 }),
    fc.nat({ max: 1000 }),
  )
  .map(([id, stock_level, reorder_point]) => ({
    id,
    stock_level,
    reorder_point,
  }))

/** Generate a list of product stock levels */
const productStockListArb = fc.array(productStockArb, { minLength: 0, maxLength: 30 })

/* ------------------------------------------------------------------ */
/*  Property 17: Pricing rule overlap detection                        */
/* ------------------------------------------------------------------ */

describe('Property 17: Pricing rule overlap detection', () => {
  it('detects overlapping rules for the same product', () => {
    fc.assert(
      fc.property(dateStrArb, dateStrArb, productIdArb, (d1, d2, pid) => {
        const start = d1 <= d2 ? d1 : d2
        const end = d1 <= d2 ? d2 : d1
        // Two identical-range rules for the same product must overlap
        const rules: PricingRuleForOverlap[] = [
          { start_date: start, end_date: end, product_id: pid },
          { start_date: start, end_date: end, product_id: pid },
        ]
        const overlaps = detectPricingRuleOverlap(rules)
        expect(overlaps.length).toBeGreaterThanOrEqual(1)
        expect(overlaps).toContainEqual({ index1: 0, index2: 1 })
      }),
      { numRuns: 100 },
    )
  })

  it('rules for different products never overlap', () => {
    fc.assert(
      fc.property(pricingRulesArb, (rules) => {
        const overlaps = detectPricingRuleOverlap(rules)
        for (const { index1, index2 } of overlaps) {
          expect(rules[index1].product_id).toBe(rules[index2].product_id)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('non-overlapping date ranges for the same product produce no overlaps', () => {
    fc.assert(
      fc.property(dateStrArb, dateStrArb, productIdArb, (d1, d2, pid) => {
        const earlier = d1 <= d2 ? d1 : d2
        const later = d1 <= d2 ? d2 : d1
        // Construct two rules where rule A ends strictly before rule B starts
        // by using earlier as end of A and a day after later as start of B
        const ruleA: PricingRuleForOverlap = {
          start_date: '2020-01-01',
          end_date: earlier,
          product_id: pid,
        }
        const ruleB: PricingRuleForOverlap = {
          start_date: later > earlier ? later : '2030-12-31',
          end_date: '2030-12-31',
          product_id: pid,
        }
        // Only test when the ranges are truly non-overlapping
        if (ruleA.end_date < ruleB.start_date) {
          const overlaps = detectPricingRuleOverlap([ruleA, ruleB])
          expect(overlaps).toHaveLength(0)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('empty rules array returns no overlaps', () => {
    expect(detectPricingRuleOverlap([])).toHaveLength(0)
  })

  it('single rule returns no overlaps', () => {
    fc.assert(
      fc.property(pricingRuleArb, (rule) => {
        expect(detectPricingRuleOverlap([rule])).toHaveLength(0)
      }),
      { numRuns: 100 },
    )
  })

  it('overlap pairs have valid indices', () => {
    fc.assert(
      fc.property(pricingRulesArb, (rules) => {
        const overlaps = detectPricingRuleOverlap(rules)
        for (const { index1, index2 } of overlaps) {
          expect(index1).toBeGreaterThanOrEqual(0)
          expect(index1).toBeLessThan(rules.length)
          expect(index2).toBeGreaterThan(index1)
          expect(index2).toBeLessThan(rules.length)
        }
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 18: Low stock threshold filtering                         */
/* ------------------------------------------------------------------ */

describe('Property 18: Low stock threshold filtering', () => {
  it('returns only products where stock_level <= reorder_point', () => {
    fc.assert(
      fc.property(productStockListArb, (products) => {
        const result = filterLowStockProducts(products)
        for (const p of result) {
          expect(p.stock_level).toBeLessThanOrEqual(p.reorder_point)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('excludes products where stock_level > reorder_point', () => {
    fc.assert(
      fc.property(productStockListArb, (products) => {
        const result = filterLowStockProducts(products)
        const resultIds = new Set(result.map((p) => p.id))
        for (const p of products) {
          if (p.stock_level > p.reorder_point) {
            expect(resultIds.has(p.id)).toBe(false)
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  it('result count equals count of products at or below reorder_point', () => {
    fc.assert(
      fc.property(productStockListArb, (products) => {
        const expected = products.filter((p) => p.stock_level <= p.reorder_point).length
        const result = filterLowStockProducts(products)
        expect(result).toHaveLength(expected)
      }),
      { numRuns: 100 },
    )
  })

  it('empty product list returns empty result', () => {
    expect(filterLowStockProducts([])).toHaveLength(0)
  })

  it('preserves original product objects (identity)', () => {
    fc.assert(
      fc.property(productStockListArb, (products) => {
        const result = filterLowStockProducts(products)
        for (const r of result) {
          expect(products).toContain(r)
        }
      }),
      { numRuns: 100 },
    )
  })
})
