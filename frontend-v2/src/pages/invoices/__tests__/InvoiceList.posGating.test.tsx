import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '@/contexts/AuthContext'
import { TenantProvider } from '@/contexts/TenantContext'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { BranchProvider } from '@/contexts/BranchContext'
import { setAccessToken } from '@/api/client'
import { makeToken } from '@/test/providers'
import InvoiceList from '../InvoiceList'

/**
 * InvoiceList POS gating + print regression-guard unit tests (task 5.3).
 *
 * These assert DOM/state outcomes that do NOT require a layout engine. The tier
 * is driven by mocking `window.matchMedia('(min-width: 1280px)')`; we use the
 * Wide tier (matches:true) so the detail region renders side-by-side and the
 * POS panel / PDF-Print toolbar are mounted and testable. The org-level
 * `pos_preview_enabled` toggle is driven through what `/org/settings` returns —
 * TenantContext maps the top-level `pos_preview_enabled` field onto
 * `settings.invoice.pos_preview_enabled`, which the component reads as
 * `posPreviewEnabled`.
 *
 * Asserts:
 *  - posPreviewEnabled === false removes BOTH the POS panel
 *    (`[data-preview="receipt"]`) AND the "Print POS Receipt" menu item;
 *    posPreviewEnabled === true keeps both (Req 3.3, 6.5).
 *  - `selectedPreview` click-to-highlight toggling still works irrespective of
 *    layout (Req 3.5).
 *  - The injected print `<style data-invoice-print="true">` block still contains
 *    the `[data-preview="receipt"] { display: none }` print-regression rule
 *    (Req 6.1, 6.2).
 *
 * Requirements: 3.3, 3.5, 6.1, 6.2, 6.5
 */

/* ------------------------------------------------------------------ */
/*  Hoisted shared state + mocks                                       */
/* ------------------------------------------------------------------ */

