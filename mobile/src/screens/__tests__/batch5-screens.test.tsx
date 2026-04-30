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
  return { ...actual, useNavigate: () => mockNavigate, useSearchParams: () => [new URLSearchParams(), vi.fn()], useParams: () => ({ id: 'test-id', type: 'revenue' }) }
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

let mockEnabledModules = ['assets', 'compliance_docs', 'sms']

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
// Tests — Phase 9: Batch 5 Screens
// ---------------------------------------------------------------------------

describe('Phase 9 — Batch 5 Screens', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEnabledModules = ['assets', 'compliance_docs', 'sms']
  })

  // ── 17.1 Assets Screen ────────────────────────────────────────────

  describe('AssetListScreen', () => {
    it('renders assets page with items', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'a1', name: 'Laptop', category: 'IT', value: 2000, current_value: 1500, depreciation_rate: 25, status: 'active' },
          ],
          total: 1,
        },
      })

      const { default: AssetListScreen } = await import('@/screens/assets/AssetListScreen')
      render(<AssetListScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('assets-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('assets-list')).toBeInTheDocument()
      expect(screen.getByText('Laptop')).toBeInTheDocument()
    })

    it('hides content when assets module is disabled', async () => {
      mockEnabledModules = ['compliance_docs', 'sms']
      mockGet.mockResolvedValue({ data: { items: [], total: 0 } })

      const { default: AssetListScreen } = await import('@/screens/assets/AssetListScreen')
      render(<AssetListScreen />, { wrapper: Wrapper })

      expect(screen.queryByTestId('assets-page')).not.toBeInTheDocument()
    })
  })

  // ── 17.2 Compliance Documents Screen ──────────────────────────────

  describe('ComplianceDashboardScreen', () => {
    it('renders compliance page with expiry pills', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'd1', name: 'Electrical License', document_type: 'license', expiry_date: '2025-06-01', status: 'valid', file_url: null },
            { id: 'd2', name: 'Insurance', document_type: 'insurance', expiry_date: '2024-02-01', status: 'expired', file_url: null },
          ],
          total: 2,
        },
      })

      const { default: ComplianceDashboardScreen } = await import('@/screens/compliance/ComplianceDashboardScreen')
      render(<ComplianceDashboardScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('compliance-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('valid-count')).toBeInTheDocument()
      expect(screen.getByTestId('expired-count')).toBeInTheDocument()
      expect(screen.getByTestId('compliance-list')).toBeInTheDocument()
      expect(screen.getByText('Electrical License')).toBeInTheDocument()
    })
  })

  // ── 17.3 SMS Chat Screen ──────────────────────────────────────────

  describe('SMSComposeScreen', () => {
    it('renders SMS conversation list', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { id: 'c1', phone: '+6421123456', contact_name: 'John Doe', last_message: 'Hi there', last_message_at: '2024-01-15T10:00:00Z', unread_count: 2 },
          ],
          total: 1,
        },
      })

      const { default: SMSComposeScreen } = await import('@/screens/sms/SMSComposeScreen')
      render(<SMSComposeScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('sms-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('sms-conversations-list')).toBeInTheDocument()
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })
  })

  // ── 17.4 Reports Screen ──────────────────────────────────────────

  describe('ReportsMenuScreen', () => {
    it('renders reports page with category cards', async () => {
      const { default: ReportsMenuScreen } = await import('@/screens/reports/ReportsMenuScreen')
      render(<ReportsMenuScreen />, { wrapper: Wrapper })

      expect(screen.getByTestId('reports-page')).toBeInTheDocument()
      expect(screen.getByTestId('report-card-revenue')).toBeInTheDocument()
      expect(screen.getByTestId('report-card-outstanding_invoices')).toBeInTheDocument()
      expect(screen.getByText('Revenue Report')).toBeInTheDocument()
    })
  })

  // ── 17.5 Notifications Screen ────────────────────────────────────

  describe('NotificationPreferencesScreen', () => {
    it('renders notification preferences with toggles', async () => {
      mockGet.mockResolvedValue({
        data: {
          items: [
            { category: 'invoice_paid', label: 'Invoice Paid', enabled: true, description: 'When an invoice is paid' },
            { category: 'invoice_overdue', label: 'Invoice Overdue', enabled: false, description: 'When an invoice becomes overdue' },
          ],
          total: 2,
        },
      })

      const { default: NotificationPreferencesScreen } = await import('@/screens/notifications/NotificationPreferencesScreen')
      render(<NotificationPreferencesScreen />, { wrapper: Wrapper })

      await waitFor(() => {
        expect(screen.getByTestId('notifications-page')).toBeInTheDocument()
      })
      expect(screen.getByTestId('notification-prefs-list')).toBeInTheDocument()
      expect(screen.getByText('Invoice Paid')).toBeInTheDocument()
      expect(screen.getByText('Invoice Overdue')).toBeInTheDocument()
    })
  })
})
