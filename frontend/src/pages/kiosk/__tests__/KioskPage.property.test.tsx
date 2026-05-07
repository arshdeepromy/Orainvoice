import { describe, it, expect, vi } from 'vitest'
import * as fc from 'fast-check'
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react'

/**
 * Property-based tests for KioskPage state machine.
 *
 * Feature: kiosk-vehicle-checkin
 */

// --- Mocks ---

// Track the vehiclesEnabled value for each property run
let mockVehiclesEnabled = false

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isEnabled: (slug: string) => (slug === 'vehicles' ? mockVehiclesEnabled : false),
    refetch: async () => {},
  }),
}))

const mockLookupVehicle = vi.fn()

vi.mock('../api', () => ({
  lookupVehicle: (...args: unknown[]) => mockLookupVehicle(...args),
  lookupCustomer: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}))

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { org_name: 'Test Org', logo_url: null } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import { KioskPage } from '../KioskPage'
import type { VehicleLookupResult } from '../types'

// ---------------------------------------------------------------------------
// Arbitraries
// ---------------------------------------------------------------------------

/** Generate a valid VehicleLookupResult */
const vehicleLookupResultArb: fc.Arbitrary<VehicleLookupResult> = fc.record({
  id: fc.uuid(),
  rego: fc.stringMatching(/^[A-Z0-9]{1,7}$/),
  make: fc.oneof(fc.constant(null), fc.string({ minLength: 1, maxLength: 20 })),
  model: fc.oneof(fc.constant(null), fc.string({ minLength: 1, maxLength: 20 })),
  body_type: fc.oneof(fc.constant(null), fc.string({ minLength: 1, maxLength: 20 })),
  year: fc.oneof(fc.constant(null), fc.integer({ min: 1900, max: 2030 })),
  colour: fc.oneof(fc.constant(null), fc.string({ minLength: 1, maxLength: 20 })),
  wof_expiry: fc.oneof(fc.constant(null), fc.constant('2025-06-01')),
  rego_expiry: fc.oneof(fc.constant(null), fc.constant('2025-12-01')),
  odometer: fc.oneof(fc.constant(null), fc.integer({ min: 0, max: 999999 })),
  source: fc.constantFrom('cache', 'carjam'),
})

// ---------------------------------------------------------------------------
// Property-based tests
// ---------------------------------------------------------------------------