const h = vi.hoisted(() => {
  const state: {
    invoices: Array<Record<string, unknown>>
    posPreviewEnabled: boolean
    navigate: ReturnType<typeof vi.fn>
    apiGet: ReturnType<typeof vi.fn>
    apiPut: ReturnType<typeof vi.fn>
    apiPost: ReturnType<typeof vi.fn>
    apiDelete: ReturnType<typeof vi.fn>
  } = {
    invoices: [],
    posPreviewEnabled: true,
    navigate: vi.fn(),
    apiGet: vi.fn(),
    apiPut: vi.fn(),
    apiPost: vi.fn(),
    apiDelete: vi.fn(),
  }

  state.apiGet = vi.fn(async (url: string, _config?: unknown) => {
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
      return {
        data: {
          name: 'Kerikeri Motors', org_name: 'Kerikeri Motors', logo_url: null,
          primary_colour: '#2F62F0', secondary_colour: '#2450D0', address: null, phone: null,
          email: null, gst_number: null, gst_percentage: 15, gst_inclusive: true,
          invoice_prefix: 'INV', default_due_days: 14, payment_terms_text: null,
          terms_and_conditions: null, trade_family: 'automotive-transport',
          trade_category: 'general-automotive', sidebar_display_mode: 'icon_and_name',
          address_country: 'NZ',
          // Drives `settings.invoice.pos_preview_enabled` in TenantContext.
          pos_preview_enabled: state.posPreviewEnabled,
        },
      }
    }
    if (url === '/org/branches') return { data: { branches: [] } }
    if (url === '/auth/me') return { data: { first_name: 'Preview', last_name: '', branch_ids: [] } }
    if (url === '/api/v2/flags') return { data: { flags: [] } }
    if (url === '/payments/online-payments/status') return { data: { is_connected: false } }
    if (url === '/invoices') return { data: { items: state.invoices, total: state.invoices.length } }
    if (url.startsWith('/invoices/')) {
      const id = url.split('/')[2]
      const inv = state.invoices.find((i) => i.id === id) ?? {}
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
  state.apiPut = vi.fn(async () => ({ data: {} }))
  state.apiPost = vi.fn(async () => ({ data: {} }))
  state.apiDelete = vi.fn(async () => ({ data: {} }))

  return state
})

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
  return {
    default: {
      get: h.apiGet,
      post: h.apiPost,
      put: h.apiPut,
      delete: h.apiDelete,
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

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => h.navigate }
})

// Stub InvoiceCreate so it never pulls in heavy create-form dependencies.
vi.mock('../InvoiceCreate', () => ({
  default: () => <div data-testid="invoice-create-stub">Create Invoice Form</div>,
}))

/* ------------------------------------------------------------------ */
/*  Controllable matchMedia mock                                       */
/* ------------------------------------------------------------------ */

interface MockMql {
  matches: boolean
  media: string
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
  listeners: Set<(e: MediaQueryListEvent) => void>
}

function createMatchMediaMock(initialMatches: boolean) {
  const installed = new Map<string, MockMql>()
  const matchMedia = vi.fn((query: string): MediaQueryList => {
    const existing = installed.get(query)
    if (existing) return existing as unknown as MediaQueryList
    const mql: MockMql = {
      matches: initialMatches,
      media: query,
      listeners: new Set(),
      addEventListener: vi.fn((_t: string, cb: (e: MediaQueryListEvent) => void) => { mql.listeners.add(cb) }),
      removeEventListener: vi.fn((_t: string, cb: (e: MediaQueryListEvent) => void) => { mql.listeners.delete(cb) }),
    }
    installed.set(query, mql)
    return mql as unknown as MediaQueryList
  })
  return { matchMedia, installed }
}

let mm = createMatchMediaMock(true)

function installMatchMedia(matches: boolean) {
  mm = createMatchMediaMock(matches)
  window.matchMedia = mm.matchMedia as unknown as typeof window.matchMedia
}

/* ------------------------------------------------------------------ */
/*  Render helper                                                      */
/* ------------------------------------------------------------------ */

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <TenantProvider>
          <ModuleProvider>
            <FeatureFlagProvider>
              <BranchProvider>
                <Routes>
                  <Route path="/invoices" element={<InvoiceList />} />
                  <Route path="/invoices/new" element={<InvoiceList />} />
                  <Route path="/invoices/:id" element={<InvoiceList />} />
                </Routes>
              </BranchProvider>
            </FeatureFlagProvider>
          </ModuleProvider>
        </TenantProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const SAMPLE_INVOICES = [
  { id: 'inv-1', invoice_number: 'INV-2041', customer_name: 'Bay Plumbing Ltd', total: 2480, status: 'issued', issue_date: '2025-11-02', due_date: '2025-11-28' },
  { id: 'inv-2', invoice_number: 'INV-2040', customer_name: 'M. Taufa', total: 640, status: 'issued', issue_date: '2025-11-08' },
]

const originalMatchMedia = window.matchMedia

beforeEach(() => {
  localStorage.clear()
  setAccessToken(makeToken())
  h.invoices = SAMPLE_INVOICES.map((i) => ({ ...i }))
  h.posPreviewEnabled = true
  h.navigate.mockClear()
  h.apiPut.mockClear()
  h.apiPost.mockClear()
  // Wide tier so the detail region renders side-by-side and the POS panel /
  // PDF-Print toolbar are mounted for assertion.
  installMatchMedia(true)
})

afterEach(() => {
  localStorage.clear()
  setAccessToken(null)
  h.invoices = []
  if (originalMatchMedia === undefined) {
    delete (window as unknown as { matchMedia?: unknown }).matchMedia
  } else {
    window.matchMedia = originalMatchMedia
  }
  vi.clearAllMocks()
})

/** Opens the PDF/Print dropdown in the detail toolbar and returns the menu container. */
async function openPdfPrintMenu(user: ReturnType<typeof userEvent.setup>) {
  const trigger = await screen.findByRole('button', { name: /PDF\/Print/i })
  await user.click(trigger)
  return trigger
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('InvoiceList POS gating', () => {
  // Req 3.3, 6.5 — pos_preview_enabled === false hides BOTH the POS panel and
  // the Print POS Receipt menu item.
  it('hides the POS panel and the Print POS Receipt menu item when pos_preview_enabled is false', async () => {
    h.posPreviewEnabled = false
    const user = userEvent.setup()
    const { container } = renderAt('/invoices/inv-1')

    // Detail region for the deep-linked invoice is shown.
    await waitFor(() => expect(screen.getAllByText(/INV-2041/).length).toBeGreaterThan(0))

    // POS panel is NOT in the document (Req 3.3).
    expect(container.querySelector('[data-preview="receipt"]')).toBeNull()

    // Open the PDF/Print dropdown — the Print POS Receipt item is NOT present (Req 6.5).
    await openPdfPrintMenu(user)
    expect(screen.getByText('Print Invoice')).toBeInTheDocument()
    expect(screen.queryByText('Print POS Receipt')).not.toBeInTheDocument()
  })

  // Req 3.3, 6.5 — pos_preview_enabled === true keeps BOTH the POS panel and the
  // Print POS Receipt menu item.
  it('shows the POS panel and the Print POS Receipt menu item when pos_preview_enabled is true', async () => {
    h.posPreviewEnabled = true
    const user = userEvent.setup()
    const { container } = renderAt('/invoices/inv-1')

    await waitFor(() => expect(screen.getAllByText(/INV-2041/).length).toBeGreaterThan(0))

    // POS panel IS in the document.
    await waitFor(() => expect(container.querySelector('[data-preview="receipt"]')).not.toBeNull())

    // Open the PDF/Print dropdown — the Print POS Receipt item IS present.
    await openPdfPrintMenu(user)
    expect(screen.getByText('Print POS Receipt')).toBeInTheDocument()
  })

  // Req 3.5 — selectedPreview click-to-highlight toggling still works irrespective
  // of layout (the receipt panel gains the selected ring class after a click).
  it('toggles the selected-state ring when the POS receipt panel is clicked', async () => {
    h.posPreviewEnabled = true
    const user = userEvent.setup()
    const { container } = renderAt('/invoices/inv-1')

    await waitFor(() => expect(screen.getAllByText(/INV-2041/).length).toBeGreaterThan(0))

    const receiptPanel = await waitFor(() => {
      const el = container.querySelector('[data-preview="receipt"]')
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    const invoicePanelInner = container.querySelector('[data-preview="invoice"] .invoice-doc-scale > div') as HTMLElement

    // Initially the invoice preview carries the selected ring, the receipt does not.
    expect(invoicePanelInner.className).toContain('ring-accent')
    expect(receiptPanel.className).not.toContain('ring-accent')

    // Clicking the receipt panel toggles the selection to the receipt.
    await user.click(receiptPanel)

    await waitFor(() => expect(receiptPanel.className).toContain('ring-accent'))
    expect(receiptPanel.className).toContain('bg-accent-soft')
    // The invoice preview no longer carries the selected ring.
    expect(invoicePanelInner.className).not.toContain('ring-accent')
  })
})

describe('InvoiceList print regression guard', () => {
  // Req 6.1, 6.2 — the injected print <style> still hides the POS receipt column.
  it('injects a print style block that hides [data-preview="receipt"] with display: none', async () => {
    renderAt('/invoices/inv-1')

    // The component injects PRINT_STYLES into document.head on mount.
    const styleEl = await waitFor(() => {
      const el = document.head.querySelector('style[data-invoice-print="true"]')
      expect(el).not.toBeNull()
      return el as HTMLStyleElement
    })

    const css = styleEl.textContent ?? ''
    expect(css).toContain('[data-preview="receipt"]')
    // The receipt-hiding rule must keep display: none (print regression guard).
    const receiptRule = css.slice(css.indexOf('[data-preview="receipt"]'))
    expect(receiptRule).toMatch(/display:\s*none/)
  })
})
