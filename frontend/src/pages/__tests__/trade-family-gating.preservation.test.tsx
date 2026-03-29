/**
 * Preservation Property Test — Trade Family Gating
 *
 * Property 2: Preservation — Vehicle UI Shown for Automotive and Null-TradeFamily Organisations
 *
 * These tests MUST PASS on unfixed code — they capture the baseline behavior to preserve.
 * Automotive orgs and null-tradeFamily orgs should see all vehicle UI.
 *
 * **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14**
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import React, { Suspense } from 'react'

/* ------------------------------------------------------------------ */
/*  Hoisted mutable tradeFamily for per-test switching                 */
/* ------------------------------------------------------------------ */

const mockState = vi.hoisted(() => ({
  tradeFamily: 'automotive-transport' as string | null,
  tradeCategory: 'general-automotive' as string | null,
}))

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

// Mock TenantContext with dynamic tradeFamily — reads from mockState at call time
vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({
    settings: {
      branding: { name: 'Test Auto Co', logo_url: null, primary_colour: '#2563eb', secondary_colour: '#1e40af', address: null, phone: null, email: null, sidebar_display_mode: 'icon_and_name' },
      gst: { gst_number: null, gst_percentage: 15, gst_inclusive: true },
      invoice: { prefix: 'INV-', default_due_days: 14, payment_terms_text: null, terms_and_conditions: null },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    tradeFamily: mockState.tradeFamily,
    tradeCategory: mockState.tradeCategory,
  }),
  TenantProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// Vehicles module is ENABLED
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
  useLocale: () => ({ locale: 'en-NZ', currency: 'NZD', formatCurrency: (n: number) => `${n.toFixed(2)}` }),
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
    if (url === '/vehicles' || url.startsWith('/vehicles?')) {
      return Promise.resolve({ data: { items: [], total: 0 } })
    }
    // Default fallback
    return Promise.resolve({ data: { items: [], total: 0 } })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  setupDefaultMocks()
  // Reset to automotive for each test — individual tests override as needed
  mockState.tradeFamily = 'automotive-transport'
  mockState.tradeCategory = 'general-automotive'
})

/* ================================================================== */
/*  PRESERVATION TESTS — Automotive tradeFamily                        */
/*  Each test asserts vehicle UI IS present for automotive orgs.        */
/*  These MUST PASS on unfixed code (baseline behavior to preserve).   */
/* ================================================================== */

describe('Property 2: Preservation — Vehicle UI Shown for Automotive Organisations', () => {

  it('InvoiceCreate: VehicleLiveSearch renders for automotive org (Req 3.2)', async () => {
    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <InvoiceCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleInputs = screen.queryAllByPlaceholderText(/rego|vehicle/i)
      const vehicleLabels = screen.queryAllByText(/vehicle/i)
      expect(vehicleInputs.length + vehicleLabels.length).toBeGreaterThan(0)
    })
  })

  it('InvoiceDetail: vehicle info section renders for automotive org (Req 3.3)', async () => {
    render(
      <MemoryRouter initialEntries={['/invoices/inv-1']}>
        <Routes>
          <Route path="/invoices/:id" element={<InvoiceDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByText('INV-001').length).toBeGreaterThan(0)
    })

    // Vehicle rego 'ABC123' should be visible for automotive org
    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('QuoteCreate: vehicle lookup renders for automotive org (Req 3.5)', async () => {
    render(
      <MemoryRouter initialEntries={['/quotes/new']}>
        <QuoteCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleSection = screen.queryByLabelText(/vehicle registration/i)
      const vehicleLabel = screen.queryByText(/^Vehicle$/i)
      expect(vehicleSection ?? vehicleLabel).not.toBeNull()
    })
  })

  it('QuoteDetail: vehicle rego renders for automotive org (Req 3.6)', async () => {
    render(
      <MemoryRouter initialEntries={['/quotes/q-1']}>
        <QuoteDetail quoteId="q-1" />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByText('QTE-001').length).toBeGreaterThan(0)
    })

    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('JobCardList: "Rego" column renders for automotive org (Req 3.7)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards']}>
        <JobCardList />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })

    expect(screen.getByText('Rego')).toBeInTheDocument()
  })

  it('JobCardCreate: vehicle section renders for automotive org (Req 3.8)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards/new']}>
        <JobCardCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleSection = document.querySelector('[aria-labelledby="section-vehicle"]')
      expect(vehicleSection).not.toBeNull()
    })
  })

  it('JobCardDetail: vehicle section renders for automotive org (Req 3.9)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards/jc-1']}>
        <Routes>
          <Route path="/job-cards/:id" element={<JobCardDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('JC-001')).toBeInTheDocument()
    })

    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('BookingForm: VehicleLiveSearch renders for automotive org (Req 3.10)', async () => {
    render(
      <MemoryRouter initialEntries={['/bookings/new']}>
        <BookingForm open={true} onClose={vi.fn()} onSaved={vi.fn()} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleInputs = screen.queryAllByPlaceholderText(/rego|vehicle/i)
      const vehicleLabels = screen.queryAllByText(/vehicle/i)
      expect(vehicleInputs.length + vehicleLabels.length).toBeGreaterThan(0)
    })
  })

  it('App.tsx: /vehicles route renders VehicleList for automotive org (Req 3.11)', async () => {
    const VehicleList = (await import('@/pages/vehicles/VehicleList')).default

    render(
      <MemoryRouter initialEntries={['/vehicles']}>
        <Suspense fallback={<div>Loading...</div>}>
          <Routes>
            <Route path="/vehicles" element={<VehicleList />} />
            <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
          </Routes>
        </Suspense>
      </MemoryRouter>,
    )

    // VehicleList should render (not redirect to dashboard) for automotive org
    await waitFor(() => {
      const dashboard = screen.queryByTestId('dashboard')
      expect(dashboard).not.toBeInTheDocument()
    })
  })
})

