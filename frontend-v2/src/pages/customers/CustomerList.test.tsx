import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '@/contexts/AuthContext'
import { TenantProvider } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { setAccessToken } from '@/api/client'
import { makeToken } from '@/test/providers'
import CustomerList from './CustomerList'

/**
 * CustomerList unit tests (Task 23) — list-render + empty-state coverage,
 * mirroring the InvoiceList test harness. Mounts the page inside the REAL
 * Auth → Tenant → Module → FeatureFlag → Branch provider tree with a seeded
 * org_admin session and mocks `@/api/client` so the contexts AND the page's
 * `GET /customers` call resolve against deterministic shapes. The fixture is
 * mutable (vi.hoisted) so a single mock serves the empty + populated cases.
 *
 * Asserts the Receivables / Unused Credits columns (ISSUE-036) and the
 * NZD-formatted money cells are present (FR-1 / FR-2c).
 */

const h = vi.hoisted(() => ({
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
      return {
        data: {
          modules: ['branch_management'].map((slug) => ({
            slug, display_name: slug, description: '', category: 'core', is_core: false, is_enabled: true,
          })),
          total: 1,
        },
      }
    }
    if (url === '/org/settings') {
      return { data: { name: 'Kerikeri Motors', org_name: 'Kerikeri Motors', logo_url: null, primary_colour: '#2F62F0', secondary_colour: '#2450D0', address: null, phone: null, email: null, gst_number: null, gst_percentage: 15, gst_inclusive: true, invoice_prefix: 'INV', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null, trade_family: 'automotive-transport', trade_category: 'general-automotive', sidebar_display_mode: 'icon_and_name', address_country: 'NZ' } }
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
      interceptors: {
        request: { use: vi.fn(() => 0), eject: vi.fn() },
        response: { use: vi.fn(() => 0), eject: vi.fn() },
      },
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
})

afterEach(() => {
  localStorage.clear()
  setAccessToken(null)
  h.customers = []
})

describe('CustomerList', () => {
  it('renders the empty state when there are no customers', async () => {
    h.customers = []
    renderList()
    expect(
      await screen.findByText('No customers yet. Create your first customer to get started.'),
    ).toBeInTheDocument()
    // Receivables + Unused Credits columns are always present (ISSUE-036).
    expect(screen.getByText('Receivables (BCY)')).toBeInTheDocument()
    expect(screen.getByText('Unused Credits (BCY)')).toBeInTheDocument()
    expect(screen.getByLabelText('Search customers')).toBeInTheDocument()
  })

  it('renders a row per customer with NZD receivables / unused credits', async () => {
    h.customers = [
      { id: 'c-1', first_name: 'Bay', last_name: 'Plumbing', display_name: 'Bay Plumbing Workshop', company_name: 'Bay Plumbing Ltd', email: 'admin@bayplumbing.nz', work_phone: '021 554 200', receivables: 2480, unused_credits: 0, reminders_enabled: false, last_portal_access_at: null, branch_id: null },
      { id: 'c-2', first_name: 'M.', last_name: 'Taufa', display_name: 'M. Taufa', email: 'm.taufa@gmail.com', phone: '022 109 8845', receivables: 0, unused_credits: 120, reminders_enabled: true, last_portal_access_at: null, branch_id: null },
    ]
    renderList()

    // Name cell (display_name) vs Company cell — distinct strings so each is unique.
    expect(await screen.findByText('Bay Plumbing Workshop')).toBeInTheDocument()
    expect(screen.getByText('Bay Plumbing Ltd')).toBeInTheDocument()
    expect(screen.getByText('M. Taufa')).toBeInTheDocument()
    // Currency formatting helper output (NZD prefix, 2dp, grouped).
    expect(screen.getByText('NZD2,480.00')).toBeInTheDocument()
    expect(screen.getByText('NZD120.00')).toBeInTheDocument()
  })
})
