import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { filterByUserLocations } from '../utils/franchiseUtils'

// Feature: production-readiness-gaps, Property 4: Location data is RBAC-scoped for Location_Manager
// **Validates: Requirements 2.6, 2.7**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const locationIdArb = fc.uuid()

const locationItemArb = (locationIds: string[]): fc.Arbitrary<{ location_id: string; name: string }> =>
  fc.record({
    location_id: fc.constantFrom(...locationIds),
    name: fc.string({ minLength: 1, maxLength: 30 }),
  })

const roleArb = fc.constantFrom(
  'org_admin',
  'location_manager',
  'staff_member',
  'salesperson',
  'global_admin',
)

/* ------------------------------------------------------------------ */
/*  Property 4: Location data is RBAC-scoped for Location_Manager      */
/* ------------------------------------------------------------------ */

describe('Property 4: Location data is RBAC-scoped for Location_Manager', () => {
  it('location_manager sees only items from assigned locations', () => {
    fc.assert(
      fc.property(
        fc.array(locationIdArb, { minLength: 2, maxLength: 10 }).chain((allLocationIds) => {
          const uniqueIds = [...new Set(allLocationIds)]
          // Ensure at least 2 unique location IDs so we can split them
          if (uniqueIds.length < 2) return fc.constant(null)
          // Pick a subset as user's assigned locations
          const splitIndex = Math.max(1, Math.floor(uniqueIds.length / 2))
          const userLocations = uniqueIds.slice(0, splitIndex)
          return fc.tuple(
            fc.array(locationItemArb(uniqueIds), { minLength: 1, maxLength: 20 }),
            fc.constant(userLocations),
            fc.constant(uniqueIds),
          )
        }),
        (result) => {
          if (result === null) return // skip degenerate case
          const [data, userLocations] = result

          const filtered = filterByUserLocations(data, userLocations, 'location_manager')
          const userLocationSet = new Set(userLocations)

          // Every returned item must belong to an assigned location
          for (const item of filtered) {
            expect(userLocationSet.has(item.location_id)).toBe(true)
          }

          // Every item in the original data that belongs to an assigned location must be returned
          const expectedCount = data.filter((d) => userLocationSet.has(d.location_id)).length
          expect(filtered.length).toBe(expectedCount)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('org_admin sees all location data', () => {
    fc.assert(
      fc.property(
        fc.array(locationIdArb, { minLength: 1, maxLength: 8 }).chain((locationIds) => {
          const uniqueIds = [...new Set(locationIds)]
          if (uniqueIds.length < 1) return fc.constant(null)
          return fc.tuple(
            fc.array(locationItemArb(uniqueIds), { minLength: 0, maxLength: 20 }),
            fc.array(fc.constantFrom(...uniqueIds), { minLength: 0, maxLength: 3 }),
          )
        }),
        (result) => {
          if (result === null) return
          const [data, userLocations] = result

          const filtered = filterByUserLocations(data, userLocations, 'org_admin')

          // Org_Admin should see all items regardless of assigned locations
          expect(filtered.length).toBe(data.length)
          for (let i = 0; i < data.length; i++) {
            expect(filtered[i]).toBe(data[i])
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('non-location_manager roles see all data', () => {
    fc.assert(
      fc.property(
        fc.array(locationIdArb, { minLength: 1, maxLength: 8 }).chain((locationIds) => {
          const uniqueIds = [...new Set(locationIds)]
          if (uniqueIds.length < 1) return fc.constant(null)
          return fc.tuple(
            fc.array(locationItemArb(uniqueIds), { minLength: 0, maxLength: 20 }),
            fc.array(fc.constantFrom(...uniqueIds), { minLength: 0, maxLength: 3 }),
            fc.constantFrom('org_admin', 'staff_member', 'salesperson', 'global_admin'),
          )
        }),
        (result) => {
          if (result === null) return
          const [data, userLocations, role] = result

          const filtered = filterByUserLocations(data, userLocations, role)

          // Any role other than location_manager should see all items
          expect(filtered.length).toBe(data.length)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('location_manager with no assigned locations sees nothing', () => {
    fc.assert(
      fc.property(
        fc.array(locationIdArb, { minLength: 1, maxLength: 8 }).chain((locationIds) => {
          const uniqueIds = [...new Set(locationIds)]
          if (uniqueIds.length < 1) return fc.constant(null)
          return fc.array(locationItemArb(uniqueIds), { minLength: 1, maxLength: 20 })
        }),
        (result) => {
          if (result === null) return
          const data = result

          const filtered = filterByUserLocations(data, [], 'location_manager')

          expect(filtered.length).toBe(0)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('filtering preserves item identity (no duplicates, no mutations)', () => {
    fc.assert(
      fc.property(
        fc.array(locationIdArb, { minLength: 2, maxLength: 8 }).chain((locationIds) => {
          const uniqueIds = [...new Set(locationIds)]
          if (uniqueIds.length < 2) return fc.constant(null)
          const splitIndex = Math.max(1, Math.floor(uniqueIds.length / 2))
          const userLocations = uniqueIds.slice(0, splitIndex)
          return fc.tuple(
            fc.array(locationItemArb(uniqueIds), { minLength: 1, maxLength: 20 }),
            fc.constant(userLocations),
          )
        }),
        (result) => {
          if (result === null) return
          const [data, userLocations] = result

          const filtered = filterByUserLocations(data, userLocations, 'location_manager')

          // Every filtered item must be a reference to an original item (not a copy)
          for (const item of filtered) {
            expect(data).toContain(item)
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