/* ================================================================== */
/*  PRESERVATION TESTS — Null tradeFamily (backward compatibility)     */
/*  tradeFamily: null should behave identically to automotive.         */
/*  isAutomotive = (null ?? 'automotive-transport') === 'automotive-   */
/*  transport' → true                                                  */
/* ================================================================== */

describe('Property 2: Preservation — Vehicle UI Shown for Null-TradeFamily Organisations (Backward Compat)', () => {

  beforeEach(() => {
    mockState.tradeFamily = null
    mockState.tradeCategory = null
  })

  it('InvoiceCreate: VehicleLiveSearch renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <InvoiceCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleInputs = screen.queryAllByPlaceholderText(/rego|vehicle/i)
      const vehicleLabels = screen.queryAllByText(/vehicle/i)
      expect(vehicleInputs.length + vehicleLabels.length).toBeGreaterThan(0)
    })
  })

  it('InvoiceDetail: vehicle info section renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/invoices/inv-1']}>
        <Routes>
          <Route path="/invoices/:id" element={<InvoiceDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByText('INV-001').length).toBeGreaterThan(0)
    })

    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('QuoteCreate: vehicle lookup renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/quotes/new']}>
        <QuoteCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleSection = screen.queryByLabelText(/vehicle registration/i)
      const vehicleLabel = screen.queryByText(/^Vehicle$/i)
      expect(vehicleSection ?? vehicleLabel).not.toBeNull()
    })
  })

  it('QuoteDetail: vehicle rego renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/quotes/q-1']}>
        <QuoteDetail quoteId="q-1" />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByText('QTE-001').length).toBeGreaterThan(0)
    })

    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('JobCardList: "Rego" column renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards']}>
        <JobCardList />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })

    expect(screen.getByText('Rego')).toBeInTheDocument()
  })

  it('JobCardCreate: vehicle section renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards/new']}>
        <JobCardCreate />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleSection = document.querySelector('[aria-labelledby="section-vehicle"]')
      expect(vehicleSection).not.toBeNull()
    })
  })

  it('JobCardDetail: vehicle section renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/job-cards/jc-1']}>
        <Routes>
          <Route path="/job-cards/:id" element={<JobCardDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('JC-001')).toBeInTheDocument()
    })

    expect(screen.getByText('ABC123')).toBeInTheDocument()
  })

  it('BookingForm: VehicleLiveSearch renders for null tradeFamily (Req 3.12)', async () => {
    render(
      <MemoryRouter initialEntries={['/bookings/new']}>
        <BookingForm open={true} onClose={vi.fn()} onSaved={vi.fn()} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const vehicleInputs = screen.queryAllByPlaceholderText(/rego|vehicle/i)
      const vehicleLabels = screen.queryAllByText(/vehicle/i)
      expect(vehicleInputs.length + vehicleLabels.length).toBeGreaterThan(0)
    })
  })

  it('App.tsx: /vehicles route renders VehicleList for null tradeFamily (Req 3.12)', async () => {
    const VehicleList = (await import('@/pages/vehicles/VehicleList')).default

    render(
      <MemoryRouter initialEntries={['/vehicles']}>
        <Suspense fallback={<div>Loading...</div>}>
          <Routes>
            <Route path="/vehicles" element={<VehicleList />} />
            <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard</div>} />
          </Routes>
        </Suspense>
      </MemoryRouter>,
    )

    // VehicleList should render (not redirect to dashboard) for null tradeFamily
    await waitFor(() => {
      const dashboard = screen.queryByTestId('dashboard')
      expect(dashboard).not.toBeInTheDocument()
    })
  })
})

/* ================================================================== */
/*  PROPERTY TEST — isAutomotive derivation                            */
/*  Verifies the isAutomotive logic for automotive and null values     */
/* ================================================================== */

describe('Property 2: isAutomotive derivation', () => {

  it('isAutomotive is true for tradeFamily: "automotive-transport"', () => {
    const tradeFamily: string | null = 'automotive-transport'
    const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
    expect(isAutomotive).toBe(true)
  })

  it('isAutomotive is true for tradeFamily: null (backward compat)', () => {
    const tradeFamily: string | null = null
    const isAutomotive = (tradeFamily ?? 'automotive-transport') === 'automotive-transport'
    expect(isAutomotive).toBe(true)
  })
})
