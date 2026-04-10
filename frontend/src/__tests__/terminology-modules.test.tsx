import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 4.1, 4.6, 6.2
 */

/* ------------------------------------------------------------------ */
/*  Mock API client                                                    */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
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

import apiClient from '@/api/client'
import { TerminologyProvider, useTerm } from '@/contexts/TerminologyContext'
import { TermLabel } from '@/components/common/TermLabel'
import { ModuleProvider } from '@/contexts/ModuleContext'
import { ModuleGate } from '@/components/common/ModuleGate'
import { FeatureFlagProvider } from '@/contexts/FeatureFlagContext'
import { FeatureGate } from '@/components/common/FeatureGate'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function TermTestConsumer({ termKey, fallback }: { termKey: string; fallback: string }) {
  const label = useTerm(termKey, fallback)
  return <span data-testid="term-output">{label}</span>
}

/* ------------------------------------------------------------------ */
/*  TermLabel tests (13.9)                                             */
/* ------------------------------------------------------------------ */

describe('TermLabel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders trade-specific text from terminology map', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { asset_label: 'Device', work_unit_label: 'Work Order' },
    })

    render(
      <TerminologyProvider>
        <TermLabel termKey="asset_label" fallback="Asset" />
      </TerminologyProvider>,
    )

    expect(await screen.findByText('Device')).toBeInTheDocument()
  })

  it('renders fallback when term key is not in the map', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { asset_label: 'Device' },
    })

    render(
      <TerminologyProvider>
        <TermLabel termKey="unknown_key" fallback="Default Label" />
      </TerminologyProvider>,
    )

    expect(await screen.findByText('Default Label')).toBeInTheDocument()
  })

  it('renders fallback when terminology API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))

    render(
      <TerminologyProvider>
        <TermLabel termKey="asset_label" fallback="Asset" />
      </TerminologyProvider>,
    )

    // Should show fallback since API failed
    expect(await screen.findByText('Asset')).toBeInTheDocument()
  })

  it('renders with custom element via as prop', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { customer_label: 'Client' },
    })

    render(
      <TerminologyProvider>
        <TermLabel termKey="customer_label" fallback="Customer" as="h2" />
      </TerminologyProvider>,
    )

    const heading = await screen.findByText('Client')
    expect(heading.tagName).toBe('H2')
  })

  it('useTerm hook returns correct trade-specific term', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { work_unit_label: 'Booking' },
    })

    render(
      <TerminologyProvider>
        <TermTestConsumer termKey="work_unit_label" fallback="Job" />
      </TerminologyProvider>,
    )

    const output = await screen.findByTestId('term-output')
    expect(output).toHaveTextContent('Booking')
  })
})

/* ------------------------------------------------------------------ */
/*  ModuleGate tests (13.10)                                           */
/* ------------------------------------------------------------------ */

describe('ModuleGate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders children when module is enabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: [
        { slug: 'inventory', display_name: 'Inventory', description: '', category: 'core', is_core: false, is_enabled: true },
      ],
    })

    render(
      <ModuleProvider>
        <ModuleGate module="inventory">
          <div data-testid="inventory-content">Inventory Content</div>
        </ModuleGate>
      </ModuleProvider>,
    )

    expect(await screen.findByTestId('inventory-content')).toBeInTheDocument()
  })

  it('hides children when module is disabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: [
        { slug: 'inventory', display_name: 'Inventory', description: '', category: 'core', is_core: false, is_enabled: false },
      ],
    })

    render(
      <ModuleProvider>
        <ModuleGate module="inventory">
          <div data-testid="inventory-content">Inventory Content</div>
        </ModuleGate>
      </ModuleProvider>,
    )

    // Wait for the API call to resolve
    await screen.findByText((_content, element) => element === document.body, {}, { timeout: 100 }).catch(() => {})

    expect(screen.queryByTestId('inventory-content')).not.toBeInTheDocument()
  })

  it('hides children when module is not in the list at all', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: [
        { slug: 'invoicing', display_name: 'Invoicing', description: '', category: 'core', is_core: true, is_enabled: true },
      ],
    })

    render(
      <ModuleProvider>
        <ModuleGate module="pos">
          <div data-testid="pos-content">POS Content</div>
        </ModuleGate>
      </ModuleProvider>,
    )

    await screen.findByText((_content, element) => element === document.body, {}, { timeout: 100 }).catch(() => {})

    expect(screen.queryByTestId('pos-content')).not.toBeInTheDocument()
  })

  it('renders fallback when module is disabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: [
        { slug: 'inventory', display_name: 'Inventory', description: '', category: 'core', is_core: false, is_enabled: false },
      ],
    })

    render(
      <ModuleProvider>
        <ModuleGate module="inventory" fallback={<div data-testid="fallback">Module not available</div>}>
          <div data-testid="inventory-content">Inventory Content</div>
        </ModuleGate>
      </ModuleProvider>,
    )

    expect(await screen.findByTestId('fallback')).toBeInTheDocument()
    expect(screen.queryByTestId('inventory-content')).not.toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  FeatureGate tests                                                  */
/* ------------------------------------------------------------------ */

describe('FeatureGate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders children when flag is enabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { new_dashboard: true },
    })

    render(
      <FeatureFlagProvider>
        <FeatureGate flag="new_dashboard">
          <div data-testid="new-dashboard">New Dashboard</div>
        </FeatureGate>
      </FeatureFlagProvider>,
    )

    expect(await screen.findByTestId('new-dashboard')).toBeInTheDocument()
  })

  it('hides children when flag is disabled', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { new_dashboard: false },
    })

    render(
      <FeatureFlagProvider>
        <FeatureGate flag="new_dashboard">
          <div data-testid="new-dashboard">New Dashboard</div>
        </FeatureGate>
      </FeatureFlagProvider>,
    )

    await screen.findByText((_content, element) => element === document.body, {}, { timeout: 100 }).catch(() => {})

    expect(screen.queryByTestId('new-dashboard')).not.toBeInTheDocument()
  })
})
