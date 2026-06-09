/**
 * G4 / CP-4 — kiosk consent step is default-unchecked on every mount,
 * regardless of any persisted localStorage / sessionStorage state.
 *
 * Feature: customer-reminder-consent, Property 4 (CP-4): Kiosk
 * default-unchecked invariant.
 *
 * The component must NEVER read persisted state — so for any random storage
 * seed, mounting it yields an unchecked master toggle and no ticked
 * sub-checkboxes / chosen channels.
 */

import { render, screen, cleanup } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import { ReminderConsentStep } from '../ReminderConsentStep'
import type { ReminderConsentVehicle } from '../types'

const VEHICLE: ReminderConsentVehicle = {
  global_vehicle_id: 'veh-1',
  rego: 'ABC123',
  make: 'Toyota',
  model: 'Hilux',
  inspection_type: 'wof',
  wof_expiry: '2026-07-01',
  cof_expiry: null,
}

describe('ReminderConsentStep default-unchecked invariant (CP-4)', () => {
  it('mounts unchecked for any persisted storage seed', () => {
    fc.assert(
      fc.property(
        fc.dictionary(fc.string(), fc.string()),
        fc.dictionary(fc.string(), fc.string()),
        (localSeed, sessionSeed) => {
          window.localStorage.clear()
          window.sessionStorage.clear()
          for (const [k, v] of Object.entries(localSeed)) {
            window.localStorage.setItem(k, v)
          }
          for (const [k, v] of Object.entries(sessionSeed)) {
            window.sessionStorage.setItem(k, v)
          }

          render(
            <ReminderConsentStep
              vehicles={[VEHICLE]}
              consentText="I agree."
              consentTextVersion="v1"
              isAutomotive
              onChange={() => {}}
              onValidityChange={() => {}}
            />,
          )

          // Master toggle unchecked.
          const master = screen.getByLabelText(/send me reminders/i) as HTMLInputElement
          expect(master.checked).toBe(false)
          // No sub-checkboxes rendered while master is off (none can be ticked).
          const checkboxes = document.querySelectorAll('input[type="checkbox"]')
          expect(checkboxes.length).toBe(1) // only the master toggle
          // No channel controls present.
          expect(screen.queryByRole('button', { name: /^(SMS|Email|Both)$/ })).toBeNull()

          cleanup()
        },
      ),
      { numRuns: 100 },
    )
  })
})
