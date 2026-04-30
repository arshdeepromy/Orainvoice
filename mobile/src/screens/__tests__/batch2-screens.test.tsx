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
  return { ...actual, useNavigate: () => mockNavigate }
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

let mockEnabledModules = ['inventory', 'staff', 'projects']

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
// Tests — Phase 6: Batch 2 Screens
// ---------------------------------------------------------------------------

describe('Phase 6 — Batch 2 Screens', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEnabledModules = ['inventory', 'staff', 'projects']
  })

  // ── 11.1 Inventory Screen ──────────────────────────────────────────

  describe('InventoryListScreen', () => {
    it('renders inventory page with stock items', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 's1', name: 'Widget A', sku: 'WA-001', stock_level: 15, sell_price: 29.99, brand: 'Acme', unit_price: 29.99 },
            { id: 's2', name: 'Widget B', sku: null, stock_level: 0, sell_price: 49.99, brand: null, unit_price: 49.99 },
          ],
          total: 2,
        },
      })

      const { default: InventoryListScreen } = await import('@/screens/inventory/InventoryListScreen')
      render(<InventoryListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('inventory-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('stock-list')).toBeInTheDocument()
      expect(screen.getByText('Widget A')).toBeInTheDocument()
      expect(screen.getByText('Widget B')).toBeInTheDocument()
    })

    it('hides content when inventory module is disabled', async () => {
      mockEnabledModules = ['staff', 'projects']
      mockGet.mockResolvedValue({ data: { items: [], total: 0 } })

      const { default: InventoryListScreen } = await import('@/screens/inventory/InventoryListScreen')
      render(<InventoryListScreen />, { wrapper: Wrapper })

      expect(screen.queryByTestId('inventory-page')).not.toBeInTheDocument()
    })
  })

  // ── 11.2 Catalogue Items Screen ────────────────────────────────────

  describe('CatalogueItemsScreen', () => {
    it('renders catalogue page with items', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'c1', name: 'Brake Pad', default_price: 45.00, gst_applicable: true, category: 'Parts' },
          ],
          total: 1,
        },
      })

      const { default: CatalogueItemsScreen } = await import('@/screens/inventory/CatalogueItemsScreen')
      render(<CatalogueItemsScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('catalogue-page')).toBeInTheDocument()
      })
    })
  })

  // ── 11.3 Staff Screen ─────────────────────────────────────────────

  describe('StaffListScreen', () => {
    it('renders staff page with role badges', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'st1', first_name: 'John', last_name: 'Doe', email: 'john@test.com', phone: null, role: 'owner', branch_name: 'Main', is_active: true },
            { id: 'st2', first_name: 'Jane', last_name: 'Smith', email: null, phone: '021123456', role: 'salesperson', branch_name: null, is_active: false },
          ],
          total: 2,
        },
      })

      const { default: StaffListScreen } = await import('@/screens/staff/StaffListScreen')
      render(<StaffListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('staff-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('staff-list')).toBeInTheDocument()
      expect(screen.getByText('John Doe')).toBeInTheDocument()
      expect(screen.getByText('Jane Smith')).toBeInTheDocument()
    })

    it('hides content when staff module is disabled', async () => {
      mockEnabledModules = ['inventory', 'projects']
      mockGet.mockResolvedValue({ data: { items: [], total: 0 } })

      const { default: StaffListScreen } = await import('@/screens/staff/StaffListScreen')
      render(<StaffListScreen />, { wrapper: Wrapper })

      expect(screen.queryByTestId('staff-page')).not.toBeInTheDocument()
    })
  })

  // ── 11.4 Projects Screen ──────────────────────────────────────────

  describe('ProjectListScreen', () => {
    it('renders projects page with progress bars', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'p1', name: 'Office Reno', status: 'active', budget: 50000, spent: 25000, budget_utilisation: 50 },
          ],
          total: 1,
        },
      })

      const { default: ProjectListScreen } = await import('@/screens/projects/ProjectListScreen')
      render(<ProjectListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('projects-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('projects-list')).toBeInTheDocument()
      expect(screen.getByText('Office Reno')).toBeInTheDocument()
    })
  })
})
