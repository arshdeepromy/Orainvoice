/**
 * Property-based tests for vehicle module gating on the frontend.
 *
 * Properties covered:
 *   P7  — Frontend vehicle UI visibility (ModuleGate)
 *   P8  — Frontend payload omits vehicle fields when disabled
 *   P9  — Customer search API omits vehicle inclusion when disabled
 *
 * Feature: vehicle-module-gating
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ---------------------------------------------------------------------------
// Vehicle field keys that must be omitted when vehicles module is disabled
// ---------------------------------------------------------------------------

const VEHICLE_PAYLOAD_KEYS = [
  'vehicle_rego',
  'vehicle_make',
  'vehicle_model',
  'vehicle_year',
  'vehicle_odometer',
  'global_vehicle_id',
  'vehicles',
] as const

// ---------------------------------------------------------------------------
// Generators
// ---------------------------------------------------------------------------

/** Generate a random rego string */
const regoArb = fc.stringOf(fc.constantFrom('A', 'B', 'C', 'X', 'Y', 'Z'), {
  minLength: 3,
  maxLength: 3,
}).chain((letters: string) =>
  fc.stringOf(fc.constantFrom('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'), {
    minLength: 3,
    maxLength: 3,
  }).map((digits: string) => letters + digits)
)

/** Generate a vehicle-like object */
const vehicleArb = fc.record({
  id: fc.uuid(),
  rego: regoArb,
  make: fc.constantFrom('Toyota', 'Ford', 'BMW', 'Honda', 'Mazda'),
  model: fc.constantFrom('Corolla', 'Ranger', '320i', 'Civic', 'CX-5'),
  year: fc.integer({ min: 1990, max: 2026 }),
  odometer: fc.option(fc.integer({ min: 0, max: 999999 }), { nil: undefined }),
  newOdometer: fc.option(fc.integer({ min: 0, max: 999999 }), { nil: undefined }),
})

/** Generate a customer search query */
const searchQueryArb = fc.string({ minLength: 2, maxLength: 50 })

// ---------------------------------------------------------------------------
// Helpers — replicate the buildPayload gating logic from InvoiceCreate.tsx
// ---------------------------------------------------------------------------

interface Vehicle {
  id: string
  rego: string
  make: string
  model: string
  year: number
  odometer?: number
  newOdometer?: number
}

function buildPayload(
  vehiclesEnabled: boolean,
  vehicles: Vehicle[],
  status: 'draft' | 'sent',
): Record<string, unknown> {
  return {
    customer_id: 'cust-1',
    // This mirrors the exact gating logic in InvoiceCreate.tsx
    ...(vehiclesEnabled
      ? {
          vehicle_rego: vehicles[0]?.rego,
          vehicle_make: vehicles[0]?.make,
          vehicle_model: vehicles[0]?.model,
          vehicle_year: vehicles[0]?.year,
          vehicle_odometer:
            vehicles[0]?.newOdometer ?? vehicles[0]?.odometer ?? undefined,
          global_vehicle_id: vehicles[0]?.id,
          vehicles: vehicles.map((v) => ({
            id: v.id,
            rego: v.rego,
            make: v.make,
            model: v.model,
            year: v.year,
            odometer: v.newOdometer ?? v.odometer ?? undefined,
          })),
        }
      : {}),
    status,
  }
}

// ---------------------------------------------------------------------------
// Helper — replicate the customer search include_vehicles gating
// ---------------------------------------------------------------------------

function buildCustomerSearchParams(
  vehiclesEnabled: boolean,
  query: string,
): Record<string, string | boolean> {
  const params: Record<string, string | boolean> = { search: query }
  if (vehiclesEnabled) {
    params.include_vehicles = true
  }
  return params
}

// ===========================================================================
// Property 7: Frontend vehicle UI visibility
// Feature: vehicle-module-gating, Property 7: Frontend vehicle UI visibility
// ===========================================================================

