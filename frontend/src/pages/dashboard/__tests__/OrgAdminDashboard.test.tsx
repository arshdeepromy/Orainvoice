/**
 * Unit tests for trade-family gating in OrgAdminDashboard.
 *
 * Requirements: 1.1, 1.2, 1.3
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ */
/*  Mocks — must be declared before imports that use them              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
  },
}))

let mockTradeFamily: string | null = null

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({
    settings: { branding: { name: 'Test Org' } },
    tradeFamily: mockTradeFamily,
    tradeCategory: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
    isLoading: false,
    mfaPending: false,
    mfaSessionToken: null,
    mfaMethods: [],
    mfaDefaultMethod: null,
    login: vi.fn(),
    loginWithGoogle: vi.fn(),
    loginWithPasskey: vi.fn(),
    logout: vi.fn(),
    completeMfa: vi.fn(),
    completeFirebaseMfa: vi.fn(),
    refreshProfile: vi.fn(),
    isGlobalAdmin: false,
    isOrgAdmin: true,
    isBranchAdmin: false,
    isSalesperson: false,
    isKiosk: false,
  }),
}))

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({
    selectedBranchId: null,
    branches: [],
    selectBranch: vi.fn(),
    isLoading: false,
    isBranchLocked: false,
  }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isEnabled: () => true,
    refetch: vi.fn(),
  }),
}))

// Mock the WidgetGrid to avoid rendering the full DnD + recharts tree
vi.mock('../widgets/WidgetGrid', () => ({
  WidgetGrid: ({ userId, branchId }: { userId: string; branchId: string | null }) => (
    <div data-testid="widget-grid" data-user-id={userId} data-branch-id={branchId ?? ''}>
      WidgetGrid
    </div>
  ),
}))

// Mock the useDashboardWidgets hook used by WidgetGrid
vi.mock('../widgets/useDashboardWidgets', () => ({
  useDashboardWidgets: () => ({
    data: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

import apiClient from '@/api/client'
import { OrgAdminDashboard } from '../OrgAdminDashboard'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderDashboard() {
  return render(
    <MemoryRouter>
      <OrgAdminDashboard />
    </MemoryRouter>,
  )
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('OrgAdminDashboard — trade-family gating', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: API returns minimal data so the dashboard renders past loading
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/reports/revenue') {
        return Promise.resolve({
          data: { total_revenue: 0, total_gst: 0, total_inclusive: 0, invoice_count: 0, average_invoice: 0, period_start: '', period_end: '' },
        })
      }
      if (url === '/reports/outstanding') {
        return Promise.resolve({
          data: { total_outstanding: 0, count: 0, invoices: [] },
        })
      }
      if (url === '/reports/storage') {
        return Promise.resolve({
          data: { used_bytes: 0, used_gb: 0, quota_gb: 10, usage_percent: 0 },
        })
      }
      if (url === '/dashboard/branch-metrics') {
        return Promise.resolve({ data: { metrics: [], totals: null } })
      }
      return Promise.resolve({ data: {} })
    })
  })

  it('renders WidgetGrid when tradeFamily is null (defaults to automotive)', async () => {
    mockTradeFamily = null
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByTestId('widget-grid')).toBeInTheDocument()
    })
  })

  it('renders WidgetGrid when tradeFamily is "automotive-transport"', async () => {
    mockTradeFamily = 'automotive-transport'
    renderDashboard()

    await waitFor(() => {
      expect(screen.getByTestId('widget-grid')).toBeInTheDocument()
    })
  })

  it('hides WidgetGrid when tradeFamily is "plumbing-gas"', async () => {
    mockTradeFamily = 'plumbing-gas'
    renderDashboard()

    await waitFor(() => {
      expect(screen.queryByTestId('widget-grid')).not.toBeInTheDocument()
    })
  })

  it('hides WidgetGrid when tradeFamily is "electrical"', async () => {
    mockTradeFamily = 'electrical'
    renderDashboard()

    await waitFor(() => {
      expect(screen.queryByTestId('widget-grid')).not.toBeInTheDocument()
    })
  })
})
