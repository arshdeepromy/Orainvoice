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
import InvoiceList from './InvoiceList'

/**
 * InvoiceList unit tests (Task 19) — fast list-render + empty-state coverage.
 *
 * Mounts the page inside the REAL Auth → Tenant → Module → FeatureFlag → Branch
 * provider tree with a seeded org_admin session, and mocks `@/api/client` so the
 * contexts AND the page's `GET /invoices` list call resolve against
 * deterministic shapes. The `invoices` fixture is mutable (via vi.hoisted) so a
 * single mock serves both the "has invoices" and "empty" cases.
 */

const h = vi.hoisted(() => ({
  invoices: [] as Array<Record<string, unknown>>,
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
          modules: ['branch_management', 'quotes'].map((slug) => ({
            slug, display_name: slug, description: '', category: 'core', is_core: false, is_enabled: true,
          })),
          total: 2,
        },
      }
    }
    if (url === '/org/settings') {
      return { data: { name: 'Kerikeri Motors', org_name: 'Kerikeri Motors', logo_url: null, primary_colour: '#2F62F0', secondary_colour: '#2450D0', address: null, phone: null, email: null, gst_number: null, gst_percentage: 15, gst_inclusive: true, invoice_prefix: 'INV', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null, trade_family: 'automotive-transport', trade_category: 'general-automotive', sidebar_display_mode: 'icon_and_name', address_country: 'NZ' } }
    }
    if (url === '/org/branches') return { data: { branches: [] } }
    if (url === '/auth/me') return { data: { first_name: 'Preview', last_name: '', branch_ids: [] } }
    if (url === '/api/v2/flags') return { data: { flags: [] } }
    if (url === '/payments/online-payments/status') return { data: { is_connected: false } }
    if (url === '/invoices') return { data: { items: h.invoices, total: h.invoices.length } }
    if (url.startsWith('/invoices/')) {
      // Detail fetch for the auto-selected first invoice — minimal valid shape.
      const id = url.split('/')[2]
      const inv = h.invoices.find((i) => i.id === id) ?? {}
      return {
        data: {
          id, invoice_number: (inv as any).invoice_number ?? null, status: (inv as any).status ?? 'issued',
          line_items: [], subtotal: 0, gst_amount: 0, total: 0, balance_due: 0, amount_paid: 0,
          discount_value: 0, discount_amount: 0, payments: [], credit_notes: [], customer: null,
          issue_date: (inv as any).issue_date ?? null, due_date: null, created_at: '2025-11-01',
        },
      }
    }
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
    <MemoryRouter initialEntries={['/invoices']}>
      <AuthProvider>
        <TenantProvider>
          <ModuleProvider>
            <FeatureFlagProvider>
              <BranchProvider>
                <Routes>
                  <Route path="/invoices" element={<InvoiceList />} />
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
  h.invoices = []
})

describe('InvoiceList', () => {
  it('renders the empty state when there are no invoices', async () => {
    h.invoices = []
    renderList()
    expect(await screen.findByText('No invoices yet.')).toBeInTheDocument()
    // Status filter + search affordances are always present.
    expect(screen.getByLabelText('Filter by status')).toBeInTheDocument()
    expect(screen.getByLabelText('Search invoices')).toBeInTheDocument()
  })

  it('renders a row per invoice with number and NZD total', async () => {
    h.invoices = [
      { id: 'inv-1', invoice_number: 'INV-2041', customer_name: 'Bay Plumbing Ltd', total: 2480, status: 'overdue', issue_date: '2025-11-02', due_date: '2025-10-28' },
      { id: 'inv-2', invoice_number: 'INV-2040', customer_name: 'M. Taufa', total: 640, status: 'issued', issue_date: '2025-11-08' },
    ]
    renderList()

    expect(await screen.findByText('Bay Plumbing Ltd')).toBeInTheDocument()
    expect(screen.getByText('M. Taufa')).toBeInTheDocument()
    // Invoice number appears in the row (and, since it's auto-selected, in the
    // detail toolbar too) — assert at least one occurrence.
    expect(screen.getAllByText(/INV-2041/).length).toBeGreaterThan(0)
    // Currency formatting helper output (NZD prefix, 2dp, grouped).
    expect(screen.getByText('NZD2,480.00')).toBeInTheDocument()
    // Status badge label uppercased.
    await waitFor(() => expect(screen.getByText('OVERDUE')).toBeInTheDocument())
  })
})
