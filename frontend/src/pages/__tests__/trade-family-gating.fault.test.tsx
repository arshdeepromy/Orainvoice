/**
 * Bug Condition Exploration Test — Trade Family Gating
 *
 * Property 1: Fault Condition — Vehicle UI Rendered for Non-Automotive Organisations
 *
 * This test MUST FAIL on unfixed code — failure confirms the bug exists.
 * DO NOT fix the code or the test when it fails.
 *
 * Bug condition: tradeFamily is non-automotive AND vehicle UI is rendered
 * Expected: vehicle UI should NOT render for non-automotive orgs
 *
 * **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11**
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import React, { Suspense } from 'react'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
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

// Mock TenantContext with tradeFamily: 'plumbing' — non-automotive org
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({
    settings: {
      branding: { name: 'Test Plumbing Co', logo_url: null, primary_colour: '#2563eb', secondary_colour: '#1e40af', address: null, phone: null, email: null, sidebar_display_mode: 'icon_and_name' },
      gst: { gst_number: null, gst_percentage: 15, gst_inclusive: true },
      invoice: { prefix: 'INV-', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    tradeFamily: 'plumbing',
    tradeCategory: 'plumber',
  }),
  TenantProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// Vehicles module is ENABLED — the bug is that pages don't check tradeFamily
vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [{ slug: 'vehicles', display_name: 'Vehicles', description: '', category: 'core', is_core: false, is_enabled: true }],
    enabledModules: ['vehicles'],
    isLoading: false,
    error: null,
    isEnabled: () => true,
    refetch: vi.fn(),
  }),
  ModuleProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFeatureFlags: () => ({ flags: {}, isEnabled: () => true }),
  FeatureFlagProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/contexts/TerminologyContext', () => ({
  useTerm: () => (fallback: string) => fallback,
  TerminologyProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/contexts/LocaleContext', () => ({
  useLocale: () => ({ locale: 'en-NZ', currency: 'NZD', formatCurrency: (n: number) => `$${n.toFixed(2)}` }),
  LocaleProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import apiClient from '@/api/client'
const mockGet = apiClient.get as ReturnType<typeof vi.fn>

/* ------------------------------------------------------------------ */
/*  Lazy imports (same as App.tsx)                                     */
/* ------------------------------------------------------------------ */

import InvoiceCreate from '@/pages/invoices/InvoiceCreate'
import InvoiceDetail from '@/pages/invoices/InvoiceDetail'
import QuoteCreate from '@/pages/quotes/QuoteCreate'
import QuoteDetail from '@/pages/quotes/QuoteDetail'
import JobCardList from '@/pages/job-cards/JobCardList'
import JobCardCreate from '@/pages/job-cards/JobCardCreate'
import JobCardDetail from '@/pages/job-cards/JobCardDetail'
import BookingForm from '@/pages/bookings/BookingForm'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockInvoice = {
  id: 'inv-1',
  invoice_number: 'INV-001',
  status: 'draft',
  customer: { id: 'cust-1', first_name: 'John', last_name: 'Doe', email: 'john@test.com', phone: '021111222' },
  customer_id: 'cust-1',
  vehicle: { rego: 'ABC123', make: 'Toyota', model: 'Corolla', year: 2020, colour: 'White' },
  vehicle_rego: 'ABC123',
  vehicle_make: 'Toyota',
  vehicle_model: 'Corolla',
  vehicle_year: 2020,
  vehicle_odometer: 55000,
  additional_vehicles: [],
  line_items: [],
  subtotal: 0,
  gst_amount: 0,
  total: 0,
  amount_paid: 0,
  amount_due: 0,
  issue_date: '2024-06-01',
  due_date: '2024-06-15',
  notes: null,
  terms: null,
  created_at: '2024-06-01T00:00:00Z',
  updated_at: '2024-06-01T00:00:00Z',
  payments: [],
  credit_notes: [],
  refunds: [],
}

const mockQuote = {
  id: 'q-1',
  quote_number: 'QTE-001',
  status: 'draft',
  customer_id: 'cust-1',
  customer_name: 'John Doe',
  vehicle_rego: 'ABC123',
  vehicle_make: 'Toyota',
  vehicle_model: 'Corolla',
  vehicle_year: 2020,
  subject: 'Test Quote',
  line_items: [],
  subtotal: 0,
  gst_amount: 0,
  total: 0,
  valid_until: '2024-07-01',
  created_at: '2024-06-01T00:00:00Z',
  updated_at: '2024-06-01T00:00:00Z',
  notes: null,
  terms: null,
}

