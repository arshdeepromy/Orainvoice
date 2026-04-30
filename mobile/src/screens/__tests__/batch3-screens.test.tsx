import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate, useSearchParams: () => [new URLSearchParams(), vi.fn()] }
})

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPatch = vi.fn()
const mockPut = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    patch: (...args: unknown[]) => mockPatch(...args),
    put: (...args: unknown[]) => mockPut(...args),
  },
}))

let mockEnabledModules = ['expenses', 'time_tracking', 'scheduling', 'pos']

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: mockEnabledModules,
    isLoading: false,
    error: null,
    isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
    tradeFamily: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', name: 'Test', email: 'test@test.com', role: 'owner', org_id: 'org1' },
    isAuthenticated: true,
    isLoading: false,
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

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ branding: null, isLoading: false, error: null, refetch: vi.fn(), tradeFamily: null, tradeCategory: null }),
}))

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

// ---------------------------------------------------------------------------
// Tests — Phase 7: Batch 3 Screens
// ---------------------------------------------------------------------------

describe('Phase 7 — Batch 3 Screens', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEnabledModules = ['expenses', 'time_tracking', 'scheduling', 'pos']
  })

  // ── 13.1 Expenses Screen ──────────────────────────────────────────

  describe('ExpenseListScreen', () => {
    it('renders expenses page with items', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'e1', description: 'Fuel', amount: 85.50, category: 'fuel', date: '2024-01-15', receipt_url: null },
          ],
          total: 1,
        },
      })

      const { default: ExpenseListScreen } = await import('@/screens/expenses/ExpenseListScreen')
      render(<ExpenseListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('expenses-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('expenses-list')).toBeInTheDocument()
      expect(screen.getByText('Fuel')).toBeInTheDocument()
    })

    it('hides content when expenses module is disabled', async () => {
      mockEnabledModules = ['time_tracking', 'scheduling', 'pos']
      mockGet.mockResolvedValue({ data: { items: [], total: 0 } })

      const { default: ExpenseListScreen } = await import('@/screens/expenses/ExpenseListScreen')
      render(<ExpenseListScreen />, { wrapper: Wrapper })

      expect(screen.queryByTestId('expenses-page')).not.toBeInTheDocument()
    })
  })

  // ── 13.2 Time Tracking Screen ─────────────────────────────────────

  describe('TimeTrackingScreen', () => {
    it('renders time tracking page with clock button', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'te1', job_id: null, job_title: 'General', clock_in: '2024-01-15T08:00:00Z', clock_out: '2024-01-15T16:00:00Z', duration_minutes: 480, notes: null },
          ],
          total: 1,
        },
      })

      const { default: TimeTrackingScreen } = await import('@/screens/time-tracking/TimeTrackingScreen')
      render(<TimeTrackingScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('time-tracking-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('clock-button')).toBeInTheDocument()
      expect(screen.getByTestId('clock-card')).toBeInTheDocument()
    })
  })

  // ── 13.3 Schedule Screen ──────────────────────────────────────────

  describe('ScheduleCalendarScreen', () => {
    it('renders schedule page with calendar', async () => {
      mockGet.mockResolvedValue({
        data: { items: [], total: 0 },
      })

      const { default: ScheduleCalendarScreen } = await import('@/screens/schedule/ScheduleCalendarScreen')
      render(<ScheduleCalendarScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('schedule-page')).toBeInTheDocument()
      })
    })
  })

  // ── 13.4 POS Screen ──────────────────────────────────────────────

  describe('POSScreen', () => {
    it('renders POS page with product grid', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'prod1', name: 'Coffee', sku: null, price: 5.50, stock_level: 100, image_url: null },
            { id: 'prod2', name: 'Muffin', sku: null, price: 4.00, stock_level: 50, image_url: null },
          ],
          total: 2,
        },
      })

      const { default: POSScreen } = await import('@/screens/pos/POSScreen')
      render(<POSScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('pos-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('product-grid')).toBeInTheDocument()
      expect(screen.getByText('Coffee')).toBeInTheDocument()
      expect(screen.getByText('Muffin')).toBeInTheDocument()
    })
  })
})