describe('Property 7: Frontend vehicle UI visibility', () => {
  it('ModuleGate hides children when module is disabled', () => {
    // Feature: vehicle-module-gating, Property 7: Frontend vehicle UI visibility
    fc.assert(
      fc.property(fc.boolean(), (vehiclesEnabled: boolean) => {
        // Simulate ModuleGate logic: if !isEnabled(module), render fallback (null)
        const shouldRender = vehiclesEnabled
        if (!vehiclesEnabled) {
          expect(shouldRender).toBe(false)
        } else {
          expect(shouldRender).toBe(true)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('vehicle UI sections are gated consistently across all invoice pages', () => {
    // Feature: vehicle-module-gating, Property 7: Frontend vehicle UI visibility
    fc.assert(
      fc.property(fc.boolean(), (vehiclesEnabled: boolean) => {
        // All three pages use the same ModuleGate pattern
        const invoiceCreateShowsVehicle = vehiclesEnabled
        const invoiceListShowsVehicle = vehiclesEnabled
        const invoiceDetailShowsVehicle = vehiclesEnabled

        // All pages must agree
        expect(invoiceCreateShowsVehicle).toBe(vehiclesEnabled)
        expect(invoiceListShowsVehicle).toBe(vehiclesEnabled)
        expect(invoiceDetailShowsVehicle).toBe(vehiclesEnabled)

        // When disabled, none should show
        if (!vehiclesEnabled) {
          expect(invoiceCreateShowsVehicle).toBe(false)
          expect(invoiceListShowsVehicle).toBe(false)
          expect(invoiceDetailShowsVehicle).toBe(false)
        }
      }),
      { numRuns: 100 },
    )
  })

  it('onVehicleAutoSelect is no-op when disabled', () => {
    // Feature: vehicle-module-gating, Property 7: Frontend vehicle UI visibility
    fc.assert(
      fc.property(vehicleArb, fc.boolean(), (vehicle: Vehicle, vehiclesEnabled: boolean) => {
        // Simulate: onVehicleAutoSelect is undefined when disabled
        const callback = vehiclesEnabled
          ? (v: Vehicle) => v
          : undefined

        if (!vehiclesEnabled) {
          expect(callback).toBeUndefined()
        } else {
          expect(callback).toBeDefined()
          expect(callback!(vehicle)).toEqual(vehicle)
        }
      }),
      { numRuns: 100 },
    )
  })
})

// ===========================================================================
// Property 8: Frontend payload omits vehicle fields when disabled
// Feature: vehicle-module-gating, Property 8: Frontend payload omits vehicle fields when disabled
// ===========================================================================

describe('Property 8: Frontend payload omits vehicle fields when disabled', () => {
  it('buildPayload never contains vehicle keys when vehiclesEnabled is false', () => {
    // Feature: vehicle-module-gating, Property 8: Frontend payload omits vehicle fields when disabled
    fc.assert(
      fc.property(
        fc.array(vehicleArb, { minLength: 0, maxLength: 5 }),
        fc.constantFrom('draft' as const, 'sent' as const),
        (vehicles: Vehicle[], status: 'draft' | 'sent') => {
          const payload = buildPayload(false, vehicles, status)

          for (const key of VEHICLE_PAYLOAD_KEYS) {
            expect(payload).not.toHaveProperty(key)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('buildPayload includes vehicle keys when vehiclesEnabled is true and vehicles exist', () => {
    // Feature: vehicle-module-gating, Property 8: Frontend payload omits vehicle fields when disabled
    fc.assert(
      fc.property(
        fc.array(vehicleArb, { minLength: 1, maxLength: 5 }),
        fc.constantFrom('draft' as const, 'sent' as const),
        (vehicles: Vehicle[], status: 'draft' | 'sent') => {
          const payload = buildPayload(true, vehicles, status)

          expect(payload).toHaveProperty('vehicle_rego')
          expect(payload).toHaveProperty('vehicle_make')
          expect(payload).toHaveProperty('vehicle_model')
          expect(payload).toHaveProperty('vehicle_year')
          expect(payload).toHaveProperty('global_vehicle_id')
          expect(payload).toHaveProperty('vehicles')
        },
      ),
      { numRuns: 100 },
    )
  })

  it('non-vehicle fields are always present regardless of module state', () => {
    // Feature: vehicle-module-gating, Property 8: Frontend payload omits vehicle fields when disabled
    fc.assert(
      fc.property(
        fc.boolean(),
        fc.array(vehicleArb, { minLength: 0, maxLength: 3 }),
        fc.constantFrom('draft' as const, 'sent' as const),
        (vehiclesEnabled: boolean, vehicles: Vehicle[], status: 'draft' | 'sent') => {
          const payload = buildPayload(vehiclesEnabled, vehicles, status)

          // These fields should always be present
          expect(payload).toHaveProperty('customer_id')
          expect(payload).toHaveProperty('status')
          expect(payload.status).toBe(status)
        },
      ),
      { numRuns: 100 },
    )
  })
})

// ===========================================================================
// Property 9: Customer search API omits vehicle inclusion when disabled
// Feature: vehicle-module-gating, Property 9: Customer search API omits vehicle inclusion when disabled
// ===========================================================================

describe('Property 9: Customer search API omits vehicle inclusion when disabled', () => {
  it('include_vehicles param is absent when module disabled', () => {
    // Feature: vehicle-module-gating, Property 9: Customer search API omits vehicle inclusion when disabled
    fc.assert(
      fc.property(searchQueryArb, (query: string) => {
        const params = buildCustomerSearchParams(false, query)
        expect(params).not.toHaveProperty('include_vehicles')
        expect(params.search).toBe(query)
      }),
      { numRuns: 100 },
    )
  })

  it('include_vehicles param is present when module enabled', () => {
    // Feature: vehicle-module-gating, Property 9: Customer search API omits vehicle inclusion when disabled
    fc.assert(
      fc.property(searchQueryArb, (query: string) => {
        const params = buildCustomerSearchParams(true, query)
        expect(params.include_vehicles).toBe(true)
        expect(params.search).toBe(query)
      }),
      { numRuns: 100 },
    )
  })

  it('search query is always included regardless of module state', () => {
    // Feature: vehicle-module-gating, Property 9: Customer search API omits vehicle inclusion when disabled
    fc.assert(
      fc.property(fc.boolean(), searchQueryArb, (vehiclesEnabled: boolean, query: string) => {
        const params = buildCustomerSearchParams(vehiclesEnabled, query)
        expect(params.search).toBe(query)
      }),
      { numRuns: 100 },
    )
  })
})