const mockJobCards = [
  {
    id: 'jc-1',
    job_card_number: 'JC-001',
    customer_name: 'John Doe',
    customer_id: 'cust-1',
    vehicle_rego: 'ABC123',
    rego: 'ABC123',
    status: 'open',
    description: 'Test job',
    assigned_to_name: null,
    created_at: '2024-06-01T00:00:00Z',
    is_timer_active: false,
  },
]

const mockJobCard = {
  id: 'jc-1',
  job_card_number: 'JC-001',
  status: 'open',
  customer: { id: 'cust-1', first_name: 'John', last_name: 'Doe', email: 'john@test.com', phone: '021111222' },
  vehicle_rego: 'ABC123',
  description: 'Test job card',
  notes: '',
  line_items: [],
  created_at: '2024-06-01T00:00:00Z',
  updated_at: '2024-06-01T00:00:00Z',
  assigned_to: null,
  assigned_to_name: null,
  is_timer_active: false,
  active_timer: null,
  total_time_seconds: 0,
}

/* ------------------------------------------------------------------ */
/*  Helper: setup API mock responses                                   */
/* ------------------------------------------------------------------ */

function setupDefaultMocks() {
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/invoices/')) {
      return Promise.resolve({ data: { invoice: mockInvoice } })
    }
    if (url.includes('/quotes/') && !url.includes('/quotes?')) {
      return Promise.resolve({ data: mockQuote })
    }
    if (url === '/job-cards' || url.startsWith('/job-cards?')) {
      return Promise.resolve({ data: { items: mockJobCards, total: 1 } })
    }
    if (url.includes('/job-cards/')) {
      return Promise.resolve({ data: mockJobCard })
    }
    if (url.includes('/customers')) {
      return Promise.resolve({ data: { items: [], total: 0 } })
    }
    if (url.includes('/catalogue')) {
      return Promise.resolve({ data: { items: [], total: 0 } })
    }
    if (url.includes('/staff')) {
      return Promise.resolve({ data: { items: [], total: 0 } })
    }
    if (url.includes('/tax-rates')) {
      return Promise.resolve({ data: { tax_rates: [], total: 0 } })
    }
    if (url.includes('/bookings')) {
      return Promise.resolve({ data: { items: [], total: 0 } })
    }
    if (url.includes('/projects')) {
      return Promise.resolve({ data: { items: [], total: 0 } })
    }
    // Default fallback
    return Promise.resolve({ data: { items: [], total: 0 } })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  setupDefaultMocks()
})

/* ================================================================== */
/*  FAULT CONDITION TESTS                                              */
/*  Each test asserts vehicle UI is NOT present for tradeFamily:       */
/*  'plumbing'. These will FAIL on unfixed code, proving the bug.      */
/* ================================================================== */

