/**
 * Unit tests for Customer Profile Claims tab (Task 23 port of
 * frontend/src/pages/customers/__tests__/CustomerProfile.claims.test.tsx).
 *
 * Mocks react-router-dom, the api client, and the Tenant/Module contexts so the
 * page mounts in isolation. Verifies the Claims tab count, summary stats,
 * claims list, New Claim navigation, and the empty state — all logic preserved
 * verbatim from the original page (FR-1 / FR-2c).
 *
 * NOTE: the redesigned page (CustomerDetail.html prototype) renders the
 * customer name in BOTH the breadcrumb and the <h1> hero, so the "loaded"
 * assertion targets the heading role specifically rather than getByText.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'cust-123' }),
  useNavigate: () => mockNavigate,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({ isEnabled: (slug: string) => slug === 'vehicles' || slug === 'sms' }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'admin@test.com', name: 'Admin', role: 'org_admin', org_id: 'org-1' },
  }),
}))

import apiClient from '@/api/client'
import CustomerProfilePage from './CustomerProfile'

const mockCustomer = {
  id: 'cust-123',
  first_name: 'Jane',
  last_name: 'Smith',
  email: 'jane@example.com',
  phone: '021-555-0002',
  address: '123 Main St',
  notes: null,
  is_anonymised: false,
  enable_portal: false,
  portal_token: null,
  portal_token_expires_at: null,
  last_portal_access_at: null,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  vehicles: [],
  invoices: [],
  total_spend: '500.00',
  outstanding_balance: '0.00',
}

const mockClaimsSummary = {
  total_claims: 3,
  open_claims: 1,
  total_cost_to_business: '150.00',
  claims: [
    {
      id: 'claim-1',
      customer_id: 'cust-123',
      customer_name: 'Jane Smith',
      claim_type: 'warranty',
      status: 'open',
      description: 'Brake pad defective',
      cost_to_business: 50,
      branch_id: null,
      created_at: '2025-03-10T10:00:00Z',
    },
    {
      id: 'claim-2',
      customer_id: 'cust-123',
      customer_name: 'Jane Smith',
      claim_type: 'service_redo',
      status: 'resolved',
      description: 'Oil change redo',
      cost_to_business: 100,
      branch_id: null,
      created_at: '2025-02-15T10:00:00Z',
    },
  ],
}

const remindersResponse = {
  data: {
    service_due: { enabled: false, days_before: 30, channel: 'email' },
    wof_expiry: { enabled: false, days_before: 30, channel: 'email' },
    cof_expiry: { enabled: false, days_before: 30, channel: 'email' },
    vehicles: [],
  },
}

/** Wait until the profile has loaded (name renders in the <h1> hero). */
async function waitForLoaded() {
  await waitFor(() => {
    expect(screen.getByRole('heading', { level: 1, name: 'Jane Smith' })).toBeInTheDocument()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url === '/customers/cust-123') return { data: mockCustomer }
    if (url === '/customers/cust-123/claims') return { data: mockClaimsSummary }
    if (url === '/customers/cust-123/reminders') return remindersResponse
    return { data: {} }
  })
})

describe('CustomerProfile — Claims tab', () => {
  it('renders Claims tab with count', async () => {
    render(<CustomerProfilePage />)

    await waitForLoaded()

    expect(screen.getByRole('tab', { name: /Claims \(3\)/ })).toBeInTheDocument()
  })

  it('displays summary statistics when Claims tab is clicked', async () => {
    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitForLoaded()

    await user.click(screen.getByRole('tab', { name: /Claims/ }))

    await waitFor(() => {
      expect(screen.getByText('Total Claims')).toBeInTheDocument()
    })

    expect(screen.getByText('Open Claims')).toBeInTheDocument()
    expect(screen.getByText('Total Cost to Business')).toBeInTheDocument()
  })

  it('displays claims list in the tab', async () => {
    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitForLoaded()

    await user.click(screen.getByRole('tab', { name: /Claims/ }))

    await waitFor(() => {
      expect(screen.getByText('Brake pad defective')).toBeInTheDocument()
    })

    expect(screen.getByText('Oil change redo')).toBeInTheDocument()
  })

  it('renders New Claim button that navigates with customer_id', async () => {
    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitForLoaded()

    await user.click(screen.getByRole('tab', { name: /Claims/ }))

    await waitFor(() => {
      expect(screen.getByText('New Claim')).toBeInTheDocument()
    })

    await user.click(screen.getByText('New Claim'))
    expect(mockNavigate).toHaveBeenCalledWith('/claims/new?customer_id=cust-123')
  })

  it('shows empty state when no claims', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url === '/customers/cust-123') return { data: mockCustomer }
      if (url === '/customers/cust-123/claims') return { data: { total_claims: 0, open_claims: 0, total_cost_to_business: '0', claims: [] } }
      if (url === '/customers/cust-123/reminders') return remindersResponse
      return { data: {} }
    })

    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitForLoaded()

    await user.click(screen.getByRole('tab', { name: /Claims/ }))

    await waitFor(() => {
      expect(screen.getByText('No claims for this customer.')).toBeInTheDocument()
    })
  })
})
