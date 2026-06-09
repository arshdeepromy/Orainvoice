/**
 * F7 — Customer List "Reminder Consent" column behind the org-setting flag.
 *
 * Feature: customer-reminder-consent
 *
 * Column hidden when `customers_consent_column_visible` is false/absent,
 * shown (with Yes/No cells from has_reminder_consent) when true.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '@/contexts/AuthContext'
import { TenantProvider } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { setAccessToken } from '@/api/client'
import { makeToken } from '@/test/providers'
import CustomerList from '../CustomerList'

const h = vi.hoisted(() => ({
  consentVisible: false as boolean,
  customers: [] as Array<Record<string, unknown>>,
}))

vi.mock('@/api/client', () => {
  let token: string | null = null
  const isValid = () => {
    if (!token) return false
    try {
      const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
      return payload.exp * 1000 > Date.now() + 60_000
    } catch {
      return false
    }
  }
  const get = vi.fn(async (url: string) => {
    if (url === '/modules') {
      return { data: { modules: [{ slug: 'branch_management', display_name: 'b', description: '', category: 'core', is_core: false, is_enabled: true }], total: 1 } }
    }
    if (url === '/org/settings') {
      return { data: { name: 'Kerikeri Motors', org_name: 'Kerikeri Motors', logo_url: null, primary_colour: '#2F62F0', secondary_colour: '#2450D0', address: null, phone: null, email: null, gst_number: null, gst_percentage: 15, gst_inclusive: true, invoice_prefix: 'INV', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null, trade_family: 'automotive-transport', trade_category: 'general-automotive', sidebar_display_mode: 'icon_and_name', customers_consent_column_visible: h.consentVisible, address_country: 'NZ' } }
    }
    if (url === '/org/branches') return { data: { branches: [] } }
    if (url === '/auth/me') return { data: { first_name: 'Preview', last_name: '', branch_ids: [] } }
    if (url === '/api/v2/flags') return { data: { flags: [] } }
    if (url === '/customers') return { data: { customers: h.customers, total: h.customers.length, has_exact_match: false } }
    return { data: {} }
  })
  return {
    default: {
      get,
      post: vi.fn(async () => ({ data: {} })),
      put: vi.fn(async () => ({ data: {} })),
      delete: vi.fn(async () => ({ data: {} })),
      interceptors: { request: { use: vi.fn(() => 0), eject: vi.fn() }, response: { use: vi.fn(() => 0), eject: vi.fn() } },
    },
    setAccessToken: (t: string | null) => { token = t },
    getAccessToken: () => token,
    isAccessTokenValid: isValid,
    doTokenRefresh: () => Promise.resolve(token),
  }
})

function renderList() {
  render(
    <MemoryRouter initialEntries={['/customers']}>
      <AuthProvider>
        <TenantProvider>
          <ModuleProvider>
            <FeatureFlagProvider>
              <BranchProvider>
                <Routes>
                  <Route path="/customers" element={<CustomerList />} />
                </Routes>
              </BranchProvider>
            </FeatureFlagProvider>
          </ModuleProvider>
        </TenantProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  localStorage.clear()
  setAccessToken(makeToken())
  h.customers = [
    { id: 'c-1', first_name: 'Bay', last_name: 'Plumbing', display_name: 'Bay Plumbing', company_name: null, email: 'a@b.nz', work_phone: '021', receivables: 0, unused_credits: 0, reminders_enabled: true, has_reminder_consent: true, last_portal_access_at: null, branch_id: null },
  ]
})

afterEach(() => {
  localStorage.clear()
  setAccessToken(null)
  h.customers = []
  h.consentVisible = false
})

describe('CustomerList reminder-consent column (F7)', () => {
  it('hides the column when the flag is false', async () => {
    h.consentVisible = false
    renderList()
    await screen.findByText('Bay Plumbing')
    expect(screen.queryByRole('columnheader', { name: /Reminder Consent/i })).not.toBeInTheDocument()
  })

  it('shows the column with Yes/No when the flag is true', async () => {
    h.consentVisible = true
    renderList()
    await screen.findByText('Bay Plumbing')
    await waitFor(() =>
      expect(screen.getByRole('columnheader', { name: /Reminder Consent/i })).toBeInTheDocument(),
    )
    expect(screen.getByText('Yes')).toBeInTheDocument()
  })
})
