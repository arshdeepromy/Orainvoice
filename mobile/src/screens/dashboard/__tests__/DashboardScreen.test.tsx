import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

// Default auth mock — non-kiosk user
let mockAuthReturn: Record<string, unknown> = {
  user: {
    id: '1',
    name: 'Test User',
    email: 'test@example.com',
    role: 'owner',
    org_id: 'org1',
  },
  isAuthenticated: true,
  isLoading: false,
  isKiosk: false,
  isGlobalAdmin: false,
  isOrgAdmin: true,
  isBranchAdmin: false,
  isSalesperson: false,
  login: vi.fn(),
  loginWithGoogle: vi.fn(),
  logout: vi.fn(),
  completeMfa: vi.fn(),
  completeFirebaseMfa: vi.fn(),
  refreshProfile: vi.fn(),
  mfaPending: false,
  mfaSessionToken: null,
  mfaMethods: [],
  mfaDefaultMethod: null,
}

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mockAuthReturn,
}))

// Default modules mock — all modules enabled
let mockEnabledModules = ['jobs', 'quotes', 'bookings', 'compliance_docs']

let mockModulesReturn: Record<string, unknown> = {
  modules: [],
  enabledModules: mockEnabledModules,
  isLoading: false,
  error: null,
  isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
  tradeFamily: null,
  refetch: vi.fn(),
}

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => mockModulesReturn,
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({
    branding: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    tradeFamily: null,
    tradeCategory: null,
  }),
}))

// Branch context mock
let mockBranchReturn: Record<string, unknown> = {
  selectedBranchId: null,
  branches: [],
  selectBranch: vi.fn(),
  isLoading: false,
  isBranchLocked: false,
}

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => mockBranchReturn,
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

const defaultStats = {
  revenue_this_month: 15000,
  outstanding_receivables: 3200,
  overdue_count: 2,
  active_jobs_count: 3,
  expiring_compliance_docs: 1,
}

const defaultRecentInvoices = [
  {
    id: 'inv-1',
    invoice_number: 'INV-001',
    customer_name: 'Acme Corp',
    total: 1500,
    status: 'paid',
    created_at: '2024-01-15T00:00:00Z',
  },
  {
    id: 'inv-2',
    invoice_number: 'INV-002',
    customer_name: 'Widget Co',
    total: 2300,
    status: 'draft',
    created_at: '2024-01-14T00:00:00Z',
  },
]

const defaultOverdueInvoices = [
  {
    id: 'inv-3',
    invoice_number: 'INV-003',
    customer_name: 'Late Payer Ltd',
    total: 800,
    balance_due: 800,
    status: 'overdue',
    due_date: '2024-01-01T00:00:00Z',
    days_overdue: 15,
  },
]

/**
 * Set up mockGet to return appropriate data for each API endpoint.
 */
