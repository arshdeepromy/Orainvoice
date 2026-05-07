import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { render } from '@testing-library/react'
import { KioskVehicleSummary } from '../KioskVehicleSummary'
import type { VehicleLookupResult } from '../types'

// ---------------------------------------------------------------------------
// Arbitraries
// ---------------------------------------------------------------------------

/** Generate a non-empty string for vehicle fields (1-30 printable chars) */
const nonEmptyStringArb = fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim().length > 0)

/** Generate a date string in YYYY-MM-DD format */
const dateStringArb = fc
  .tuple(
    fc.integer({ min: 2020, max: 2030 }),
    fc.integer({ min: 1, max: 12 }),
    fc.integer({ min: 1, max: 28 }),
  )
  .map(([y, m, d]) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`)

/** Generate a positive odometer value */
const odometerArb = fc.integer({ min: 1, max: 999999 })

/** Generate a VehicleLookupResult with a mix of null and non-null optional fields */
const vehicleLookupResultArb: fc.Arbitrary<VehicleLookupResult> = fc.record({
  id: fc.uuid(),
  rego: fc.stringMatching(/^[A-Z0-9]{1,7}$/).filter((s) => s.length >= 1),
  make: fc.option(nonEmptyStringArb, { nil: null }),
  model: fc.option(nonEmptyStringArb, { nil: null }),
  body_type: fc.option(nonEmptyStringArb, { nil: null }),
  year: fc.option(fc.integer({ min: 1990, max: 2026 }), { nil: null }),
  colour: fc.option(nonEmptyStringArb, { nil: null }),
  wof_expiry: fc.option(dateStringArb, { nil: null }),
  rego_expiry: fc.option(dateStringArb, { nil: null }),
  odometer: fc.option(odometerArb, { nil: null }),
  source: fc.constantFrom('cache', 'carjam', 'manual'),
})

/**
 * Generate a VehicleLookupResult where at least one optional display field is non-null.
 * This ensures the property test always has something to verify.
 */
const vehicleWithAtLeastOneFieldArb: fc.Arbitrary<VehicleLookupResult> = vehicleLookupResultArb.filter(
  (v) =>
    v.body_type !== null ||
    v.make !== null ||
    v.model !== null ||
    v.wof_expiry !== null ||
    v.rego_expiry !== null ||
    v.odometer !== null,
)

// ---------------------------------------------------------------------------
// Property-based tests
// ---------------------------------------------------------------------------

describe('KioskVehicleSummary — Property-Based Tests', () => {
  // Feature: kiosk-vehicle-checkin, Property 4: Vehicle summary displays all available fields
  // **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5**
  describe('Property 4: Vehicle summary displays all available fields', () => {
    it('for any vehicle lookup result with non-null fields, rendered output contains each non-null value', () => {
      fc.assert(
        fc.asyncProperty(vehicleWithAtLeastOneFieldArb, async (vehicle) => {
          const { container } = render(
            <KioskVehicleSummary
              vehicle={vehicle}
              vehicleCount={0}
              onConfirm={() => {}}
              onAddAnother={() => {}}
              onBack={() => {}}
            />,
          )

          const textContent = container.textContent ?? ''

          // Requirement 4.1: body_type is displayed when non-null
          if (vehicle.body_type !== null) {
            expect(textContent).toContain(vehicle.body_type)
          }

          // Requirement 4.2: make and model are displayed when non-null
          // The component renders make and model combined (e.g., "Toyota Corolla")
          if (vehicle.make !== null) {
            expect(textContent).toContain(vehicle.make)
          }
          if (vehicle.model !== null) {
            expect(textContent).toContain(vehicle.model)
          }

          // Requirement 4.3: WOF expiry is displayed when non-null
          if (vehicle.wof_expiry !== null) {
            expect(textContent).toContain(vehicle.wof_expiry)
          }

          // Requirement 4.4: rego_expiry is displayed when non-null
          if (vehicle.rego_expiry !== null) {
            expect(textContent).toContain(vehicle.rego_expiry)
          }

          // Requirement 4.5: odometer is displayed when non-null
          // The component renders odometer with .toLocaleString() + " km"
          if (vehicle.odometer !== null) {
            const formattedOdometer = (vehicle.odometer ?? 0).toLocaleString()
            expect(textContent).toContain(formattedOdometer)
            expect(textContent).toContain('km')
          }
        }),
        { numRuns: 100 },
      )
    })
  })
})
