/**
 * F6 — RevocationModal: Cancel discards, Confirm posts, success refreshes.
 *
 * Feature: customer-reminder-consent
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const post = vi.fn().mockResolvedValue({ data: {} })
vi.mock('@/api/client', () => ({
  default: { post: (...a: unknown[]) => post(...a) },
}))

import { RevocationModal } from '../RevocationModal'

function renderModal(onRevoked = vi.fn(), onCancel = vi.fn()) {
  render(
    <RevocationModal
      open
      customerId="cust-123"
      category="wof_expiry"
      channel="sms"
      onRevoked={onRevoked}
      onCancel={onCancel}
    />,
  )
}

beforeEach(() => post.mockClear())

describe('RevocationModal', () => {
  it('Cancel discards without posting', () => {
    const onCancel = vi.fn()
    renderModal(vi.fn(), onCancel)
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
  })

  it('Confirm is disabled until method + reason are provided', () => {
    renderModal()
    const confirm = screen.getByRole('button', { name: /revoke consent/i })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/how was the revocation obtained/i), {
      target: { value: 'phone' },
    })
    expect(confirm).toBeDisabled() // still no reason
    fireEvent.change(screen.getByLabelText(/^Reason$/i), {
      target: { value: 'Customer requested' },
    })
    expect(confirm).toBeEnabled()
  })

  it('Confirm posts the revocation and refreshes the parent', async () => {
    const onRevoked = vi.fn()
    renderModal(onRevoked)
    fireEvent.change(screen.getByLabelText(/how was the revocation obtained/i), {
      target: { value: 'phone' },
    })
    fireEvent.change(screen.getByLabelText(/^Reason$/i), {
      target: { value: 'Customer requested' },
    })
    fireEvent.click(screen.getByRole('button', { name: /revoke consent/i }))

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const [url, body] = post.mock.calls[0]
    expect(url).toBe('/customers/cust-123/reminders/revoke')
    expect(body).toEqual({
      obtained_method: 'phone',
      channel: 'sms',
      categories_affected: ['wof_expiry'],
      reason_note: 'Customer requested',
    })
    expect(onRevoked).toHaveBeenCalled()
  })
})
