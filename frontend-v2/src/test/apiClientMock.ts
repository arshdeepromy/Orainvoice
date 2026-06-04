import { vi } from 'vitest'

/**
 * Mock for `@/api/client`, used by the shell unit tests (TopBar / OrgSwitcher /
 * OrgLayout) so the REAL context providers (Auth/Tenant/Module/FeatureFlag/
 * Branch) run end-to-end against deterministic, realistic backend response
 * shapes instead of a live server.
 *
 * The shapes mirror the actual endpoints the contexts call:
 *   GET /modules        (baseURL /api/v2) → { modules: [...], total }
 *   GET /org/settings                     → org branding + GST + invoice + trade
 *   GET /org/branches                     → { branches: [...] }
 *   GET /auth/me                          → { first_name, last_name, branch_ids }
 *   GET /api/v2/flags                     → { flags: [...] }
 *   GET /public/branding                  → platform branding
 *
 * Token helpers reproduce the real client's module-level token state + JWT
 * validity check so AuthProvider's session-restore path runs unchanged.
 */

let accessToken: string | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

export function isAccessTokenValid(): boolean {
  if (!accessToken) return false
  try {
    const base64 = accessToken.split('.')[1]
    const payload = JSON.parse(atob(base64.replace(/-/g, '+').replace(/_/g, '/')))
    return payload.exp * 1000 > Date.now() + 60_000
  } catch {
    return false
  }
}

export function doTokenRefresh(): Promise<string | null> {
  return Promise.resolve(accessToken)
}

/** Modules the shell gates against — all enabled so gated nav/actions render. */
const MODULE_SLUGS = [
  'quotes', 'recurring_invoices', 'pos', 'jobs', 'bookings', 'scheduling',
  'branch_management', 'projects', 'time_tracking', 'vehicles', 'staff',
  'inventory', 'purchase_orders', 'accounting', 'expenses',
]

function modulesPayload() {
  return MODULE_SLUGS.map((slug) => ({
    slug,
    display_name: slug,
    description: '',
    category: 'core',
    is_core: false,
    is_enabled: true,
  }))
}

const orgSettingsPayload = {
  name: 'Kerikeri Motors',
  org_name: 'Kerikeri Motors',
  logo_url: null,
  primary_colour: '#2F62F0',
  secondary_colour: '#2450D0',
  address: '12 Kerikeri Rd',
  phone: '09 555 0100',
  email: 'hello@kerikerimotors.test',
  gst_number: '123-456-789',
  gst_percentage: 15,
  gst_inclusive: true,
  invoice_prefix: 'INV',
  default_due_days: 14,
  payment_terms_text: null,
  terms_and_conditions: null,
  default_notes: null,
  default_notes_enabled: false,
  payment_terms_enabled: true,
  terms_and_conditions_enabled: true,
  trade_family: 'automotive-transport',
  trade_category: 'general-automotive',
  sidebar_display_mode: 'icon_and_name',
  address_country: 'NZ',
}

const branchesPayload = {
  branches: [
    { id: 'br-01', name: 'Kerikeri', address: null, phone: null, is_active: true },
    { id: 'br-02', name: 'Whangārei', address: null, phone: null, is_active: true },
  ],
}

const get = vi.fn(async (url: string) => {
  if (url === '/modules') return { data: { modules: modulesPayload(), total: MODULE_SLUGS.length } }
  if (url === '/org/settings') return { data: orgSettingsPayload }
  if (url === '/org/branches') return { data: branchesPayload }
  if (url === '/auth/me') return { data: { first_name: 'Preview', last_name: '', branch_ids: ['br-01', 'br-02'] } }
  if (url === '/api/v2/flags') return { data: { flags: [] } }
  if (url === '/public/branding') {
    return {
      data: {
        platform_name: 'OraInvoice',
        logo_url: null,
        dark_logo_url: null,
        favicon_url: null,
        primary_colour: '#2563EB',
        secondary_colour: '#1E40AF',
        support_email: null,
        terms_url: null,
        website_url: null,
        platform_theme: 'classic',
      },
    }
  }
  return { data: {} }
})

const post = vi.fn(async () => ({ data: {} }))

const apiClient = {
  get,
  post,
  interceptors: {
    request: { use: vi.fn(() => 0), eject: vi.fn() },
    response: { use: vi.fn(() => 0), eject: vi.fn() },
  },
}

export default apiClient