describe('KioskPage — Property-Based Tests', () => {
  // Feature: kiosk-vehicle-checkin, Property 1: Module-gated screen transition
  // **Validates: Requirements 1.1, 1.2**
  describe('Property 1: Module-gated screen transition', () => {
    it('for any org config, "Check In" leads to rego screen iff vehicles module enabled, else form screen', () => {
      fc.assert(
        fc.property(fc.boolean(), (vehiclesEnabled) => {
          // Set the mock value for this run
          mockVehiclesEnabled = vehiclesEnabled

          // Render the KioskPage
          render(<KioskPage />)

          // Find and click the "Check In" button
          const checkInButton = screen.getByRole('button', { name: /check in/i })
          fireEvent.click(checkInButton)

          if (vehiclesEnabled) {
            // Requirement 1.1: vehicles enabled → Registration Screen
            // The KioskRegoEntry component shows "Enter Vehicle Registration" heading
            expect(
              screen.getByRole('heading', { name: /enter vehicle registration/i }),
            ).toBeInTheDocument()
          } else {
            // Requirement 1.2: vehicles disabled → Customer Details Screen (form)
            // The KioskCheckInForm shows a "Check In" heading for the form
            expect(screen.getByRole('heading', { name: /check in/i })).toBeInTheDocument()
            // Verify form fields are present (confirms it's the form screen, not welcome)
            expect(screen.getByLabelText(/first name/i)).toBeInTheDocument()
          }

          // Cleanup DOM between property runs
          cleanup()
        }),
        { numRuns: 100 },
      )
    })
  })

  // Feature: kiosk-vehicle-checkin, Property 11: Session state preservation during navigation
  // **Validates: Requirements 10.1, 10.2**
  describe('Property 11: Session state preservation during navigation', () => {
    it('for any accumulated state, navigating between screens preserves all confirmed vehicles and form data', async () => {
      await fc.assert(
        fc.asyncProperty(
          vehicleLookupResultArb,
          fc.record({
            first_name: fc.string({ minLength: 1, maxLength: 20 }).filter((s) => s.trim().length > 0),
            last_name: fc.string({ minLength: 1, maxLength: 20 }).filter((s) => s.trim().length > 0),
            phone: fc.stringMatching(/^0[0-9]{8,9}$/),
          }),
          async (vehicle, formInput) => {
            // Enable vehicles module
            mockVehiclesEnabled = true
            mockLookupVehicle.mockReset()
            mockLookupVehicle.mockResolvedValueOnce(vehicle)

            render(<KioskPage />)

            // Step 1: Click "Check In" → rego screen
            fireEvent.click(screen.getByRole('button', { name: /check in/i }))
            expect(
              screen.getByRole('heading', { name: /enter vehicle registration/i }),
            ).toBeInTheDocument()

            // Step 2: Enter rego and click Confirm → vehicle summary
            const regoInput = screen.getByLabelText(/vehicle registration number/i)
            fireEvent.change(regoInput, { target: { value: vehicle.rego } })

            await act(async () => {
              fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
            })

            await waitFor(() => {
              expect(screen.getByRole('heading', { name: /vehicle found/i })).toBeInTheDocument()
            })

            // Step 3: Click Confirm on summary → form screen (vehicle added)
            await act(async () => {
              fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
            })

            await waitFor(() => {
              expect(screen.getByLabelText(/first name/i)).toBeInTheDocument()
            })

            // Step 4: Enter form data
            fireEvent.change(screen.getByLabelText(/first name/i), {
              target: { value: formInput.first_name },
            })
            fireEvent.change(screen.getByLabelText(/last name/i), {
              target: { value: formInput.last_name },
            })
            fireEvent.change(screen.getByLabelText(/phone/i), {
              target: { value: formInput.phone },
            })

            // Step 5: Click Back on form → rego screen
            fireEvent.click(screen.getByRole('button', { name: /back/i }))

            // Step 6: Verify vehicle count badge shows "1 vehicle added"
            expect(screen.getByText('1 vehicle added')).toBeInTheDocument()

            // Step 7: Click Skip on rego → form screen
            fireEvent.click(screen.getByRole('button', { name: /skip/i }))

            // Step 8: Verify form data is preserved
            await waitFor(() => {
              expect(screen.getByLabelText(/first name/i)).toBeInTheDocument()
            })

            expect(screen.getByLabelText(/first name/i)).toHaveValue(formInput.first_name)
            expect(screen.getByLabelText(/last name/i)).toHaveValue(formInput.last_name)
            expect(screen.getByLabelText(/phone/i)).toHaveValue(formInput.phone)

            cleanup()
          },
        ),
        { numRuns: 30 },
      )
    })
  })

  // Feature: kiosk-vehicle-checkin, Property 5: Vehicle list accumulation invariant
  // **Validates: Requirements 5.3, 5.4**
  describe('Property 5: Vehicle list accumulation invariant', () => {
    it('for any sequence of N vehicle confirmations, session vehicle list contains exactly N entries', async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.array(vehicleLookupResultArb, { minLength: 1, maxLength: 5 }),
          async (vehicles) => {
            // Enable vehicles module
            mockVehiclesEnabled = true
            mockLookupVehicle.mockReset()

            // Set up lookupVehicle to resolve with each vehicle in sequence
            for (let i = 0; i < vehicles.length; i++) {
              mockLookupVehicle.mockResolvedValueOnce(vehicles[i])
            }

            render(<KioskPage />)

            // Click "Check In" → go to rego screen
            const checkInButton = screen.getByRole('button', { name: /check in/i })
            fireEvent.click(checkInButton)

            for (let i = 0; i < vehicles.length; i++) {
              // We should be on the rego screen
              expect(
                screen.getByRole('heading', { name: /enter vehicle registration/i }),
              ).toBeInTheDocument()

              // If i > 0, verify the badge shows the correct count
              if (i > 0) {
                expect(
                  screen.getByText(`${i} vehicle${i !== 1 ? 's' : ''} added`),
                ).toBeInTheDocument()
              }

              // Type rego and click Confirm
              const regoInput = screen.getByLabelText(/vehicle registration number/i)
              fireEvent.change(regoInput, { target: { value: vehicles[i].rego } })

              await act(async () => {
                fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
              })

              // Wait for vehicle summary screen to appear
              await waitFor(() => {
                expect(screen.getByRole('heading', { name: /vehicle found/i })).toBeInTheDocument()
              })

              // On the last vehicle, click "Confirm" (which goes to form)
              // On all others, click "Add Another Vehicle" (which goes back to rego)
              if (i < vehicles.length - 1) {
                fireEvent.click(
                  screen.getByRole('button', { name: /add another vehicle/i }),
                )
              } else {
                // Click "Confirm" on the summary to add the last vehicle and go to form
                await act(async () => {
                  fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))
                })
              }
            }

            // After all N confirmations, we should be on the form screen
            // The total vehicles added = N (vehicles.length)
            // Verify by checking the form screen is displayed
            await waitFor(() => {
              expect(screen.getByLabelText(/first name/i)).toBeInTheDocument()
            })

            // Navigate back to rego to verify the badge count
            // The form has a "Back" button that goes to rego when vehicles enabled
            fireEvent.click(screen.getByRole('button', { name: /back/i }))

            // Now on rego screen, verify the badge shows N vehicles added
            const n = vehicles.length
            expect(
              screen.getByText(`${n} vehicle${n !== 1 ? 's' : ''} added`),
            ).toBeInTheDocument()

            cleanup()
          },
        ),
        { numRuns: 30 },
      )
    })
  })
})
