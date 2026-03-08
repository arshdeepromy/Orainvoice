/**
 * Pure utility functions for inventory calculations.
 * Extracted for property-based testing (Properties 17, 18).
 *
 * Validates: Requirements 9.4, 9.6
 */

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface PricingRuleForOverlap {
  start_date: string
  end_date: string
  product_id: string
}

export interface ProductStockLevel {
  id: string
  stock_level: number
  reorder_point: number
}

export interface OverlapPair {
  index1: number
  index2: number
}

/* ------------------------------------------------------------------ */
/*  Property 17: Pricing rule overlap detection                        */
/* ------------------------------------------------------------------ */

/**
 * Detect overlapping pricing rules for the same product.
 * Two rules overlap when they share the same product_id and their
 * date ranges intersect (start1 <= end2 AND start2 <= end1).
 *
 * Returns an array of index pairs identifying the overlapping rules.
 */
export function detectPricingRuleOverlap(
  rules: PricingRuleForOverlap[],
): OverlapPair[] {
  const overlaps: OverlapPair[] = []

  for (let i = 0; i < rules.length; i++) {
    for (let j = i + 1; j < rules.length; j++) {
      const a = rules[i]
      const b = rules[j]

      // Only check rules for the same product
      if (a.product_id !== b.product_id) continue

      // Check date range overlap: start1 <= end2 AND start2 <= end1
      if (a.start_date <= b.end_date && b.start_date <= a.end_date) {
        overlaps.push({ index1: i, index2: j })
      }
    }
  }

  return overlaps
}

/* ------------------------------------------------------------------ */
/*  Property 18: Low stock threshold filtering                         */
/* ------------------------------------------------------------------ */

/**
 * Filter products where stock_level is at or below the reorder_point.
 * Returns only the products that are low on stock.
 */
export function filterLowStockProducts<T extends ProductStockLevel>(
  products: T[],
): T[] {
  return products.filter((p) => p.stock_level <= p.reorder_point)
}
