import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 11.1-11.6, 12.1-12.4, 66.1-66.3, 67.1-67.3
 */

/* Mock react-router-dom */
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'cust-1' }),
  useNavigate: () => vi.fn(),
}))

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import CustomerList from '../pages/customers/CustomerList'
import CustomerProfile from '../pages/customers/CustomerProfile'
import FleetAccounts from '../pages/customers/FleetAccounts'
import DiscountRules from '../pages/customers/DiscountRules'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockCustomers = [
  { id: 'cust-1', first_name: 'John', last_name: 'Smith', email: 'john@example.com', phone: '021 123 4567' },
  { id: 'cust-2', first_name: 'Jane', last_name: 'Doe', email: 'jane@example.com', phone: '022 987 6543' },
]

const mockProfile = {
  id: 'cust-1',
  first_name: 'John',
  last_name: 'Smith',
  email: 'john@example.com',
  phone: '021 123 4567',
  address: '123 Main St, Auckland',
  notes: 'Regular customer',
  is_anonymised: false,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const mockProfileFull = {
  ...mockProfile,
  vehicles: [
    { id: 'vl-1', rego: 'ABC123', make: 'Toyota', model: 'Corolla', year: 2020, colour: 'White', source: 'global', linked_at: '2024-06-01T00:00:00Z' },
  ],
  invoices: [
    { id: 'inv-1', invoice_number: 'INV-001', vehicle_rego: 'ABC123', status: 'paid', issue_date: '2024-12-01', total: '230.00', balance_due: '0.00' },
    { id: 'inv-2', invoice_number: 'INV-002', vehicle_rego: 'ABC123', status: 'overdue', issue_date: '2025-01-01', total: '150.00', balance_due: '150.00' },
  ],
  total_spend: '230.00',
  outstanding_balance: '150.00',
}

const mockFleetAccounts = [
  {
    id: 'fleet-1', name: 'ABC Transport', primary_contact_name: 'Bob Jones',
    primary_contact_email: 'bob@abc.co.nz', primary_contact_phone: '09 555 1234',
    billing_address: '456 Fleet St', notes: null, pricing_overrides: {},
    customer_count: 5, created_at: '2024-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z',
  },
]

const mockDiscountRules = [
  { id: 'dr-1', name: '10% Loyalty', rule_type: 'visit_count' as const, threshold_value: '5', discount_type: 'percentage' as const, discount_value: '10', is_active: true, created_at: '2024-01-01T00:00:00Z' },
  { id: 'dr-2', name: '$20 off big spenders', rule_type: 'spend_threshold' as const, threshold_value: '1000', discount_type: 'fixed' as const, discount_value: '20', is_active: false, created_at: '2024-06-01T00:00:00Z' },
]

/* ------------------------------------------------------------------ */
/*  CustomerList tests                                                 */
/* ------------------------------------------------------------------ */

describe('CustomerList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<CustomerList />)
    expect(screen.getByRole('status', { name: 'Loading customers' })).toBeInTheDocument()
  })

  it('renders heading and new customer button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { customers: mockCustomers, total: 2, has_exact_match: false },
    })
    render(<CustomerList />)
    expect(screen.getByRole('heading', { name: 'Customers' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ New Customer' })).toBeInTheDocument()
  })

  it('displays customer list with name, email, phone (Req 11.1, 11.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { customers: mockCustomers, total: 2, has_exact_match: false },
    })
    render(<CustomerList />)
    const table = await screen.findByRole('grid')
    const rows = within(table).getAllByRole('row')
    // header + 2 data rows
    expect(rows).toHaveLength(3)
    expect(screen.getByText('John Smith')).toBeInTheDocument()
    expect(screen.getByText('john@example.com')).toBeInTheDocument()
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
  })

  it('shows empty state when no customers', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { customers: [], total: 0, has_exact_match: false },
    })
    render(<CustomerList />)
    expect(await screen.findByText('No customers yet. Create your first customer to get started.')).toBeInTheDocument()
  })

  it('opens create customer modal (Req 11.3, 11.4)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { customers: [], total: 0, has_exact_match: false },
    })
    render(<CustomerList />)
    await screen.findByRole('grid')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '+ New Customer' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('New Customer')).toBeInTheDocument()
  })

  it('has search input for live search (Req 11.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { customers: mockCustomers, total: 2, has_exact_match: false },
    })
    render(<CustomerList />)
    expect(screen.getByLabelText('Search customers')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  CustomerProfile tests                                              */
/* ------------------------------------------------------------------ */

describe('CustomerProfile', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<CustomerProfile />)
    expect(screen.getByRole('status', { name: 'Loading customer' })).toBeInTheDocument()
  })

  it('displays customer name and summary cards (Req 12.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    expect(await screen.findByText('John Smith')).toBeInTheDocument()
    expect(screen.getByText('Total Spend')).toBeInTheDocument()
    expect(screen.getByText('Outstanding')).toBeInTheDocument()
  })

  it('shows linked vehicles in vehicles tab (Req 12.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    expect(await screen.findByText('ABC123')).toBeInTheDocument()
    expect(screen.getByText('2020 Toyota Corolla')).toBeInTheDocument()
  })

  it('shows invoice history in invoices tab (Req 12.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: /Invoices/ }))
    expect(screen.getByText('INV-001')).toBeInTheDocument()
    expect(screen.getByText('INV-002')).toBeInTheDocument()
  })

  it('has send email/SMS button (Req 12.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    expect(screen.getByRole('button', { name: 'Send Email / SMS' })).toBeInTheDocument()
  })

  it('has merge customer button (Req 12.4)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    expect(screen.getByRole('button', { name: 'Merge Customer' })).toBeInTheDocument()
  })

  it('displays contact details section', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    expect(screen.getByText('john@example.com')).toBeInTheDocument()
    expect(screen.getByText('021 123 4567')).toBeInTheDocument()
    expect(screen.getByText('123 Main St, Auckland')).toBeInTheDocument()
  })

  it('shows Process Deletion Request button for non-anonymised customer (Req 13.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    expect(screen.getByRole('button', { name: 'Process Deletion Request' })).toBeInTheDocument()
  })

  it('shows Export Customer Data button for non-anonymised customer (Req 13.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    expect(screen.getByRole('button', { name: 'Export Customer Data' })).toBeInTheDocument()
  })

  it('hides privacy buttons for anonymised customer', async () => {
    const anonymised = { ...mockProfileFull, is_anonymised: true, first_name: 'Anonymised', last_name: 'Customer' }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: anonymised })
    render(<CustomerProfile />)
    await screen.findByText('Anonymised Customer')
    expect(screen.queryByRole('button', { name: 'Process Deletion Request' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Export Customer Data' })).not.toBeInTheDocument()
  })

  it('opens deletion confirmation dialog explaining anonymisation (Req 13.1, 13.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Process Deletion Request' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/Replace the customer name with "Anonymised Customer"/)).toBeInTheDocument()
    expect(screen.getByText(/Clear all contact details/)).toBeInTheDocument()
    expect(screen.getByText(/financial records remain intact/)).toBeInTheDocument()
    expect(screen.getByText(/This action cannot be undone/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm Anonymisation' })).toBeInTheDocument()
  })

  it('opens export confirmation dialog explaining what is included (Req 13.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Export Customer Data' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/Customer profile/)).toBeInTheDocument()
    expect(screen.getByText(/Complete invoice history/)).toBeInTheDocument()
    expect(screen.getByText(/Payment records/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download Export' })).toBeInTheDocument()
  })

  it('calls DELETE endpoint when deletion is confirmed (Req 13.1, 13.2)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockProfileFull })
    ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({})
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Process Deletion Request' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Anonymisation' }))
    expect(apiClient.delete).toHaveBeenCalledWith('/customers/cust-1')
  })

  it('calls GET export endpoint when export is confirmed (Req 13.3)', async () => {
    const mockBlob = new Blob(['{}'], { type: 'application/json' })
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((_url: string, config?: Record<string, unknown>) => {
      if (config?.responseType === 'blob') return Promise.resolve({ data: mockBlob })
      return Promise.resolve({ data: mockProfileFull })
    })
    // Mock URL.createObjectURL and revokeObjectURL
    const createObjectURL = vi.fn(() => 'blob:test')
    const revokeObjectURL = vi.fn()
    globalThis.URL.createObjectURL = createObjectURL
    globalThis.URL.revokeObjectURL = revokeObjectURL
    render(<CustomerProfile />)
    await screen.findByText('John Smith')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Export Customer Data' }))
    await user.click(screen.getByRole('button', { name: 'Download Export' }))
    expect(apiClient.get).toHaveBeenCalledWith('/customers/cust-1/export', { responseType: 'blob' })
  })
})

