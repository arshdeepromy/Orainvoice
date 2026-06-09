/**
 * E2 — KioskPage fetches /kiosk/consent-text once at mount.
 *
 * Feature: customer-reminder-consent
 */

import { render, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const fetchConsentText = vi.fn().mockResolvedValue({ text: 'Consent text', version: 'v1' })

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => true }),
}))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ logout: vi.fn() }),
}))
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { session: null } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))
vi.mock('../api', () => ({
  fetchConsentText: (...args: unknown[]) => fetchConsentText(...args),
  lookupVehicle: vi.fn(),
  lookupCustomer: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}))

import { KioskPage } from '../KioskPage'

describe('KioskPage consent-text boot fetch', () => {
  beforeEach(() => {
    fetchConsentText.mockClear()
  })

  it('calls fetchConsentText exactly once at mount', async () => {
    render(<KioskPage />)
    await waitFor(() => expect(fetchConsentText).toHaveBeenCalledTimes(1))
  })
})
