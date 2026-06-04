/**
 * Unit tests for QR Payment button visibility on InvoiceCreate.
 *
 * Task 20 port of frontend/src/pages/invoices/InvoiceCreate.qr.test.tsx — verbatim
 * (the original already uses `@/` imports + context mocks that match v2).
 *
 * **Validates: Requirements 1.1, 1.2**
 *
 * Property 1: QR Payment Button Visibility
 * For any organisation, the "QR Payment" button SHALL be visible on InvoiceCreate
 * if and only if the organisation has a non-empty stripe_connect_account_id
 * (determined by the online-payments/status endpoint returning { is_connected: true }).
 */

import { render, screen, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

/* ------------------------------------------------------------------ */
/*  Mocks — must be declared before imports that use them              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
  },
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({
    settings: {
      branding: { name: 'Test Org', logo_url: null, primary_colour: '#2563eb', secondary_colour: '#1e40af', address: null, phone: null, email: null, sidebar_display_mode: 'icon_and_name' },
      gst: { gst_number: '123-456-789', gst_percentage: 15, gst_inclusive: false },
      invoice: { prefix: 'INV', default_due_days: 0, payment_terms_text: null, terms_and_conditions: null, default_notes: null, default_notes_enabled: false, payment_terms_enabled: true, terms_and_conditions_enabled: true },
      addressCountry: 'NZ',
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    tradeFamily: 'automotive-transport',
    tradeCategory: 'general-automotive',
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

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', email: 'test@example.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
    isLoading: false,
    isGlobalAdmin: false,
    isOrgAdmin: true,
    isBranchAdmin: false,
    isSalesperson: false,
    isKiosk: false,
  }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: ['vehicles'],
    isLoading: false,
    error: null,
    isEnabled: (slug: string) => slug === 'vehicles',
    refetch: vi.fn(),
  }),
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/utils/navigationGuard', () => ({
  setNavigationGuard: vi.fn(),
  clearNavigationGuard: vi.fn(),
}))

vi.mock('@/utils/vehicleHelpers', () => ({
  getInspectionLabel: () => 'WOF',
}))

// Mock the QrPaymentWaitingPopup to avoid its internal complexity
vi.mock('./QrPaymentWaitingPopup', () => ({
  QrPaymentWaitingPopup: () => <div data-testid="qr-payment-waiting-popup" />,
}))

// Mock the components used inside InvoiceCreate to reduce complexity
vi.mock('@/components/customers/CustomerCreateModal', () => ({
  CustomerCreateModal: () => null,
}))

vi.mock('@/components/vehicles/VehicleLiveSearch', () => ({
  VehicleLiveSearch: () => null,
}))

vi.mock('@/components/inventory/AddToStockModal', () => ({
  AddToStockModal: () => null,
}))

vi.mock('@/components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderInvoiceCreate() {
  return render(
    <MemoryRouter initialEntries={['/invoices/new']}>
      <Routes>
        <Route path="/invoices/new" element={<InvoiceCreateLazy />} />
      </Routes>
    </MemoryRouter>,
  )
}

// Lazy import after mocks are set up
let InvoiceCreateLazy: React.ComponentType

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('InvoiceCreate — QR Payment Button Visibility (Property 1)', () => {
  beforeEach(async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.clearAllMocks()

    // Default mock responses for all the API calls InvoiceCreate makes on mount
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/payments/online-payments/status') {
        // Default: connected
        return Promise.resolve({ data: { is_connected: true } })
      }
      if (url === '/invoices/next-number') {
        return Promise.resolve({ data: { next_number: 'INV-2026-001' } })
      }
      if (url === '/catalogue/items') {
        return Promise.resolve({ data: { items: [], total: 0 } })
      }
      if (url === '/org/salespeople' || url.includes('salespeople')) {
        return Promise.resolve({ data: { salespeople: [] } })
      }
      if (url === '/customers') {
        return Promise.resolve({ data: { customers: [], total: 0 } })
      }
      return Promise.resolve({ data: {} })
    })

    // Dynamically import the component after mocks are set up
    const mod = await import('./InvoiceCreate')
    InvoiceCreateLazy = mod.default
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows "QR Payment" button when online-payments/status returns connected: true', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/payments/online-payments/status') {
        return Promise.resolve({ data: { is_connected: true } })
      }
      if (url === '/invoices/next-number') {
        return Promise.resolve({ data: { next_number: 'INV-2026-001' } })
      }
      if (url === '/catalogue/items') {
        return Promise.resolve({ data: { items: [], total: 0 } })
      }
      if (url === '/org/salespeople' || url.includes('salespeople')) {
        return Promise.resolve({ data: { salespeople: [] } })
      }
      return Promise.resolve({ data: {} })
    })

    await act(async () => {
      renderInvoiceCreate()
    })

    // Wait for the component to process the API response and re-render
    // The component renders the QR Payment button in both mobile and desktop action bars
    await waitFor(() => {
      const buttons = screen.queryAllByText('QR Payment')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  it('hides "QR Payment" button when online-payments/status returns connected: false', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === '/payments/online-payments/status') {
        return Promise.resolve({ data: { is_connected: false } })
      }
      if (url === '/invoices/next-number') {
        return Promise.resolve({ data: { next_number: 'INV-2026-001' } })
      }
      if (url === '/catalogue/items') {
        return Promise.resolve({ data: { items: [], total: 0 } })
      }
      if (url === '/org/salespeople' || url.includes('salespeople')) {
        return Promise.resolve({ data: { salespeople: [] } })
      }
      return Promise.resolve({ data: {} })
    })

    await act(async () => {
      renderInvoiceCreate()
    })

    // Wait for the component to settle after API calls
    await act(async () => {
      vi.advanceTimersByTime(100)
    })

    // QR Payment button should NOT be present in either mobile or desktop action bars
    expect(screen.queryAllByText('QR Payment')).toHaveLength(0)
  })
})