/* ------------------------------------------------------------------ */
/*  FleetAccounts tests                                                */
/* ------------------------------------------------------------------ */

describe('FleetAccounts', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<FleetAccounts />)
    expect(screen.getByRole('status', { name: 'Loading fleet accounts' })).toBeInTheDocument()
  })

  it('renders heading and new fleet account button (Req 66.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { fleet_accounts: mockFleetAccounts, total: 1 },
    })
    render(<FleetAccounts />)
    expect(screen.getByRole('heading', { name: 'Fleet Accounts' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ New Fleet Account' })).toBeInTheDocument()
  })

  it('displays fleet account list (Req 66.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { fleet_accounts: mockFleetAccounts, total: 1 },
    })
    render(<FleetAccounts />)
    const table = await screen.findByRole('grid')
    expect(within(table).getByText('ABC Transport')).toBeInTheDocument()
    expect(within(table).getByText('Bob Jones')).toBeInTheDocument()
    expect(within(table).getByText('5')).toBeInTheDocument()
  })

  it('shows empty state when no fleet accounts', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { fleet_accounts: [], total: 0 },
    })
    render(<FleetAccounts />)
    expect(await screen.findByText('No fleet accounts yet. Create one to manage commercial customers.')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  DiscountRules tests                                                */
/* ------------------------------------------------------------------ */

describe('DiscountRules', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<DiscountRules />)
    expect(screen.getByRole('status', { name: 'Loading discount rules' })).toBeInTheDocument()
  })

  it('renders heading and new rule button (Req 67.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { discount_rules: mockDiscountRules, total: 2 },
    })
    render(<DiscountRules />)
    expect(screen.getByRole('heading', { name: 'Discount Rules' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ New Rule' })).toBeInTheDocument()
  })

  it('displays discount rules with type badges and values (Req 67.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { discount_rules: mockDiscountRules, total: 2 },
    })
    render(<DiscountRules />)
    const table = await screen.findByRole('grid')
    expect(within(table).getByText('10% Loyalty')).toBeInTheDocument()
    expect(within(table).getByText('Visit Count')).toBeInTheDocument()
    expect(within(table).getByText('10%')).toBeInTheDocument()
    expect(within(table).getByText('$20 off big spenders')).toBeInTheDocument()
    expect(within(table).getByText('Spend Threshold')).toBeInTheDocument()
    expect(within(table).getByText('$20')).toBeInTheDocument()
  })

  it('shows active/inactive status badges (Req 67.3)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { discount_rules: mockDiscountRules, total: 2 },
    })
    render(<DiscountRules />)
    await screen.findByRole('grid')
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('shows empty state when no rules', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { discount_rules: [], total: 0 },
    })
    render(<DiscountRules />)
    expect(await screen.findByText('No discount rules yet. Create one to offer loyalty discounts.')).toBeInTheDocument()
  })
})
