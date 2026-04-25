import { describe, it, expect, beforeEach } from 'vitest'
import * as fc from 'fast-check'
import { saveLayout, loadLayout, filterStaleWidgets } from '../WidgetGrid'

// Feature: automotive-dashboard-widgets
// Property 3: Layout Persistence Round-Trip — **Validates: Requirements 3.2, 3.3**
// Property 4: Stale Widget Filtering Preserves Available Widget Order — **Validates: Requirements 3.5**

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

/** Generate a widget-ID-like string (alphanumeric with dashes) */
const widgetIdArb = fc
  .array(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789-'.split('')), {
    minLength: 1,
    maxLength: 20,
  })
  .map((chars) => chars.join(''))

/** Generate a user ID (non-empty alphanumeric) */
const userIdArb = fc
  .array(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789'.split('')), {
    minLength: 1,
    maxLength: 20,
  })
  .map((chars) => chars.join(''))

/** Generate a non-empty array of unique widget IDs */
const widgetIdArrayArb = fc
  .uniqueArray(widgetIdArb, { minLength: 1, maxLength: 20 })

/* ------------------------------------------------------------------ */
/*  Property 3: Layout Persistence Round-Trip                          */
/* ------------------------------------------------------------------ */

describe('Property 3: Layout Persistence Round-Trip', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('save then load returns identical widget order', () => {
    fc.assert(
      fc.property(userIdArb, widgetIdArrayArb, (userId, order) => {
        saveLayout(userId, order)
        const loaded = loadLayout(userId)
        expect(loaded).toEqual(order)
      }),
      { numRuns: 100 },
    )
  })

  it('loadLayout returns null when no layout has been saved', () => {
    fc.assert(
      fc.property(userIdArb, (userId) => {
        const loaded = loadLayout(userId)
        expect(loaded).toBeNull()
      }),
      { numRuns: 100 },
    )
  })

  it('different user IDs have independent layouts', () => {
    fc.assert(
      fc.property(
        userIdArb,
        userIdArb.filter((id) => id !== ''),
        widgetIdArrayArb,
        widgetIdArrayArb,
        (userId1, userId2Suffix, order1, order2) => {
          // Ensure distinct user IDs
          const userId2 = userId1 + '_' + userId2Suffix
          saveLayout(userId1, order1)
          saveLayout(userId2, order2)
          expect(loadLayout(userId1)).toEqual(order1)
          expect(loadLayout(userId2)).toEqual(order2)
        },
      ),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 4: Stale Widget Filtering Preserves Available Widget Order*/
/* ------------------------------------------------------------------ */

describe('Property 4: Stale Widget Filtering Preserves Available Widget Order', () => {
  it('filtered result contains only available IDs', () => {
    fc.assert(
      fc.property(widgetIdArrayArb, widgetIdArrayArb, (savedOrder, availableIds) => {
        const result = filterStaleWidgets(savedOrder, availableIds)
        const availableSet = new Set(availableIds)
        for (const id of result) {
          expect(availableSet.has(id)).toBe(true)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('preserves relative order of saved IDs that are still available', () => {
    fc.assert(
      fc.property(widgetIdArrayArb, widgetIdArrayArb, (savedOrder, availableIds) => {
        const result = filterStaleWidgets(savedOrder, availableIds)
        const availableSet = new Set(availableIds)

        // Extract the subset of saved IDs that are available
        const keptFromSaved = savedOrder.filter((id) => availableSet.has(id))

        // The kept IDs should appear in the same relative order in the result
        const resultKept = result.filter((id) => keptFromSaved.includes(id))
        expect(resultKept).toEqual(keptFromSaved)
      }),
      { numRuns: 100 },
    )
  })

  it('appends new available IDs not in saved order at the end', () => {
    fc.assert(
      fc.property(widgetIdArrayArb, widgetIdArrayArb, (savedOrder, availableIds) => {
        const result = filterStaleWidgets(savedOrder, availableIds)
        const savedSet = new Set(savedOrder)

        // IDs in available but not in saved should appear at the end
        const newIds = availableIds.filter((id) => !savedSet.has(id))
        if (newIds.length > 0) {
          const resultTail = result.slice(result.length - newIds.length)
          expect(resultTail).toEqual(newIds)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('result contains all available IDs exactly once', () => {
    fc.assert(
      fc.property(widgetIdArrayArb, widgetIdArrayArb, (savedOrder, availableIds) => {
        const result = filterStaleWidgets(savedOrder, availableIds)
        const resultSet = new Set(result)

        // Every available ID is in the result
        for (const id of availableIds) {
          expect(resultSet.has(id)).toBe(true)
        }

        // No duplicates
        expect(result.length).toBe(resultSet.size)
      }),
      { numRuns: 100 },
    )
  })
})
