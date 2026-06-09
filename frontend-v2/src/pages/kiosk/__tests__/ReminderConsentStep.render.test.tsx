/**
 * E1 / I1 — ReminderConsentStep rendering per vehicle.inspection_type.
 *
 * Feature: customer-reminder-consent
 * Covers Req 1.5a–1.5e: the single inspection-type checkbox resolves to WOF,
 * COF, or none; non-automotive trade families show only Service due.
 */

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ReminderConsentStep } from '../ReminderConsentStep'
import type { ReminderConsentVehicle } from '../types'

function vehicle(overrides: Partial<ReminderConsentVehicle> = {}): ReminderConsentVehicle {
  return {
    global_vehicle_id: 'veh-1',
    rego: 'ABC123',
    make: 'Toyota',
    model: 'Hilux',
    inspection_type: null,
    wof_expiry: null,
    cof_expiry: null,
    ...overrides,
  }
}

function renderStep(v: ReminderConsentVehicle, isAutomotive = true) {
  render(
    <ReminderConsentStep
      vehicles={[v]}
      consentText="I agree to receive reminders."
      consentTextVersion="2026-06-08-v1"
      isAutomotive={isAutomotive}
      onChange={vi.fn()}
      onValidityChange={vi.fn()}
    />,
  )
  // Reveal the per-vehicle rows by ticking the master toggle.
  fireEvent.click(screen.getByLabelText(/send me reminders/i))
}

describe('ReminderConsentStep inspection-type rows', () => {
  it('renders WOF when inspection_type=wof', () => {
    renderStep(vehicle({ inspection_type: 'wof' }))
    expect(screen.getByText('WOF expiry')).toBeInTheDocument()
    expect(screen.queryByText('COF expiry')).not.toBeInTheDocument()
  })

  it('renders COF when inspection_type=cof', () => {
    renderStep(vehicle({ inspection_type: 'cof' }))
    expect(screen.getByText('COF expiry')).toBeInTheDocument()
    expect(screen.queryByText('WOF expiry')).not.toBeInTheDocument()
  })

  it('prefers COF when both expiries set and no inspection_type', () => {
    renderStep(vehicle({ wof_expiry: '2026-07-01', cof_expiry: '2026-08-01' }))
    expect(screen.getByText('COF expiry')).toBeInTheDocument()
    expect(screen.queryByText('WOF expiry')).not.toBeInTheDocument()
  })

  it('renders COF when only cof_expiry set', () => {
    renderStep(vehicle({ cof_expiry: '2026-08-01' }))
    expect(screen.getByText('COF expiry')).toBeInTheDocument()
  })

  it('renders WOF when only wof_expiry set', () => {
    renderStep(vehicle({ wof_expiry: '2026-07-01' }))
    expect(screen.getByText('WOF expiry')).toBeInTheDocument()
  })

  it('renders no inspection row when neither type nor expiry present', () => {
    renderStep(vehicle())
    expect(screen.queryByText('WOF expiry')).not.toBeInTheDocument()
    expect(screen.queryByText('COF expiry')).not.toBeInTheDocument()
    // Registration + Service due still render for automotive.
    expect(screen.getByText('Registration expiry')).toBeInTheDocument()
    expect(screen.getByText('Service due')).toBeInTheDocument()
  })

  it('non-automotive shows only Service due (hides WOF/COF/registration)', () => {
    renderStep(vehicle({ inspection_type: 'wof', wof_expiry: '2026-07-01' }), false)
    expect(screen.getByText('Service due')).toBeInTheDocument()
    expect(screen.queryByText('WOF expiry')).not.toBeInTheDocument()
    expect(screen.queryByText('COF expiry')).not.toBeInTheDocument()
    expect(screen.queryByText('Registration expiry')).not.toBeInTheDocument()
  })
})