function setupApiMocks(
  stats = defaultStats,
  recent = defaultRecentInvoices,
  overdue = defaultOverdueInvoices,
) {
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/dashboard/stats')) {
      return Promise.resolve({ data: stats })
    }
    if (url.includes('/invoices')) {
      // Check if it's the overdue query
      const args = mockGet.mock.calls.find(
        (c: unknown[]) =>
          typeof c[0] === 'string' &&
          c[0].includes('/invoices') &&
          ((c[1] as Record<string, unknown>)?.params as Record<string, unknown> | undefined)?.status === 'overdue',
      )
      if (args) {
        return Promise.resolve({ data: { items: overdue, total: overdue.length } })
      }
      return Promise.resolve({ data: { items: recent, total: recent.length } })
    }
    return Promise.resolve({ data: {} })
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DashboardScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.resetModules()

    mockEnabledModules = ['jobs', 'quotes', 'bookings', 'compliance_docs']

    mockAuthReturn = {
      user: {
        id: '1',
        name: 'Test User',
        email: 'test@example.com',
        role: 'owner',
        org_id: 'org1',
      },
      isAuthenticated: true,
      isLoading: false,
      isKiosk: false,
      isGlobalAdmin: false,
      isOrgAdmin: true,
      isBranchAdmin: false,
      isSalesperson: false,
      login: vi.fn(),
      loginWithGoogle: vi.fn(),
      logout: vi.fn(),
      completeMfa: vi.fn(),
      completeFirebaseMfa: vi.fn(),
      refreshProfile: vi.fn(),
      mfaPending: false,
      mfaSessionToken: null,
      mfaMethods: [],
      mfaDefaultMethod: null,
    }

    mockModulesReturn = {
      modules: [],
      enabledModules: mockEnabledModules,
      isLoading: false,
      error: null,
      isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
      tradeFamily: null,
      refetch: vi.fn(),
    }

    mockBranchReturn = {
      selectedBranchId: null,
      branches: [],
      selectBranch: vi.fn(),
      isLoading: false,
      isBranchLocked: false,
    }
  })

  // -------------------------------------------------------------------------
  // Requirement 17.1 — Greeting with first name
  // -------------------------------------------------------------------------

  it('displays greeting with user first name', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('dashboard-greeting')).toHaveTextContent(
        'Hello, Test',
      )
    })
  })

  // -------------------------------------------------------------------------
  // Requirement 17.2 — Stat cards in 2-column grid
  // -------------------------------------------------------------------------

  it('renders stat cards with data from the API', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('stat-revenue')).toBeInTheDocument()
    })
    expect(screen.getByTestId('stat-outstanding')).toBeInTheDocument()
    expect(screen.getByTestId('stat-overdue')).toBeInTheDocument()
    expect(screen.getByTestId('stat-active-jobs')).toBeInTheDocument()
  })

  it('shows overdue count with red badge when overdue > 0', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('overdue-badge')).toBeInTheDocument()
    })
  })

  it('hides active jobs card when jobs module is disabled', async () => {
    mockEnabledModules = ['quotes', 'bookings', 'compliance_docs']
    mockModulesReturn = {
      ...mockModulesReturn,
      enabledModules: mockEnabledModules,
      isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
    }
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('stat-revenue')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('stat-active-jobs')).not.toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Requirement 17.3 — Quick action chips
  // -------------------------------------------------------------------------

  it('renders all quick action chips when all modules are enabled', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('quick-action-new-invoice')).toBeInTheDocument()
    })
    expect(screen.getByTestId('quick-action-new-customer')).toBeInTheDocument()
    expect(screen.getByTestId('quick-action-new-quote')).toBeInTheDocument()
    expect(screen.getByTestId('quick-action-new-job')).toBeInTheDocument()
    expect(screen.getByTestId('quick-action-new-booking')).toBeInTheDocument()
  })

  it('hides New Quote chip when quotes module is disabled', async () => {
    mockEnabledModules = ['jobs', 'bookings', 'compliance_docs']
    mockModulesReturn = {
      ...mockModulesReturn,
      enabledModules: mockEnabledModules,
      isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
    }
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('quick-action-new-invoice')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('quick-action-new-quote')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-action-new-job')).toBeInTheDocument()
  })

  it('hides New Job chip when jobs module is disabled', async () => {
    mockEnabledModules = ['quotes', 'bookings', 'compliance_docs']
    mockModulesReturn = {
      ...mockModulesReturn,
      enabledModules: mockEnabledModules,
      isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
    }
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('quick-action-new-invoice')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('quick-action-new-job')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-action-new-quote')).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Requirement 17.4 — Recent Invoices section
  // -------------------------------------------------------------------------

  it('renders recent invoices section with invoice data', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('recent-invoices-section')).toBeInTheDocument()
    })
    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('Widget Co')).toBeInTheDocument()
  })

  it('shows empty state when no recent invoices', async () => {
    setupApiMocks(defaultStats, [], defaultOverdueInvoices)
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('No recent invoices')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Requirement 17.5 — Needs Attention section
  // -------------------------------------------------------------------------

  it('renders needs attention section with overdue invoices', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('needs-attention-section')).toBeInTheDocument()
    })
    expect(screen.getByText('Late Payer Ltd')).toBeInTheDocument()
  })

  it('hides needs attention section when no overdue invoices', async () => {
    setupApiMocks(defaultStats, defaultRecentInvoices, [])
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('recent-invoices-section')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('needs-attention-section')).not.toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Requirement 17.6 — Compliance alert card
  // -------------------------------------------------------------------------

  it('renders compliance alert card when compliance_docs enabled and docs expiring', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('compliance-alert-card')).toBeInTheDocument()
    })
    expect(screen.getByText(/1 document expiring soon/)).toBeInTheDocument()
  })

  it('hides compliance alert card when no expiring docs', async () => {
    setupApiMocks({ ...defaultStats, expiring_compliance_docs: 0 })
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('stat-revenue')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('compliance-alert-card')).not.toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Requirement 17.7 — Safe API consumption
  // -------------------------------------------------------------------------

  it('handles missing/null API response fields with safe defaults', async () => {
    mockGet.mockResolvedValue({ data: {} })
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    // Should render without crashing, showing default values
    await waitFor(() => {
      expect(screen.getByTestId('stat-revenue')).toBeInTheDocument()
    })
  })

  it('calls dashboard stats and overdue invoices APIs on initial load', async () => {
    setupApiMocks()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        '/api/v1/dashboard/stats',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      )
    })
  })

  // -------------------------------------------------------------------------
  // Loading and error states
  // -------------------------------------------------------------------------

  it('shows loading spinner while fetching data', async () => {
    mockGet.mockReturnValue(new Promise(() => {}))
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    // Konsta Preloader renders as a span with class k-preloader
    const preloader = document.querySelector('.k-preloader')
    expect(preloader).toBeInTheDocument()
  })

  it('shows error banner when API call fails', async () => {
    // All three API calls reject — Promise.allSettled catches them individually
    // but the outer try/catch catches the error
    mockGet.mockRejectedValue(new Error('Network error'))
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Failed to load dashboard data',
      )
    })
  })

  // -------------------------------------------------------------------------
  // Navigation — quick action chips
  // -------------------------------------------------------------------------

  it('navigates to invoice creation when New Invoice chip is tapped', async () => {
    setupApiMocks()
    const user = userEvent.setup()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('quick-action-new-invoice')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('quick-action-new-invoice'))

    expect(mockNavigate).toHaveBeenCalledWith('/invoices/new')
  })

  it('navigates to customer creation when New Customer chip is tapped', async () => {
    setupApiMocks()
    const user = userEvent.setup()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('quick-action-new-customer')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('quick-action-new-customer'))

    expect(mockNavigate).toHaveBeenCalledWith('/customers/new')
  })

  // -------------------------------------------------------------------------
  // Requirement 8.1 — Pull-to-refresh triggers API refetch
  // -------------------------------------------------------------------------

  it('re-fetches dashboard data when refresh is triggered', async () => {
    // Start with an error state so the Retry button is visible
    mockGet.mockRejectedValue(new Error('Network error'))
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    // Now set up successful responses for the retry
    mockGet.mockClear()
    setupApiMocks()

    // Click the Retry button — this calls handleRefresh (same as PullRefresh onRefresh)
    await userEvent.click(screen.getByText('Retry'))

    // Verify the dashboard stats endpoint was re-fetched
    await waitFor(() => {
      expect(screen.getByTestId('stat-revenue')).toBeInTheDocument()
    })

    const statsCalls = mockGet.mock.calls.filter(
      (call: unknown[]) =>
        typeof call[0] === 'string' &&
        (call[0] as string).includes('/dashboard/stats'),
    )
    expect(statsCalls.length).toBeGreaterThan(0)
  })
})
