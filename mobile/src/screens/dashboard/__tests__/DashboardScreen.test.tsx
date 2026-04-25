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
  user: { id: '1', name: 'Test User', email: 'test@example.com', role: 'owner', org_id: 'org1' },
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
let mockModulesReturn: Record<string, unknown> = {
  modules: [],
  enabledModules: ['jobs', 'quotes', 'bookings', 'time_tracking'],
  isLoading: false,
  error: null,
  isModuleEnabled: (slug: string) =>
    ['jobs', 'quotes', 'bookings', 'time_tracking'].includes(slug),
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

const defaultSummary = {
  revenue: 15000,
  outstanding_invoices: 5,
  outstanding_amount: 3200,
  jobs_in_progress: 3,
  upcoming_bookings: 2,
  clocked_in: false,
  current_time_entry_id: null,
}

function mockDashboardResponse(data = defaultSummary) {
  mockGet.mockResolvedValue({ data })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DashboardScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset to defaults
    mockAuthReturn = {
      user: { id: '1', name: 'Test User', email: 'test@example.com', role: 'owner', org_id: 'org1' },
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
      enabledModules: ['jobs', 'quotes', 'bookings', 'time_tracking'],
      isLoading: false,
      error: null,
      isModuleEnabled: (slug: string) =>
        ['jobs', 'quotes', 'bookings', 'time_tracking'].includes(slug),
      tradeFamily: null,
      refetch: vi.fn(),
    }
  })

  // -------------------------------------------------------------------------
  // Requirement 6.1 — Summary card rendering
  // -------------------------------------------------------------------------

  it('renders summary cards with data from the API', async () => {
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('revenue-value')).toHaveTextContent('$15,000')
    })
    expect(screen.getByTestId('outstanding-count')).toHaveTextContent('5')
    expect(screen.getByTestId('jobs-count')).toHaveTextContent('3')
    expect(screen.getByTestId('bookings-count')).toHaveTextContent('2')
  })

  it('displays welcome message with user name', async () => {
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText(/Welcome, Test User/)).toBeInTheDocument()
    })
  })

  it('shows loading spinner while fetching data', async () => {
    // Never resolve the API call
    mockGet.mockReturnValue(new Promise(() => {}))
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows error banner when API call fails', async () => {
    mockGet.mockRejectedValue(new Error('Network error'))
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to load dashboard data')
    })
  })

  it('handles missing/null API response fields with safe defaults', async () => {
    mockGet.mockResolvedValue({ data: {} })
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('revenue-value')).toHaveTextContent('$0')
    })
    expect(screen.getByTestId('outstanding-count')).toHaveTextContent('0')
  })

  // -------------------------------------------------------------------------
  // Requirement 6.3 — Quick action filtering by ModuleGate
  // -------------------------------------------------------------------------

  it('renders all quick action buttons when all modules are enabled', async () => {
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /New Invoice/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /New Quote/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New Job Card/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New Customer/i })).toBeInTheDocument()
  })

  it('hides New Quote button when quotes module is disabled', async () => {
    mockModulesReturn = {
      ...mockModulesReturn,
      enabledModules: ['jobs', 'bookings', 'time_tracking'],
      isModuleEnabled: (slug: string) =>
        ['jobs', 'bookings', 'time_tracking'].includes(slug),
    }
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /New Invoice/i })).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /New Quote/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New Job Card/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New Customer/i })).toBeInTheDocument()
  })

  it('hides New Job Card button when jobs module is disabled', async () => {
    mockModulesReturn = {
      ...mockModulesReturn,
      enabledModules: ['quotes', 'bookings', 'time_tracking'],
      isModuleEnabled: (slug: string) =>
        ['quotes', 'bookings', 'time_tracking'].includes(slug),
    }
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /New Invoice/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /New Quote/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New Job Card/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New Customer/i })).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Requirement 6.4 — Summary card navigation
  // -------------------------------------------------------------------------

  it('navigates to invoices when revenue card is tapped', async () => {
    mockDashboardResponse()
    const user = userEvent.setup()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('revenue-value')).toBeInTheDocument()
    })

    // The revenue card is the one containing the revenue value
    const revenueCard = screen.getByTestId('revenue-value').closest('[role="button"]')!
    await user.click(revenueCard)

    expect(mockNavigate).toHaveBeenCalledWith('/invoices')
  })

  // -------------------------------------------------------------------------
  // Requirement 6.5 — Quick action navigation
  // -------------------------------------------------------------------------

  it('navigates to invoice creation when New Invoice is tapped', async () => {
    mockDashboardResponse()
    const user = userEvent.setup()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /New Invoice/i })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /New Invoice/i }))

    expect(mockNavigate).toHaveBeenCalledWith('/invoices/new')
  })

  it('navigates to customer creation when New Customer is tapped', async () => {
    mockDashboardResponse()
    const user = userEvent.setup()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /New Customer/i })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /New Customer/i }))

    expect(mockNavigate).toHaveBeenCalledWith('/customers/new')
  })

  // -------------------------------------------------------------------------
  // Requirement 6.2 — Pull-to-refresh
  // -------------------------------------------------------------------------

  it('calls the dashboard API on initial load', async () => {
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        '/api/v1/dashboard/branch-metrics',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      )
    })
  })

  // -------------------------------------------------------------------------
  // Requirement 19.1 — Clock in/out button
  // -------------------------------------------------------------------------

  it('renders Clock In button when time_tracking module is enabled', async () => {
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Clock In/i })).toBeInTheDocument()
    })
  })

  it('hides Clock In button when time_tracking module is disabled', async () => {
    mockModulesReturn = {
      ...mockModulesReturn,
      enabledModules: ['jobs', 'quotes', 'bookings'],
      isModuleEnabled: (slug: string) =>
        ['jobs', 'quotes', 'bookings'].includes(slug),
    }
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('revenue-value')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Clock In/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Clock Out/i })).not.toBeInTheDocument()
  })

  it('shows Clock Out button when user is already clocked in', async () => {
    mockGet.mockResolvedValue({
      data: { ...defaultSummary, clocked_in: true },
    })
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Clock Out/i })).toBeInTheDocument()
    })
  })

  it('calls clock-in API and toggles button text', async () => {
    mockDashboardResponse()
    mockPost.mockResolvedValue({ data: {} })
    const user = userEvent.setup()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Clock In/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Clock In/i }))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/api/v2/time-entries/clock-in')
      expect(screen.getByRole('button', { name: /Clock Out/i })).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Kiosk role — hides revenue/outstanding cards
  // -------------------------------------------------------------------------

  it('hides revenue and outstanding cards for kiosk role', async () => {
    mockAuthReturn = {
      ...mockAuthReturn,
      user: { id: '1', name: 'Kiosk', email: 'kiosk@example.com', role: 'kiosk', org_id: 'org1' },
      isKiosk: true,
    }
    mockDashboardResponse()
    const DashboardScreen = (await import('../DashboardScreen')).default
    render(<DashboardScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      // Jobs card should still be visible
      expect(screen.getByTestId('jobs-count')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('revenue-value')).not.toBeInTheDocument()
    expect(screen.queryByTestId('outstanding-count')).not.toBeInTheDocument()
  })
})
