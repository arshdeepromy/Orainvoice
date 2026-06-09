/**
 * E6 — accessibility hardening for the kiosk consent step (Req 1.9/1.10, NFR-4).
 *
 * Feature: customer-reminder-consent
 *
 * jsdom has no layout engine, so pixel sizes / contrast are verified in the
 * Playwright e2e (I5). Here we assert the structural a11y guarantees that ARE
 * observable in jsdom: every checkbox has an associated label, every
 * interactive control carries the ≥44px hit-area utility classes, and the
 * consent text uses the ≥16px / ≥12px font-size classes.
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

function renderExpanded() {
  const result = render(
    <ReminderConsentStep
      vehicles={[VEHICLE]}
      consentText="I agree to receive reminders."
      consentTextVersion="v1"
      isAutomotive
      onChange={vi.fn()}
      onValidityChange={vi.fn()}
      onContinue={vi.fn()}
    />,
  )
  fireEvent.click(screen.getByLabelText(/send me reminders/i))
  return result
}

describe('ReminderConsentStep accessibility', () => {
  it('every checkbox has an associated <label htmlFor>', () => {
    const { container } = renderExpanded()
    const checkboxes = container.querySelectorAll('input[type="checkbox"]')
    expect(checkboxes.length).toBeGreaterThan(0)
    checkboxes.forEach((cb) => {
      const id = cb.getAttribute('id')
      expect(id).toBeTruthy()
      expect(container.querySelector(`label[for="${id}"]`)).not.toBeNull()
    })
  })

  it('checkbox hit areas use the ≥44px utility class on their label', () => {
    const { container } = renderExpanded()
    container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      const id = cb.getAttribute('id')
      const label = container.querySelector(`label[for="${id}"]`)
      expect(label?.className).toContain('min-h-[44px]')
    })
  })

  it('channel + continue buttons carry ≥44px hit-area classes', () => {
    renderExpanded()
    // Reveal channel controls by leaving rows ticked (master-on pre-checks).
    const channelButtons = screen.getAllByRole('button', { name: /^(SMS|Email|Both)$/ })
    expect(channelButtons.length).toBeGreaterThan(0)
    channelButtons.forEach((b) => {
      expect(b.className).toContain('min-h-[44px]')
      expect(b.className).toContain('min-w-[44px]')
    })
    const cont = screen.getByRole('button', { name: /continue/i })
    expect(cont.className).toContain('min-h-[44px]')
  })

  it('primary consent text is ≥16px and the supporting note ≥12px', () => {
    renderExpanded()
    expect(screen.getByText('I agree to receive reminders.').className).toContain('text-base')
    expect(
      screen.getByText(/change or withdraw consent at any time/i).className,
    ).toContain('text-xs')
  })
})
