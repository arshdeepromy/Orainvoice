/**
 * Unit tests for Customer Profile Claims tab.
 *
 * Requirements: 9.1, 9.2, 9.3
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

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))

import apiClient from '../../../api/client'
import CustomerProfilePage from '../CustomerProfile'

const mockCustomer = {
  id: 'cust-123',
  first_name: 'Jane',
  last_name: 'Smith',
  email: 'jane@example.com',
  phone: '021-555-0002',
  address: '123 Main St',
  notes: null,
  is_anonymised: false,
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

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url === '/customers/cust-123') return { data: mockCustomer }
    if (url === '/customers/cust-123/claims') return { data: mockClaimsSummary }
    if (url === '/customers/cust-123/reminders') return { data: { service_due: { enabled: false, days_before: 30, channel: 'email' }, wof_expiry: { enabled: false, days_before: 30, channel: 'email' }, vehicles: [] } }
    return { data: {} }
  })
})

describe('CustomerProfile — Claims tab', () => {
  it('renders Claims tab with count', async () => {
    render(<CustomerProfilePage />)

    await waitFor(() => {
      expect(screen.getByText('Jane Smith')).toBeInTheDocument()
    })

    expect(screen.getByRole('tab', { name: /Claims \(3\)/ })).toBeInTheDocument()
  })

  it('displays summary statistics when Claims tab is clicked', async () => {
    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitFor(() => {
      expect(screen.getByText('Jane Smith')).toBeInTheDocument()
    })

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

    await waitFor(() => {
      expect(screen.getByText('Jane Smith')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('tab', { name: /Claims/ }))

    await waitFor(() => {
      expect(screen.getByText('Brake pad defective')).toBeInTheDocument()
    })

    expect(screen.getByText('Oil change redo')).toBeInTheDocument()
  })

  it('renders New Claim button that navigates with customer_id', async () => {
    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitFor(() => {
      expect(screen.getByText('Jane Smith')).toBeInTheDocument()
    })

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
      if (url === '/customers/cust-123/reminders') return { data: { service_due: { enabled: false, days_before: 30, channel: 'email' }, wof_expiry: { enabled: false, days_before: 30, channel: 'email' }, vehicles: [] } }
      return { data: {} }
    })

    const user = userEvent.setup()
    render(<CustomerProfilePage />)

    await waitFor(() => {
      expect(screen.getByText('Jane Smith')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('tab', { name: /Claims/ }))

    await waitFor(() => {
      expect(screen.getByText('No claims for this customer.')).toBeInTheDocument()
    })
  })
})
