/**
 * E5 — the kiosk check-in POST body includes `reminder_consent` when the
 * customer opted in, and omits it otherwise.
 *
 * Feature: customer-reminder-consent
 *
 * Exercises the actual submission path (KioskCheckInForm builds the body and
 * POSTs to /kiosk/check-in), which is where E5 added the consent field.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const post = vi.fn().mockResolvedValue({ data: { customer_first_name: 'Jo' } })

vi.mock('@/api/client', () => ({
  default: { post: (...a: unknown[]) => post(...a), get: vi.fn() },
}))
vi.mock('../api', () => ({
  lookupCustomer: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}))

import { KioskCheckInForm } from '../KioskCheckInForm'
import type { KioskFormData, KioskReminderConsentBlock } from '../types'

const FORM: KioskFormData = {
  first_name: 'Jo',
  last_name: 'Driver',
  phone: '021555000',
  email: 'jo@example.com',
}

const BLOCK: KioskReminderConsentBlock = {
  consent_text_version: 'v1',
  entries: [{ vehicle_id: 'veh-1', category: 'wof_expiry', channel: 'sms' }],
}

function renderForm(reminderConsent: KioskReminderConsentBlock | null) {
  render(
    <KioskCheckInForm
      formData={FORM}
      onFormDataChange={vi.fn()}
      onSuccess={vi.fn()}
      onError={vi.fn()}
      onBack={vi.fn()}
      vehicles={[]}
      reminderConsent={reminderConsent}
    />,
  )
  // Confirm-email is internal state — match it so validation passes.
  fireEvent.change(screen.getByPlaceholderText('Re-enter your email'), {
    target: { value: 'jo@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: /complete check-in/i }))
}

describe('kiosk check-in submit body', () => {
  beforeEach(() => post.mockClear())

  it('includes reminder_consent when the customer opted in', async () => {
    renderForm(BLOCK)
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const [, body] = post.mock.calls[0]
    expect(body.reminder_consent).toEqual(BLOCK)
  })

  it('omits reminder_consent when there is no consent block', async () => {
    renderForm(null)
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const [, body] = post.mock.calls[0]
    expect('reminder_consent' in body).toBe(false)
  })
})
