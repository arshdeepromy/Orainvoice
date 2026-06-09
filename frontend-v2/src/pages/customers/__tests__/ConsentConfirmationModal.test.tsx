/**
 * F4 / I4 — Consent Confirmation modal.
 *
 * Feature: customer-reminder-consent
 *
 * Covers: Cancel discards (no PUT), Confirm posts with a consent_record whose
 * source = `manually_recorded_by_staff:${obtained_method}` and
 * consent_text_version = the version from the mocked /customers/consent-text
 * fetch, and "Other" requires a note.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const put = vi.fn().mockResolvedValue({ data: {} })
vi.mock('@/api/client', () => ({
  default: { put: (...a: unknown[]) => put(...a) },
}))
const fetchConsentText = vi.fn().mockResolvedValue({ text: 'Consent text', version: '2026-06-08-v1' })
vi.mock('@/api/customers', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/customers')>()
  return { ...actual, fetchConsentText: (...a: unknown[]) => fetchConsentText(...a) }
})

import { ConsentConfirmationModal } from '../ConsentConfirmationModal'
import type { MissingConsentPair } from '@/api/customers'

const MISSING: MissingConsentPair[] = [
  { category: 'wof_expiry', channel: 'sms' },
]
const CONFIG = {
  wof_expiry: { enabled: true, days_before: 30, channel: 'sms' as const },
}

function renderModal(onConfirmed = vi.fn(), onCancel = vi.fn()) {
  render(
    <ConsentConfirmationModal
      open
      customerId="cust-123"
      missing={MISSING}
      config={CONFIG}
      onConfirmed={onConfirmed}
      onCancel={onCancel}
    />,
  )
}

beforeEach(() => {
  put.mockClear()
  fetchConsentText.mockClear()
})

describe('ConsentConfirmationModal', () => {
  it('Cancel discards without issuing a PUT', () => {
    const onCancel = vi.fn()
    renderModal(vi.fn(), onCancel)
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
    expect(put).not.toHaveBeenCalled()
  })

  it('Confirm posts a consent_record with composed source + fetched version', async () => {
    const onConfirmed = vi.fn()
    renderModal(onConfirmed)
    // Wait for the consent text to load (Confirm gated on version).
    await screen.findByText('Consent text')

    fireEvent.change(screen.getByLabelText(/how was consent obtained/i), {
      target: { value: 'phone' },
    })
    fireEvent.click(screen.getByRole('button', { name: /confirm consent/i }))

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1))
    const [url, body] = put.mock.calls[0]
    expect(url).toBe('/customers/cust-123/reminders')
    expect(body.consent_record.source).toBe('manually_recorded_by_staff:phone')
    expect(body.consent_record.consent_text_version).toBe('2026-06-08-v1')
    expect(body.consent_record.entries).toEqual([
      { vehicle_id: null, category: 'wof_expiry', channel: 'sms' },
    ])
    // The config is persisted alongside the consent record.
    expect(body.wof_expiry).toEqual(CONFIG.wof_expiry)
    expect(onConfirmed).toHaveBeenCalled()
  })

  it('"Other" requires a note before Confirm is enabled', async () => {
    renderModal()
    await screen.findByText('Consent text')

    fireEvent.change(screen.getByLabelText(/how was consent obtained/i), {
      target: { value: 'other' },
    })
    const confirm = screen.getByRole('button', { name: /confirm consent/i })
    expect(confirm).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/note .required for/i), {
      target: { value: 'Customer confirmed by letter' },
    })
    expect(confirm).toBeEnabled()
  })
})