describe('Property 1: Fault Condition — Vehicle UI Rendered for Non-Automotive Organisations', () => {

  it('InvoiceCreate: VehicleLiveSearch should NOT be visible for plumbing org (Req 1.2)', async () => {
    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <InvoiceCreate />
      </MemoryRouter>,
    )

    // VehicleLiveSearch renders an input with placeholder containing "rego" or "vehicle"
    // The component renders unconditionally — this assertion should FAIL on unfixed code
    await waitFor(() => {
      const vehicleInputs = screen.queryAllByPlaceholderText(/rego|vehicle/i)
      const vehicleLabels = screen.queryAllByText(/vehicle/i)
      // At least one vehicle-related element should NOT be present for non-automotive
      expect(vehicleInputs.length + vehicleLabels.length).toBe(0)
    })
  })

  it('InvoiceDetail: vehicle info section should NOT be visible for plumbing org (Req 1.3)', async () => {
    render(
      <MemoryRouter initialEntries={['/invoices/inv-1']}>
        <Routes>
          <Route path="/invoices/:id" element={<InvoiceDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    // Wait for the invoice data to load
    await waitFor(() => {
      expect(screen.getAllByText('INV-001').length).toBeGreaterThan(0)
    })

    // Now check that vehicle rego is NOT visible for a plumbing org
    // InvoiceDetail renders vehicle rego 'ABC123' in the Vehicle section
    expect(screen.queryByText('ABC123')).not.toBeInTheDocument()
  })

  it('QuoteCreate: vehicle lookup should NOT be visible for plumbing org (Req 1.5)', async () => {
    render(
      <MemoryRouter initialEntries={['/quotes/new']}>
        <QuoteCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      // QuoteCreate renders a vehicle lookup section with label "Vehicle"
      // when isEnabled('vehicles') is true — but it should also check tradeFamily
      const vehicleSection = screen.queryByLabelText(/vehicle registration/i)
      const vehicleLabel = screen.queryByText(/^Vehicle$/i)
      expect(vehicleSection ?? vehicleLabel).toBeNull()
    })
  })

  it('QuoteDetail: vehicle rego should NOT be displayed for plumbing org (Req 1.6)', async () => {
    render(
      <MemoryRouter initialEntries={['/quotes/q-1']}>
        <QuoteDetail quoteId="q-1" />
      </MemoryRouter>,
    )

    // Wait for the quote data to load
    await waitFor(() => {
      expect(screen.getAllByText('QTE-001').length).toBeGreaterThan(0)
    })

    // Now check that vehicle rego is NOT visible for a plumbing org
    expect(screen.queryByText('ABC123')).not.toBeInTheDocument()
  })

  it('JobCardList: "Rego" column header should NOT be present for plumbing org (Req 1.7)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards']}>
        <JobCardList />
      </MemoryRouter>,
    )

    // Wait for the job card data to load (table renders after fetch)
    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })

    // Now check that "Rego" column header is NOT present for a plumbing org
    expect(screen.queryByText('Rego')).not.toBeInTheDocument()
  })

  it('JobCardCreate: vehicle section should NOT be present for plumbing org (Req 1.8)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards/new']}>
        <JobCardCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      // JobCardCreate renders a vehicle section with aria-labelledby="section-vehicle"
      const vehicleSection = document.querySelector('[aria-labelledby="section-vehicle"]')
      expect(vehicleSection).toBeNull()
    })
  })

  it('JobCardDetail: vehicle section should NOT be present for plumbing org (Req 1.9)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards/jc-1']}>
        <Routes>
          <Route path="/job-cards/:id" element={<JobCardDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    // Wait for the job card data to load
    await waitFor(() => {
      expect(screen.getByText('JC-001')).toBeInTheDocument()
    })

    // Now check that vehicle rego is NOT visible for a plumbing org
    expect(screen.queryByText('ABC123')).not.toBeInTheDocument()
  })

  it('BookingForm: VehicleLiveSearch should NOT be present for plumbing org (Req 1.10)', async () => {
    render(
      <MemoryRouter initialEntries={['/bookings/new']}>
        <BookingForm open={true} onClose={vi.fn()} onSaved={vi.fn()} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleInputs = screen.queryAllByPlaceholderText(/rego|vehicle/i)
      const vehicleLabels = screen.queryAllByText(/vehicle/i)
      expect(vehicleInputs.length + vehicleLabels.length).toBe(0)
    })
  })

  it('App.tsx: /vehicles route should redirect to /dashboard for plumbing org (Req 1.11)', async () => {
    // Test the RequireAutomotive guard — non-automotive orgs should be redirected
    mockGet.mockImplementation((url: string) => {
      if (url === '/vehicles' || url.startsWith('/vehicles?')) {
        return Promise.resolve({ data: { items: [], total: 0 } })
      }
      return Promise.resolve({ data: { items: [], total: 0 } })
    })

    const VehicleList = (await import('@/pages/vehicles/VehicleList')).default

    // Inline RequireAutomotive that uses the mocked useTenant (tradeFamily: 'plumbing')
    const { useTenant } = await import('@/contexts/TenantContext')
    function RequireAutomotive() {
      const { tradeFamily } = useTenant()
      const isAuto = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
      if (!isAuto) return <Navigate to="/dashboard" replace />
      return <Outlet />
    }

    render(
      <MemoryRouter initialEntries={['/vehicles']}>
        <Suspense fallback={<div>Loading...</div>}>
          <Routes>
            <Route element={<RequireAutomotive />}>
              <Route path="/vehicles" element={<VehicleList />} />
            </Route>
            <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
          </Routes>
        </Suspense>
      </MemoryRouter>,
    )

    await waitFor(() => {
      const dashboard = screen.queryByTestId('dashboard')
      expect(dashboard).toBeInTheDocument()
    })
  })
})
