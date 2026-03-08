import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React, { Suspense } from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

/**
 * Integration tests verifying the three context providers work together:
 * - ModuleRouter renders correct lazy components for enabled modules
 * - ModuleRouter redirects for disabled modules
 * - FeatureFlagContext's FeatureGate shows/hides children based on flag state
 * - TerminologyContext's useTerm returns the correct term or fallback
 *
 * Validates: Requirements 18.4
 */

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
    isLoading: false,
    mfaPending: false,
    mfaSessionToken: null,
    login: vi.fn(),
    loginWithGoogle: vi.fn(),
    loginWithPasskey: vi.fn(),
    logout: vi.fn(),
    completeMfa: vi.fn(),
    isGlobalAdmin: false,
    isOrgAdmin: true,
    isSalesperson: false,
  }),
}))

// Mock TenantContext so lazy-loaded page components don't crash
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({
    settings: {
      branding: { name: 'Test Org', logo_url: null, primary_colour: '#2563eb', secondary_colour: '#1e40af', address: null, phone: null, email: null },
      gst: { gst_number: null, gst_percentage: 15, gst_inclusive: true },
      invoice: { prefix: 'INV-', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  TenantProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import apiClient from '@/api/client'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { TerminologyProvider, useTerm } from '@/contexts/TerminologyContext'
import { FeatureGate } from '@/components/common/FeatureGate'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const mockGet = apiClient.get as ReturnType<typeof vi.fn>

function makeModuleData(slugs: string[], enabledSlugs: string[]) {
  return slugs.map((slug) => ({
    slug,
    display_name: slug,
    description: '',
    category: 'core',
    is_core: false,
    is_enabled: enabledSlugs.includes(slug),
  }))
}

function setupMocks({
  modules = [] as string[],
  enabledModules = [] as string[],
  flags = {} as Record<string, boolean>,
  terms = {} as Record<string, string>,
}: {
  modules?: string[]
  enabledModules?: string[]
  flags?: Record<string, boolean>
  terms?: Record<string, string>
}) {
  mockGet.mockImplementation((url: string) => {
    if (url === '/modules') {
      return Promise.resolve({ data: makeModuleData(modules, enabledModules) })
    }
    if (url === '/api/v2/flags') {
      return Promise.resolve({ data: flags })
    }
    if (url === '/v2/terminology') {
      return Promise.resolve({ data: terms })
    }
    // Catch-all for any other API calls from lazy-loaded components
    if (url === '/org/settings') {
      return Promise.resolve({
        data: {
          name: 'Test Org', logo_url: null, primary_colour: '#2563eb',
          secondary_colour: '#1e40af', address: null, phone: null, email: null,
          gst_number: null, gst_percentage: 15, gst_inclusive: true,
          invoice_prefix: 'INV-', default_due_days: 14,
          payment_terms_text: null, terms_and_conditions: null,
        },
      })
    }
    return Promise.resolve({ data: [] })
  })
}

function renderWithAllProviders(
  ui: React.ReactElement,
  { initialEntries = ['/'] }: { initialEntries?: string[] } = {},
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <ModuleProvider>
        <FeatureFlagProvider>
          <TerminologyProvider>
            {ui}
          </TerminologyProvider>
        </FeatureFlagProvider>
      </ModuleProvider>
    </MemoryRouter>,
  )
}

/* ------------------------------------------------------------------ */
/*  1. ModuleRouter renders correct components for enabled modules     */
/* ------------------------------------------------------------------ */

describe('ModuleRouter integration — enabled modules', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('renders module route when module is enabled and flag is true', async () => {
    setupMocks({
      modules: ['kitchen_display', 'loyalty'],
      enabledModules: ['kitchen_display'],
      flags: { kitchen_display: true },
    })

    const { ModuleRouter } = await import('@/router/ModuleRouter')

    renderWithAllProviders(
      <Routes>
        <Route path="/*" element={
          <Suspense fallback={<div data-testid="suspense-fallback">Loading...</div>}>
            <ModuleRouter />
          </Suspense>
        } />
      </Routes>,
      { initialEntries: ['/kitchen'] },
    )

    // The kitchen route should render (either loading fallback from Suspense or actual content)
    // It should NOT show feature-not-available since the module is enabled
    await waitFor(() => {
      expect(screen.queryByTestId('feature-not-available')).not.toBeInTheDocument()
    }, { timeout: 3000 })
  })

  it('renders core routes regardless of module state', async () => {
    setupMocks({
      modules: [],
      enabledModules: [],
      flags: {},
    })

    const { ModuleRouter } = await import('@/router/ModuleRouter')

    renderWithAllProviders(
      <Routes>
        <Route path="/*" element={
          <Suspense fallback={<div data-testid="suspense-fallback">Loading...</div>}>
            <ModuleRouter />
          </Suspense>
        } />
      </Routes>,
      { initialEntries: ['/dashboard'] },
    )

    // Dashboard is a core route — should not show feature-not-available
    await waitFor(() => {
      expect(screen.queryByTestId('feature-not-available')).not.toBeInTheDocument()
    }, { timeout: 3000 })
  })
})

/* ------------------------------------------------------------------ */
/*  2. ModuleRouter redirects for disabled modules                     */
/* ------------------------------------------------------------------ */

describe('ModuleRouter integration — disabled modules', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('shows feature-not-available page for disabled module routes', async () => {
    setupMocks({
      modules: ['kitchen_display'],
      enabledModules: [], // kitchen_display is NOT enabled
      flags: {},
    })

    const { ModuleRouter } = await import('@/router/ModuleRouter')

    renderWithAllProviders(
      <Routes>
        <Route path="/*" element={
          <Suspense fallback={<div>Loading...</div>}>
            <ModuleRouter />
          </Suspense>
        } />
      </Routes>,
      { initialEntries: ['/kitchen'] },
    )

    expect(
      await screen.findByTestId('feature-not-available', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })

  it('shows feature-not-available with back-to-dashboard link', async () => {
    setupMocks({
      modules: ['loyalty'],
      enabledModules: [], // loyalty NOT enabled
      flags: {},
    })

    const { ModuleRouter } = await import('@/router/ModuleRouter')

    renderWithAllProviders(
      <Routes>
        <Route path="/*" element={
          <Suspense fallback={<div>Loading...</div>}>
            <ModuleRouter />
          </Suspense>
        } />
      </Routes>,
      { initialEntries: ['/loyalty'] },
    )

    expect(
      await screen.findByTestId('feature-not-available', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('back-to-dashboard-link')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  3. FeatureFlagContext correctly gates sub-features                  */
/* ------------------------------------------------------------------ */

describe('FeatureFlagContext + FeatureGate integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows children when flag is enabled', async () => {
    setupMocks({ flags: { beta_feature: true } })

    renderWithAllProviders(
      <FeatureGate flag="beta_feature">
        <div data-testid="gated-content">Beta Content</div>
      </FeatureGate>,
    )

    expect(await screen.findByTestId('gated-content')).toBeInTheDocument()
  })

  it('hides children when flag is disabled', async () => {
    setupMocks({ flags: { beta_feature: false } })

    renderWithAllProviders(
      <FeatureGate flag="beta_feature">
        <div data-testid="gated-content">Beta Content</div>
      </FeatureGate>,
    )

    await waitFor(() => {
      expect(screen.queryByTestId('gated-content')).not.toBeInTheDocument()
    })
  })

  it('hides children when flag key does not exist', async () => {
    setupMocks({ flags: { other_flag: true } })

    renderWithAllProviders(
      <FeatureGate flag="nonexistent_flag">
        <div data-testid="gated-content">Should not show</div>
      </FeatureGate>,
    )

    await waitFor(() => {
      expect(screen.queryByTestId('gated-content')).not.toBeInTheDocument()
    })
  })

  it('renders fallback when flag is disabled', async () => {
    setupMocks({ flags: { premium: false } })

    renderWithAllProviders(
      <FeatureGate flag="premium" fallback={<div data-testid="upgrade-prompt">Upgrade</div>}>
        <div data-testid="premium-content">Premium</div>
      </FeatureGate>,
    )

    await waitFor(() => {
      expect(screen.queryByTestId('premium-content')).not.toBeInTheDocument()
      expect(screen.getByTestId('upgrade-prompt')).toBeInTheDocument()
    })
  })
})

/* ------------------------------------------------------------------ */
/*  4. TerminologyContext correctly substitutes labels                  */
/* ------------------------------------------------------------------ */

function TermConsumer({ termKey, fallback }: { termKey: string; fallback: string }) {
  const label = useTerm(termKey, fallback)
  return <span data-testid="term-output">{label}</span>
}

describe('TerminologyContext + useTerm integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns trade-specific term when key exists', async () => {
    setupMocks({ terms: { asset_label: 'Vehicle', customer_label: 'Client' } })

    renderWithAllProviders(
      <TermConsumer termKey="asset_label" fallback="Asset" />,
    )

    const output = await screen.findByTestId('term-output')
    expect(output).toHaveTextContent('Vehicle')
  })

  it('returns fallback when term key is not in the map', async () => {
    setupMocks({ terms: { asset_label: 'Vehicle' } })

    renderWithAllProviders(
      <TermConsumer termKey="missing_key" fallback="Default Label" />,
    )

    const output = await screen.findByTestId('term-output')
    expect(output).toHaveTextContent('Default Label')
  })

  it('returns fallback when terminology API fails', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url === '/v2/terminology') {
        return Promise.reject(new Error('Network error'))
      }
      if (url === '/modules') {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: {} })
    })

    renderWithAllProviders(
      <TermConsumer termKey="asset_label" fallback="Asset" />,
    )

    const output = await screen.findByTestId('term-output')
    expect(output).toHaveTextContent('Asset')
  })

  it('substitutes multiple terms correctly in the same render', async () => {
    setupMocks({
      terms: {
        asset_label: 'Device',
        work_unit_label: 'Work Order',
        customer_label: 'Client',
      },
    })

    function MultiTermConsumer() {
      const asset = useTerm('asset_label', 'Asset')
      const work = useTerm('work_unit_label', 'Job')
      const customer = useTerm('customer_label', 'Customer')
      return (
        <div>
          <span data-testid="term-asset">{asset}</span>
          <span data-testid="term-work">{work}</span>
          <span data-testid="term-customer">{customer}</span>
        </div>
      )
    }

    renderWithAllProviders(<MultiTermConsumer />)

    expect(await screen.findByTestId('term-asset')).toHaveTextContent('Device')
    expect(screen.getByTestId('term-work')).toHaveTextContent('Work Order')
    expect(screen.getByTestId('term-customer')).toHaveTextContent('Client')
  })
})
