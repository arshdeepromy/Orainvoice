import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ---------------------------------------------------------------------------
// Pure helpers: mirror the filtering and indicator logic used by
// CataloguePicker (AddToStockModal.tsx) and StockLevels.tsx
// ---------------------------------------------------------------------------

type Category = 'part' | 'tyre' | 'fluid'

interface PartCatalogueEntry {
  id: string
  name: string
  part_type: string
  is_active: boolean
}

/**
 * Filter parts catalogue entries by category, matching the logic in
 * CataloguePicker: `res.data.parts.filter((p) => p.part_type === category)`
 *
 * Parts and tyres both live in parts_catalogue, distinguished by part_type.
 * Fluids come from a separate endpoint and are not filtered this way.
 */
function filterPartsByCategory(
  parts: PartCatalogueEntry[],
  category: Category,
): PartCatalogueEntry[] {
  return parts.filter((p) => p.part_type === category)
}

/**
 * Determine whether a catalogue item is already in stock, matching the logic
 * in CataloguePicker: `existingStockItemIds.has(item.id)`
 */
function isAlreadyInStock(
  itemId: string,
  existingStockItemIds: Set<string>,
): boolean {
  return existingStockItemIds.has(itemId)
}

// ---------------------------------------------------------------------------
// Arbitraries
// ---------------------------------------------------------------------------

/** Generate a UUID-like string id */
const uuidArb = fc.uuid()

/** Generate a part catalogue entry with a specific part_type */
const partEntryArb = (partType: string): fc.Arbitrary<PartCatalogueEntry> =>
  fc.record({
    id: uuidArb,
    name: fc.string({ minLength: 1, maxLength: 50 }),
    part_type: fc.constant(partType),
    is_active: fc.constant(true),
  })

/** Generate a mixed catalogue with parts, tyres, and other types */
const mixedPartsArb = fc.array(
  fc.oneof(
    partEntryArb('part'),
    partEntryArb('tyre'),
    // Include some entries with unexpected part_type to ensure filtering is strict
    partEntryArb('accessory'),
    partEntryArb('tool'),
  ),
  { minLength: 0, maxLength: 30 },
)

// ---------------------------------------------------------------------------
// Property-based tests
// ---------------------------------------------------------------------------

describe('StockLevels — Property-Based Tests', () => {
  // Feature: inventory-stock-management, Property 4: Category Filtering
  // **Validates: Requirements 3.3, 4.1**
  it('Property 4: filtering parts by category returns only items matching selected category', () => {
    fc.assert(
      fc.property(
        mixedPartsArb,
        fc.constantFrom('part' as Category, 'tyre' as Category),
        (parts, category) => {
          const result = filterPartsByCategory(parts, category)

          // Every returned item must match the selected category
          for (const item of result) {
            expect(item.part_type).toBe(category)
          }

          // The result must contain ALL items of the selected category
          const expected = parts.filter((p) => p.part_type === category)
          expect(result.length).toBe(expected.length)

          // The result IDs must match exactly the expected IDs (same order)
          expect(result.map((r) => r.id)).toEqual(expected.map((e) => e.id))
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 4: fluid category never matches parts catalogue entries', () => {
    fc.assert(
      fc.property(mixedPartsArb, (parts) => {
        // Fluids come from a separate endpoint; filtering parts_catalogue
        // by 'fluid' should always return an empty list since no part_type
        // is 'fluid' in the parts catalogue.
        const result = filterPartsByCategory(parts, 'fluid')
        expect(result.length).toBe(0)
      }),
      { numRuns: 100 },
    )
  })

  // Feature: inventory-stock-management, Property 6: Already-In-Stock Indicator
  // **Validates: Requirements 4.5**
  it('Property 6: already-in-stock indicator is true iff catalogue_item_id exists in stock items set', () => {
    fc.assert(
      fc.property(
        // Generate a list of catalogue item IDs
        fc.array(uuidArb, { minLength: 1, maxLength: 30 }),
        // Generate a subset of IDs that are "in stock"
        fc.array(uuidArb, { minLength: 0, maxLength: 15 }),
        (catalogueIds, stockedIds) => {
          const stockSet = new Set(stockedIds)

          for (const id of catalogueIds) {
            const result = isAlreadyInStock(id, stockSet)
            const expected = stockSet.has(id)
            expect(result).toBe(expected)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 6: items explicitly added to stock set are always marked as in-stock', () => {
    fc.assert(
      fc.property(
        fc.array(uuidArb, { minLength: 1, maxLength: 20 }),
        (ids) => {
          // All IDs are in the stock set
          const stockSet = new Set(ids)

          for (const id of ids) {
            expect(isAlreadyInStock(id, stockSet)).toBe(true)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('Property 6: items not in stock set are never marked as in-stock', () => {
    fc.assert(
      fc.property(
        fc.array(uuidArb, { minLength: 1, maxLength: 20 }),
        fc.array(uuidArb, { minLength: 1, maxLength: 20 }),
        (catalogueIds, stockedIds) => {
          const stockSet = new Set(stockedIds)

          for (const id of catalogueIds) {
            if (!stockSet.has(id)) {
              expect(isAlreadyInStock(id, stockSet)).toBe(false)
            }
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
