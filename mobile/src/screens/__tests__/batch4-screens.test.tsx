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
  return { ...actual, useNavigate: () => mockNavigate, useParams: () => ({ id: 'test-id' }) }
})

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
  },
}))

let mockEnabledModules = ['recurring_invoices', 'purchase_orders', 'progress_claims', 'variations', 'retentions', 'tables', 'kitchen_display']
let mockTradeFamily: string | null = 'building-construction'

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: mockEnabledModules,
    isLoading: false,
    error: null,
    isModuleEnabled: (slug: string) => mockEnabledModules.includes(slug),
    tradeFamily: mockTradeFamily,
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
// Tests — Phase 8: Batch 4 Screens
// ---------------------------------------------------------------------------

describe('Phase 8 — Batch 4 Screens', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEnabledModules = ['recurring_invoices', 'purchase_orders', 'progress_claims', 'variations', 'retentions', 'tables', 'kitchen_display']
    mockTradeFamily = 'building-construction'
  })

  // ── 15.1 Recurring Invoices Screen ────────────────────────────────

  describe('RecurringListScreen', () => {
    it('renders recurring invoices with frequency badge', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'r1', customer_name: 'Acme Corp', amount: 500, frequency: 'monthly', next_run_date: '2024-02-01', status: 'active' },
          ],
          total: 1,
        },
      })

      const { default: RecurringListScreen } = await import('@/screens/recurring/RecurringListScreen')
      render(<RecurringListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('recurring-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('recurring-list')).toBeInTheDocument()
      expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    })
  })

  // ── 15.2 Purchase Orders Screen ───────────────────────────────────

  describe('POListScreen', () => {
    it('renders purchase orders list', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'po1', po_number: 'PO-001', supplier_name: 'Parts Co', amount: 1200, status: 'sent', created_at: '2024-01-10' },
          ],
          total: 1,
        },
      })

      const { default: POListScreen } = await import('@/screens/purchase-orders/POListScreen')
      render(<POListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('po-list-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('po-list')).toBeInTheDocument()
      expect(screen.getByText('PO-001')).toBeInTheDocument()
    })
  })

  // ── 15.3 Construction Screens ─────────────────────────────────────

  describe('ProgressClaimListScreen', () => {
    it('renders progress claims with building-construction trade', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'cl1', claim_number: 'CL-001', project_name: 'Tower Build', amount: 50000, status: 'submitted', created_at: '2024-01-05' },
          ],
          total: 1,
        },
      })

      const { default: ProgressClaimListScreen } = await import('@/screens/construction/ProgressClaimListScreen')
      render(<ProgressClaimListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('progress-claims-page')).toBeInTheDocument()
      })
      expect(screen.getByText('CL-001')).toBeInTheDocument()
    })

    it('hides content when trade family does not match', async () => {
      mockTradeFamily = 'automotive-transport'
      mockGet.mockResolvedValue({ data: { items: [], total: 0 } })

      const { default: ProgressClaimListScreen } = await import('@/screens/construction/ProgressClaimListScreen')
      render(<ProgressClaimListScreen />, { wrapper: Wrapper })

      expect(screen.queryByTestId('progress-claims-page')).not.toBeInTheDocument()
    })
  })

  describe('RetentionSummaryScreen', () => {
    it('renders retention summary cards', async () => {
      mockGet.mockResolvedValue({
        data: {
          total_retained: 10000,
          total_released: 5000,
          total_pending: 5000,
          release_schedules: [],
        },
      })

      const { default: RetentionSummaryScreen } = await import('@/screens/construction/RetentionSummaryScreen')
      render(<RetentionSummaryScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('retentions-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('retained-card')).toBeInTheDocument()
    })
  })

  // ── 15.4 Hospitality Screens ──────────────────────────────────────

  describe('FloorPlanScreen', () => {
    it('renders floor plan when food-hospitality trade', async () => {
      mockTradeFamily = 'food-hospitality'
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 't1', number: 1, seats: 4, status: 'available', customer_name: null, x: 10, y: 10 },
          ],
          total: 1,
        },
      })

      const { default: FloorPlanScreen } = await import('@/screens/hospitality/FloorPlanScreen')
      render(<FloorPlanScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('floor-plan-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('floor-layout')).toBeInTheDocument()
    })
  })

  describe('KitchenDisplayScreen', () => {
    it('renders kitchen display with order cards', async () => {
      mockTradeFamily = 'food-hospitality'
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'ko1', order_number: '42', table_number: 3, items: [{ id: 'ki1', name: 'Burger', quantity: 2, modifications: null }], status: 'pending', created_at: '2024-01-15T12:00:00Z', notes: null },
          ],
          total: 1,
        },
      })

      const { default: KitchenDisplayScreen } = await import('@/screens/hospitality/KitchenDisplayScreen')
      render(<KitchenDisplayScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('kitchen-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('kitchen-order-ko1')).toBeInTheDocument()
      expect(screen.getByText('2× Burger')).toBeInTheDocument()
    })
  })
})
