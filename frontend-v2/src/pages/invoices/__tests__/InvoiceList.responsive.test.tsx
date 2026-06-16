import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
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
 * InvoiceList responsive master/detail unit tests (task 3.4).
 *
 * These assert DOM/state outcomes that do NOT require a layout engine — the
 * actual breakpoint/container-query/print VISUAL behavior has no layout engine
 * under jsdom and is verified manually/Playwright (task 7). Here we drive the
 * tier purely by mocking `window.matchMedia('(min-width: 1280px)')`:
 *   - matches:false  → below the Wide_Threshold (narrow / single-pane)
 *   - matches:true   → at/above the Wide_Threshold (side-by-side)
 *
 * `@/api/client` is mocked so the contexts and the page's list/detail fetches
 * resolve against deterministic shapes (mirrors InvoiceList.test.tsx).
 * `react-router-dom` is partially mocked so `useNavigate` returns a spy we can
 * assert against; MemoryRouter/Routes/useParams/useLocation stay real so the
 * route still drives `routeId`/`isCreating`. `InvoiceCreate` is stubbed so we
 * can assert it is the sole visible pane on the narrow create route.
 *
 * Requirements: 1.7, 1.8, 1.9, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 4.6, 7.1, 7.3, 8.1, 8.2
 */

const WIDE_QUERY = '(min-width: 1280px)'

/* ------------------------------------------------------------------ */
/*  Hoisted shared state + mocks                                       */
/* ------------------------------------------------------------------ */

