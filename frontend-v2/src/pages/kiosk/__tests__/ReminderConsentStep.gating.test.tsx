/**
 * E4 / I2 — per-checkbox channel sub-control gates submission (Req 1.6, 1.11).
 *
 * Feature: customer-reminder-consent
 *
 * A ticked sub-checkbox with no channel chosen keeps the step invalid
 * (onValidityChange(false) + Continue disabled); choosing a channel flips it
 * valid; the emitted block carries the chosen channel.
 */

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
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

function setup() {
  const onChange = vi.fn()
  const onValidityChange = vi.fn()
  render(
    <ReminderConsentStep
      vehicles={[VEHICLE]}
      consentText="I agree."
      consentTextVersion="v1"
      isAutomotive
      onChange={onChange}
      onValidityChange={onValidityChange}
      onContinue={vi.fn()}
    />,
  )
  // Tick the master toggle → sub-checkboxes pre-check, channels stay empty.
  fireEvent.click(screen.getByLabelText(/send me reminders/i))
  return { onChange, onValidityChange }
}

describe('ReminderConsentStep channel gating', () => {
  it('is invalid while a ticked row has no channel, then valid once chosen', () => {
    const { onValidityChange, onChange } = setup()

    // After master-on, every row is ticked but channel-less → invalid.
    expect(onValidityChange).toHaveBeenLastCalledWith(false)
    // The Continue button is disabled in the invalid state.
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()

    // Choose a channel for every ticked row (WOF, Registration, Service due).
    screen.getAllByRole('button', { name: 'SMS' }).forEach((b) => fireEvent.click(b))

    expect(onValidityChange).toHaveBeenLastCalledWith(true)
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled()

    // The last emitted block carries the chosen channel.
    const calls = onChange.mock.calls
    const lastBlock = calls[calls.length - 1]?.[0]
    expect(lastBlock).not.toBeNull()
    expect(lastBlock.entries.every((e: { channel: string }) => e.channel === 'sms')).toBe(true)
  })

  it('unticking a row removes its channel requirement', () => {
    const { onValidityChange } = setup()
    // Give every row a channel → valid.
    screen.getAllByRole('button', { name: 'Both' }).forEach((b) => fireEvent.click(b))
    expect(onValidityChange).toHaveBeenLastCalledWith(true)
  })
})
