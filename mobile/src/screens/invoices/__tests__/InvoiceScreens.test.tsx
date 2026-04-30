import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ id: 'inv-1' }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  }
})

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', name: 'Test', email: 'test@test.com', role: 'owner', org_id: 'org1' },
    isAuthenticated: true,
    isLoading: false,
    isKiosk: false,
  }),
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isModuleEnabled: () => true,
    tradeFamily: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({
    branding: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    tradeFamily: null,
    tradeCategory: null,
  }),
}))

vi.mock('@/hooks/useHaptics', () => ({
  useHaptics: () => ({
    light: vi.fn().mockResolvedValue(undefined),
    medium: vi.fn().mockResolvedValue(undefined),
    heavy: vi.fn().mockResolvedValue(undefined),
    selection: vi.fn().mockResolvedValue(undefined),
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

const mockInvoices = [
  {
    id: 'inv-1',
    invoice_number: 'INV-001',
    customer_id: 'cust-1',
    customer_name: 'John Doe',
    status: 'draft' as const,
    subtotal: 100,
    tax_amount: 15,
    discount_amount: 0,
    total: 115,
    amount_paid: 0,
    amount_due: 115,
    due_date: '2025-02-15',
    created_at: '2025-01-15',
    line_items: [
      {
        id: 'li-1',
        description: 'Plumbing Service',
        quantity: 2,
        unit_price: 50,
        tax_rate: 0.15,
        amount: 100,
      },
    ],
  },
  {
    id: 'inv-2',
    invoice_number: 'INV-002',
    customer_id: 'cust-2',
    customer_name: 'Jane Smith',
    status: 'paid' as const,
    subtotal: 200,
    tax_amount: 30,
    discount_amount: 10,
    total: 220,
    amount_paid: 220,
    amount_due: 0,
    due_date: '2025-03-01',
    created_at: '2025-02-01',
    line_items: [],
  },
  {
    id: 'inv-3',
    invoice_number: 'INV-003',
    customer_id: 'cust-3',
    customer_name: 'Bob Builder',
    status: 'overdue' as const,
    subtotal: 500,
    tax_amount: 75,
    discount_amount: 0,
    total: 575,
    amount_paid: 100,
    amount_due: 475,
    due_date: '2025-01-01',
    created_at: '2024-12-01',
    line_items: [],
  },
]

function mockInvoiceListResponse(invoices = mockInvoices) {
  mockGet.mockResolvedValue({
    data: { items: invoices, total: invoices.length },
  })
}

function mockInvoiceDetailResponse(invoice = mockInvoices[0]) {
  mockGet.mockResolvedValue({ data: invoice })
}

// ---------------------------------------------------------------------------
// InvoiceListScreen Tests
// ---------------------------------------------------------------------------

describe('InvoiceListScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders invoice list with numbers, customers, and amounts', async () => {
    mockInvoiceListResponse()
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })
    expect(screen.getByText('INV-002')).toBeInTheDocument()
    expect(screen.getByText('INV-003')).toBeInTheDocument()
  })

  it('displays status badges for invoices', async () => {
    mockInvoiceListResponse()
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      // StatusBadge uses STATUS_CONFIG which renders uppercase labels
      expect(screen.getByText('DRAFT')).toBeInTheDocument()
    })
    expect(screen.getByText('PAID')).toBeInTheDocument()
    expect(screen.getByText('OVERDUE')).toBeInTheDocument()
  })

  it('displays total amounts in NZD format', async () => {
    mockInvoiceListResponse()
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('NZD115.00')).toBeInTheDocument()
    })
    expect(screen.getByText('NZD220.00')).toBeInTheDocument()
    expect(screen.getByText('NZD575.00')).toBeInTheDocument()
  })

  it('shows empty state when no invoices', async () => {
    mockGet.mockResolvedValue({ data: { items: [], total: 0 } })
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('No invoices found')).toBeInTheDocument()
    })
  })

  it('navigates to new invoice screen when FAB is tapped', async () => {
    mockInvoiceListResponse()
    const user = userEvent.setup()
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    // FAB renders as a Konsta Fab component with text "+ New Invoice"
    const fab = screen.getByTestId('konsta-fab')
    await user.click(fab)
    expect(mockNavigate).toHaveBeenCalledWith('/invoices/new')
  })

  it('renders search bar with correct placeholder', async () => {
    mockInvoiceListResponse()
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search invoices…')).toBeInTheDocument()
    })
    // Konsta Searchbar renders an input[type="text"] with the placeholder
    expect(screen.getByTestId('invoice-searchbar')).toBeInTheDocument()
  })

  it('renders Mark Sent swipe action for draft invoices', async () => {
    mockInvoiceListResponse([mockInvoices[0]]) // draft invoice only
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    // Swipe action buttons are rendered but aria-hidden until swiped;
    // verify they exist in the DOM via aria-label
    const markSentButtons = screen.getAllByLabelText('Mark Sent')
    expect(markSentButtons.length).toBeGreaterThan(0)
  })

  it('renders Payment swipe action for unpaid invoices', async () => {
    mockInvoiceListResponse([mockInvoices[0]]) // draft invoice
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    // Swipe action buttons are rendered but aria-hidden until swiped
    const paymentButtons = screen.getAllByLabelText('Payment')
    expect(paymentButtons.length).toBeGreaterThan(0)
  })

  it('does not render Payment swipe action for paid invoices', async () => {
    mockInvoiceListResponse([mockInvoices[1]]) // paid invoice only
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('INV-002')).toBeInTheDocument()
    })

    expect(screen.queryByLabelText('Payment')).not.toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Requirement 8.1 — Pull-to-refresh triggers API refetch
  // -------------------------------------------------------------------------

  it('re-fetches invoice data when refresh is triggered', async () => {
    // Start with an error state so the Retry button is visible
    mockGet.mockRejectedValue(new Error('Network error'))
    const InvoiceListScreen = (await import('../InvoiceListScreen')).default
    render(<InvoiceListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Failed to load invoices')).toBeInTheDocument()
    })

    // Now set up successful responses for the retry
    mockGet.mockClear()
    mockInvoiceListResponse()

    // Click the Retry button — this calls handleRefresh (same as PullRefresh onRefresh)
    await userEvent.click(screen.getByText('Retry'))

    // Verify the invoices endpoint was re-fetched and data is displayed
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    const invoiceCalls = mockGet.mock.calls.filter(
      (call: unknown[]) =>
        typeof call[0] === 'string' &&
        (call[0] as string).includes('/invoices'),
    )
    expect(invoiceCalls.length).toBeGreaterThan(0)
  })
})