const h = vi.hoisted(() => {
  const state: {
    invoices: Array<Record<string, unknown>>
    navigate: ReturnType<typeof vi.fn>
    apiGet: ReturnType<typeof vi.fn>
    apiPut: ReturnType<typeof vi.fn>
    apiPost: ReturnType<typeof vi.fn>
    apiDelete: ReturnType<typeof vi.fn>
  } = {
    invoices: [],
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
      return { data: { name: 'Kerikeri Motors', org_name: 'Kerikeri Motors', logo_url: null, primary_colour: '#2F62F0', secondary_colour: '#2450D0', address: null, phone: null, email: null, gst_number: null, gst_percentage: 15, gst_inclusive: true, invoice_prefix: 'INV', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null, trade_family: 'automotive-transport', trade_category: 'general-automotive', sidebar_display_mode: 'icon_and_name', address_country: 'NZ' } }
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

// Stub InvoiceCreate so the Create_View is a single, easily-asserted node.
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
  const dispatch = (query: string, matches: boolean) => {
    const mql = installed.get(query)
    if (!mql) return
    mql.matches = matches
    const event = { matches, media: query } as MediaQueryListEvent
    mql.listeners.forEach((cb) => cb(event))
  }
  return { matchMedia, installed, dispatch }
}

let mm = createMatchMediaMock(false)

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
  { id: 'inv-1', invoice_number: 'INV-2041', customer_name: 'Bay Plumbing Ltd', total: 2480, status: 'overdue', issue_date: '2025-11-02', due_date: '2025-10-28' },
  { id: 'inv-2', invoice_number: 'INV-2040', customer_name: 'M. Taufa', total: 640, status: 'issued', issue_date: '2025-11-08' },
]

const originalMatchMedia = window.matchMedia

beforeEach(() => {
  localStorage.clear()
  setAccessToken(makeToken())
  h.invoices = SAMPLE_INVOICES.map((i) => ({ ...i }))
  h.navigate.mockClear()
  h.apiPut.mockClear()
  h.apiPost.mockClear()
  // Default tier: narrow (below the Wide_Threshold).
  installMatchMedia(false)
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

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('InvoiceList responsive master/detail', () => {
  // Req 2.6, 7.3 — Back control is a native <button>, Tab-reachable.
  it('renders the Back control as a native, Tab-reachable button on a narrow screen', async () => {
    const user = userEvent.setup()
    renderAt('/invoices/inv-1') // deep-link → narrowPane initializes to 'detail'

    const backBtn = await screen.findByRole('button', { name: 'Back to invoices' })
    expect(backBtn.tagName).toBe('BUTTON')
    expect((backBtn as HTMLButtonElement).type).toBe('button')
    expect((backBtn as HTMLButtonElement).disabled).toBe(false)
    // Native buttons are in the tab order by default (no negative tabindex).
    expect(backBtn.tabIndex).toBeGreaterThanOrEqual(0)

    // Reachable via Tab from a clean state.
    let reached = false
    for (let i = 0; i < 8 && !reached; i++) {
      await user.tab()
      if (document.activeElement === backBtn) reached = true
    }
    expect(reached).toBe(true)
  })

  // Req 2.6, 7.3 — activates on Enter and moves focus to the list region.
  it('activates the Back control with Enter and moves focus to the list region', async () => {
    const user = userEvent.setup()
    renderAt('/invoices/inv-1')

    const backBtn = await screen.findByRole('button', { name: 'Back to invoices' })
    backBtn.focus()
    expect(document.activeElement).toBe(backBtn)

    await user.keyboard('{Enter}')

    // The list region (its search input) is now shown and holds focus (Req 7.3).
    const search = await screen.findByLabelText('Search invoices')
    await waitFor(() => expect(document.activeElement).toBe(search))
    // Detail pane is gone.
    expect(screen.queryByRole('button', { name: 'Back to invoices' })).not.toBeInTheDocument()
  })

  // Req 2.6, 7.3 — activates on Space and moves focus to the list region.
  it('activates the Back control with Space and moves focus to the list region', async () => {
    const user = userEvent.setup()
    renderAt('/invoices/inv-1')

    const backBtn = await screen.findByRole('button', { name: 'Back to invoices' })
    backBtn.focus()
    expect(document.activeElement).toBe(backBtn)

    await user.keyboard('[Space]')

    const search = await screen.findByLabelText('Search invoices')
    await waitFor(() => expect(document.activeElement).toBe(search))
    expect(screen.queryByRole('button', { name: 'Back to invoices' })).not.toBeInTheDocument()
  })

  // Req 2.3, 2.4, 2.5 — narrow: select row → detail; Back → list with row still selected.
  it('shows detail on row select and returns to the list with the row still selected (narrow)', async () => {
    const user = userEvent.setup()
    renderAt('/invoices') // bare narrow mount → starts on the list

    // List is the visible pane.
    const row = await screen.findByText('Bay Plumbing Ltd')
    expect(screen.getByLabelText('Search invoices')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Back to invoices' })).not.toBeInTheDocument()

    // Selecting a row shows the detail region (Req 2.4).
    await user.click(row)
    const backBtn = await screen.findByRole('button', { name: 'Back to invoices' })
    expect(screen.queryByLabelText('Search invoices')).not.toBeInTheDocument()

    // Back returns to the list (Req 2.3).
    await user.click(backBtn)
    await screen.findByLabelText('Search invoices')

    // The previously selected row keeps its persistent selected-state indicator (Req 2.5).
    const rowBtn = (await screen.findByText('Bay Plumbing Ltd')).closest('button')!
    expect(rowBtn).toHaveAttribute('aria-current', 'true')
    expect(rowBtn.className).toContain('bg-accent-soft')
  })

  // Req 1.7 — deep-link mount below the Wide_Threshold initializes narrowPane = 'detail'.
  it('initializes to the detail pane when deep-linking to an invoice below the Wide_Threshold', async () => {
    renderAt('/invoices/inv-1')

    // Detail region for that invoice (its number shows in the detail toolbar).
    expect(await screen.findByRole('button', { name: 'Back to invoices' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText(/INV-2041/).length).toBeGreaterThan(0))
    // List column is not in the visible layout.
    expect(screen.queryByLabelText('Search invoices')).not.toBeInTheDocument()
  })

  // Req 1.8, 1.9 — bare narrow mount stays on the list even after auto-select sets selectedId.
  it('stays on the list on a bare narrow mount even after the first invoice auto-selects', async () => {
    renderAt('/invoices')

    // List is shown.
    await screen.findByText('Bay Plumbing Ltd')
    expect(screen.getByLabelText('Search invoices')).toBeInTheDocument()

    // Auto-selection happens (the detail fetch fires for the first row) but the
    // visible pane must remain the list (auto-selection alone does NOT show detail).
    await waitFor(() => {
      expect(h.apiGet).toHaveBeenCalledWith('/invoices/inv-1')
    })
    expect(screen.getByLabelText('Search invoices')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Back to invoices' })).not.toBeInTheDocument()
  })

  // Req 2.7, 2.8 — Back navigates to /invoices keeping selectedId; reselect → /invoices/:id + detail.
  it('navigates to /invoices on Back (keeping the highlight) and back to /invoices/:id on reselect', async () => {
    const user = userEvent.setup()
    renderAt('/invoices/inv-1') // narrow, detail pane

    const backBtn = await screen.findByRole('button', { name: 'Back to invoices' })
    await user.click(backBtn)

    // Back navigates to the Invoices_List_Path (Req 2.7).
    expect(h.navigate).toHaveBeenCalledWith('/invoices')

    // Row keeps its selected-state indicator (selectedId unchanged) (Req 2.5/2.7).
    const rowBtn = (await screen.findByText('Bay Plumbing Ltd')).closest('button')!
    expect(rowBtn).toHaveAttribute('aria-current', 'true')

    // Reselecting the retained row navigates to /invoices/:id and shows detail (Req 2.8).
    h.navigate.mockClear()
    await user.click(rowBtn)
    expect(h.navigate).toHaveBeenCalledWith('/invoices/inv-1')
    expect(await screen.findByRole('button', { name: 'Back to invoices' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Search invoices')).not.toBeInTheDocument()
  })

  // Req 8.1, 8.2 — narrow create route: Create_View is the sole pane with the Back control.
  it('shows the Create_View as the sole pane with a Back control on the narrow create route', async () => {
    renderAt('/invoices/new')

    expect(await screen.findByTestId('invoice-create-stub')).toBeInTheDocument()
    // Sole pane: the list column is not rendered beside it (Req 8.1).
    expect(screen.queryByLabelText('Search invoices')).not.toBeInTheDocument()
    // Back control is shown (Req 8.2).
    expect(screen.getByRole('button', { name: 'Back to invoices' })).toBeInTheDocument()
  })

  // Req 7.1, 4.6 — a matchMedia change moves focus into the newly shown region
  // and triggers no settings-mutation API call.
  it('moves focus into the newly shown region on a matchMedia change without any settings mutation', async () => {
    // Start at the Wide tier (both panes) deep-linked to an invoice (narrowPane = 'detail').
    installMatchMedia(true)
    renderAt('/invoices/inv-1')

    // Both panes present at the Wide tier; put focus in the list region.
    const search = await screen.findByLabelText('Search invoices')
    search.focus()
    expect(document.activeElement).toBe(search)

    const putCallsBefore = h.apiPut.mock.calls.length
    const postCallsBefore = h.apiPost.mock.calls.length

    // Narrow the viewport: the transition hides the list (which held focus).
    act(() => {
      mm.dispatch(WIDE_QUERY, false)
    })

    // Focus moves to a visible interactive element in the newly shown region (Req 7.1).
    const backBtn = await screen.findByRole('button', { name: 'Back to invoices' })
    await waitFor(() => expect(document.activeElement).toBe(backBtn))

    // No settings-mutation API call fired as a result of the responsive change (Req 4.6).
    const settingsMutations = [
      ...h.apiPut.mock.calls.slice(putCallsBefore),
      ...h.apiPost.mock.calls.slice(postCallsBefore),
    ].filter((c) => String(c[0]).includes('settings'))
    expect(settingsMutations).toHaveLength(0)
  })
})
