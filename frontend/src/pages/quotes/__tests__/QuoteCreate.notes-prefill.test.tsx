// Feature: quote-settings-parity, Property 3: Notes pre-fill semantics
import type { ReactElement } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, act } from '@testing-library/react'
import * as fc from 'fast-check'

// ─── Mocks ───────────────────────────────────────────────────────────────────

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()
vi.mock('../../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
    delete: vi.fn(),
  },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({}),
}))

// Mutable holder so each fc iteration can override the settings.invoice payload.
let mockTenantSettings: any = null
vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({
    tradeFamily: 'automotive-transport',
    settings: mockTenantSettings,
  }),
}))

vi.mock('../../../contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: () => true }),
}))

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({ selectedBranchId: null, branches: [] }),
}))

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u-1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
  }),
}))

vi.mock('@/utils/navigationGuard', () => ({
  setNavigationGuard: vi.fn(),
  clearNavigationGuard: vi.fn(),
}))

vi.mock('../../../components/vehicles/VehicleLiveSearch', () => ({
  VehicleLiveSearch: () => null,
}))
vi.mock('../../../components/customers/CustomerCreateModal', () => ({
  CustomerCreateModal: () => null,
}))
vi.mock('../../../components/quotes/QuoteMultiVehicleSection', () => ({
  default: () => null,
}))
vi.mock('../../../components/quotes/InventoryPickerModal', () => ({
  default: () => null,
}))

import QuoteCreate from '../QuoteCreate'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function setupApiMocks() {
  mockGet.mockImplementation((url: string) => {
    if (url === '/catalogue/items') return Promise.resolve({ data: { items: [] } })
    if (url === '/org/salespeople') return Promise.resolve({ data: { salespeople: [] } })
    if (url.includes('/customers')) return Promise.resolve({ data: { customers: [] } })
    return Promise.resolve({ data: {} })
  })
}

// QuoteCreate's Notes editor is a contentEditable <div> with a unique
// aria-label. Locate it deterministically that way.
function findNotesEditor(container: HTMLElement): HTMLDivElement {
  const el = container.querySelector(
    'div[contenteditable="true"][aria-label="Customer notes"]',
  ) as HTMLDivElement | null
  if (!el) throw new Error('Could not find Notes contentEditable on QuoteCreate')
  return el
}

// Mirror the toHtml() helper inside QuoteCreate so the test can compute the
// expected innerHTML for any (enabled, default_notes) tuple.
function toHtml(value: string): string {
  if (/<[a-z][\s\S]*>/i.test(value)) return value
  return value.replace(/\r\n|\r|\n/g, '<br>')
}

// Normalise an HTML string the way the browser does when assigned via
// innerHTML (e.g. `&` → `&amp;`). Avoids brittle string comparisons.
function normaliseHtml(html: string): string {
  const el = document.createElement('div')
  el.innerHTML = html
  return el.innerHTML
}

function buildSettings(opts: { default_notes_enabled: boolean; default_notes: string }) {
  return {
    branding: {
      name: 'Test Org',
      logo_url: null,
      primary_colour: '#000',
      secondary_colour: '#111',
      address: null,
      phone: null,
      email: null,
      sidebar_display_mode: 'icon_and_name' as const,
    },
    gst: { gst_number: null, gst_percentage: 15, gst_inclusive: false },
    invoice: {
      prefix: 'QT-',
      default_due_days: 14,
      payment_terms_text: null,
      terms_and_conditions: null,
      default_notes: opts.default_notes,
      default_notes_enabled: opts.default_notes_enabled,
      payment_terms_enabled: true,
      terms_and_conditions_enabled: false, // keep T&C effect dormant
    },
    addressCountry: null,
  }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('QuoteCreate — Notes pre-fill semantics (Property 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupApiMocks()
  })
  afterEach(() => {
    cleanup()
    mockTenantSettings = null
  })

  /**
   * Property 3a — pre-fill semantics on initial mount.
   * **Validates: Requirements 1.1, 1.2, 1.3**
   *
   * For any (default_notes_enabled, default_notes) on a fresh mount in create
   * mode (no prior user value), the resulting Notes editor innerHTML equals:
   *   - toHtml(default_notes) when default_notes_enabled && default_notes non-empty,
   *   - else the empty string.
   *
   * The contentEditable editor stores HTML; legacy plain-text defaults are
   * converted via toHtml() so newlines render as <br> rather than disappearing.
   */
  it('Property 3a: pre-fills Notes with toHtml(default) when enabled and non-empty (else empty)', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.boolean(),
        fc.string({ minLength: 0, maxLength: 50 }),
        async (default_notes_enabled, default_notes) => {
          mockTenantSettings = buildSettings({ default_notes_enabled, default_notes })

          let container: HTMLElement | null = null
          await act(async () => {
            const result = render(<QuoteCreate />)
            container = result.container
          })
          // give effects a tick to run
          await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
          })

          const editor = findNotesEditor(container!)
          const expected =
            default_notes_enabled && default_notes
              ? normaliseHtml(toHtml(default_notes))
              : ''
          expect(editor.innerHTML).toBe(expected)

          cleanup()
        },
      ),
      { numRuns: 100 },
    )
  })

  /**
   * Property 3b — stable settings re-render does not overwrite a user edit.
   * **Validates: Requirements 1.5**
   *
   * Once the user types something into Notes, a re-render with the same
   * `settings` object must not clobber that value. The effect's `prev || ...`
   * guard plus the stable dependency array enforces "applied at most once
   * per mount when there is a prior user value".
   */
  it('Property 3b: stable settings re-render does not overwrite user edits', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim() !== ''),
        fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s.trim() !== ''),
        async (default_notes, prior_user_value) => {
          mockTenantSettings = buildSettings({
            default_notes_enabled: true,
            default_notes,
          })

          let container: HTMLElement | null = null
          let rerender: ((ui: ReactElement) => void) | null = null
          await act(async () => {
            const result = render(<QuoteCreate />)
            container = result.container
            rerender = result.rerender
          })
          await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
          })

          const editor = findNotesEditor(container!)

          // Simulate a user edit by overwriting innerHTML and dispatching an
          // input event — this is what a real user typing would trigger.
          await act(async () => {
            editor.innerHTML = prior_user_value
            editor.dispatchEvent(new Event('input', { bubbles: true }))
          })

          // Re-render with the SAME mockTenantSettings reference — the deps
          // (default_notes_enabled, default_notes) have not changed, so the
          // pre-fill effect should not run again, and the `prev || ...` guard
          // preserves the user value if it did.
          await act(async () => {
            rerender!(<QuoteCreate />)
          })
          await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
          })

          const editorAfter = findNotesEditor(container!)
          expect(editorAfter.innerHTML).toBe(normaliseHtml(prior_user_value))

          cleanup()
        },
      ),
      { numRuns: 100 },
    )
  })
})