// ---------------------------------------------------------------------------
// InvoiceDetailScreen Tests
// ---------------------------------------------------------------------------

describe('InvoiceDetailScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders invoice header with number and customer', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })
    expect(screen.getByText('John Doe')).toBeInTheDocument()
  })

  it('renders status badge', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      // StatusBadge uses STATUS_CONFIG which renders uppercase labels
      expect(screen.getByText('DRAFT')).toBeInTheDocument()
    })
  })

  it('renders line items with description, quantity, and price', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Plumbing Service')).toBeInTheDocument()
    })
    expect(screen.getByText(/2 × NZD50\.00/)).toBeInTheDocument()
  })

  it('renders totals section with subtotal, tax, and total', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Subtotal')).toBeInTheDocument()
    })
    expect(screen.getByText('GST')).toBeInTheDocument()
    // "Total" appears in both hero card and totals section
    expect(screen.getAllByText('Total').length).toBeGreaterThanOrEqual(1)
  })

  it('renders payment history with amount paid and due', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Amount Paid')).toBeInTheDocument()
    })
    expect(screen.getByText('Amount Due')).toBeInTheDocument()
  })

  it('shows Send Invoice button for draft invoices', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Send Invoice/i })).toBeInTheDocument()
    })
  })

  it('shows Record Payment button for unpaid invoices', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Record Payment/i })).toBeInTheDocument()
    })
  })

  it('shows Preview PDF button', async () => {
    mockInvoiceDetailResponse()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Preview PDF/i })).toBeInTheDocument()
    })
  })

  it('navigates to PDF screen when Preview PDF is tapped', async () => {
    mockInvoiceDetailResponse()
    const user = userEvent.setup()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Preview PDF/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Preview PDF/i }))
    expect(mockNavigate).toHaveBeenCalledWith('/invoices/inv-1/pdf')
  })

  it('shows error state when API fails', async () => {
    mockGet.mockRejectedValue(new Error('Network error'))
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Failed to load data')).toBeInTheDocument()
    })
  })

  it('shows Record Payment form when Record Payment button is clicked', async () => {
    mockInvoiceDetailResponse()
    const user = userEvent.setup()
    const InvoiceDetailScreen = (await import('../InvoiceDetailScreen')).default
    render(<InvoiceDetailScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Record Payment/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Record Payment/i }))

    await waitFor(() => {
      // Record Payment Sheet opens with a heading
      expect(screen.getByTestId('record-payment-sheet')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Exported helper unit tests
// ---------------------------------------------------------------------------

describe('sendInvoice', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls POST to send endpoint and returns true on success', async () => {
    mockPost.mockResolvedValue({ data: {} })
    const { sendInvoice } = await import('../InvoiceDetailScreen')
    const result = await sendInvoice('inv-1')
    expect(mockPost).toHaveBeenCalledWith('/api/v1/invoices/inv-1/send')
    expect(result).toBe(true)
  })

  it('returns false on failure', async () => {
    mockPost.mockRejectedValue(new Error('fail'))
    const { sendInvoice } = await import('../InvoiceDetailScreen')
    const result = await sendInvoice('inv-1')
    expect(result).toBe(false)
  })
})

describe('handleSendInvoice', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls POST to send endpoint', async () => {
    mockPost.mockResolvedValue({ data: {} })
    const { handleSendInvoice } = await import('../InvoiceListScreen')
    await handleSendInvoice('inv-1')
    expect(mockPost).toHaveBeenCalledWith('/api/v1/invoices/inv-1/send')
  })
})
