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
    useParams: () => ({ id: 'cust-1' }),
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

const mockCustomers = [
  {
    id: 'cust-1',
    first_name: 'John',
    last_name: 'Doe',
    email: 'john@example.com',
    phone: '021-555-1234',
    company: 'Doe Plumbing',
    address: '123 Main St',
  },
  {
    id: 'cust-2',
    first_name: 'Jane',
    last_name: null,
    email: null,
    phone: '021-555-5678',
    company: null,
    address: null,
  },
  {
    id: 'cust-3',
    first_name: 'Bob',
    last_name: 'Smith',
    email: 'bob@example.com',
    phone: null,
    company: null,
    address: null,
  },
]

function mockCustomerListResponse(customers = mockCustomers) {
  mockGet.mockResolvedValue({
    data: { customers, total: customers.length },
  })
}

// ---------------------------------------------------------------------------
// CustomerListScreen Tests
// ---------------------------------------------------------------------------

describe('CustomerListScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders customer list with names and contact info', async () => {
    mockCustomerListResponse()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })
    expect(screen.getByText('Jane')).toBeInTheDocument()
    expect(screen.getByText('Bob Smith')).toBeInTheDocument()
  })

  it('displays phone and email in subtitle', async () => {
    mockCustomerListResponse()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('021-555-1234 · john@example.com')).toBeInTheDocument()
    })
  })

  it('displays company name as trailing content', async () => {
    mockCustomerListResponse()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('Doe Plumbing')).toBeInTheDocument()
    })
  })

  it('shows empty state when no customers', async () => {
    mockGet.mockResolvedValue({ data: { customers: [], total: 0 } })
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('No customers found')).toBeInTheDocument()
    })
  })

  it('navigates to new customer screen when New button is tapped', async () => {
    mockCustomerListResponse()
    const user = userEvent.setup()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /New/i }))
    expect(mockNavigate).toHaveBeenCalledWith('/customers/new')
  })

  it('renders search bar with correct placeholder', async () => {
    mockCustomerListResponse()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByRole('searchbox')).toBeInTheDocument()
    })
    expect(screen.getByPlaceholderText('Search customers…')).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Requirement 7.6 — Swipe action buttons
  // -------------------------------------------------------------------------

  it('renders Call swipe action button for customers with phone', async () => {
    mockCustomerListResponse()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })

    // SwipeAction renders action buttons in the DOM (hidden behind the swipe)
    const callButtons = screen.getAllByRole('button', { name: 'Call' })
    expect(callButtons.length).toBeGreaterThan(0)
  })

  it('renders Email swipe action button for customers with email', async () => {
    mockCustomerListResponse()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })

    const emailButtons = screen.getAllByRole('button', { name: 'Email' })
    expect(emailButtons.length).toBeGreaterThan(0)
  })

  it('renders SMS swipe action button for customers with phone', async () => {
    mockCustomerListResponse()
    const CustomerListScreen = (await import('../CustomerListScreen')).default
    render(<CustomerListScreen />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument()
    })

    const smsButtons = screen.getAllByRole('button', { name: 'SMS' })
    expect(smsButtons.length).toBeGreaterThan(0)
  })
})

// ---------------------------------------------------------------------------
// Swipe action handler unit tests
// ---------------------------------------------------------------------------

describe('CustomerListScreen swipe action handlers', () => {
  let windowOpenSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    windowOpenSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  it('handleCall opens tel: link with customer phone', async () => {
    const { handleCall } = await import('../CustomerListScreen')
    handleCall('021-555-1234')
    expect(windowOpenSpy).toHaveBeenCalledWith('tel:021-555-1234', '_system')
  })

  it('handleCall does nothing when phone is null', async () => {
    const { handleCall } = await import('../CustomerListScreen')
    handleCall(null)
    expect(windowOpenSpy).not.toHaveBeenCalled()
  })

  it('handleEmail opens mailto: link with customer email', async () => {
    const { handleEmail } = await import('../CustomerListScreen')
    handleEmail('john@example.com')
    expect(windowOpenSpy).toHaveBeenCalledWith('mailto:john@example.com', '_system')
  })

  it('handleEmail does nothing when email is null', async () => {
    const { handleEmail } = await import('../CustomerListScreen')
    handleEmail(null)
    expect(windowOpenSpy).not.toHaveBeenCalled()
  })

  it('handleSms opens sms: link with customer phone', async () => {
    const { handleSms } = await import('../CustomerListScreen')
    handleSms('021-555-1234')
    expect(windowOpenSpy).toHaveBeenCalledWith('sms:021-555-1234', '_system')
  })

  it('handleSms does nothing when phone is null', async () => {
    const { handleSms } = await import('../CustomerListScreen')
    handleSms(null)
    expect(windowOpenSpy).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// CustomerCreateScreen Tests
// ---------------------------------------------------------------------------

describe('CustomerCreateScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: list endpoint for any background fetches
    mockGet.mockResolvedValue({ data: { customers: [], total: 0 } })
  })

  // -------------------------------------------------------------------------
  // Requirement 7.5 — Validation
  // -------------------------------------------------------------------------

  it('shows validation error when first name is empty', async () => {
    const user = userEvent.setup()
    const CustomerCreateScreen = (await import('../CustomerCreateScreen')).default
    render(<CustomerCreateScreen />, { wrapper: Wrapper })

    // Submit without filling in first name
    await user.click(screen.getByRole('button', { name: /Create Customer/i }))

    await waitFor(() => {
      expect(screen.getByText('First name is required')).toBeInTheDocument()
    })
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('shows validation error for invalid email', async () => {
    const user = userEvent.setup()
    const CustomerCreateScreen = (await import('../CustomerCreateScreen')).default
    render(<CustomerCreateScreen />, { wrapper: Wrapper })

    await user.type(screen.getByPlaceholderText('First name'), 'John')
    await user.type(screen.getByPlaceholderText('email@example.com'), 'not-an-email')
    await user.click(screen.getByRole('button', { name: /Create Customer/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid email address')).toBeInTheDocument()
    })
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('submits form with only first name and navigates to profile', async () => {
    mockPost.mockResolvedValue({ data: { id: 'new-cust-1' } })
    const user = userEvent.setup()
    const CustomerCreateScreen = (await import('../CustomerCreateScreen')).default
    render(<CustomerCreateScreen />, { wrapper: Wrapper })

    await user.type(screen.getByPlaceholderText('First name'), 'Alice')
    await user.click(screen.getByRole('button', { name: /Create Customer/i }))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/api/v1/customers', {
        first_name: 'Alice',
      })
    })
    expect(mockNavigate).toHaveBeenCalledWith('/customers/new-cust-1', { replace: true })
  })

  it('submits form with all fields populated', async () => {
    mockPost.mockResolvedValue({ data: { id: 'new-cust-2' } })
    const user = userEvent.setup()
    const CustomerCreateScreen = (await import('../CustomerCreateScreen')).default
    render(<CustomerCreateScreen />, { wrapper: Wrapper })

    await user.type(screen.getByPlaceholderText('First name'), 'John')
    await user.type(screen.getByPlaceholderText('Last name'), 'Doe')
    await user.type(screen.getByPlaceholderText('email@example.com'), 'john@example.com')
    await user.type(screen.getByPlaceholderText('Phone number'), '021-555-1234')
    await user.type(screen.getByPlaceholderText('Company name'), 'Doe Plumbing')
    await user.type(screen.getByPlaceholderText('Street address'), '123 Main St')
    await user.click(screen.getByRole('button', { name: /Create Customer/i }))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/api/v1/customers', {
        first_name: 'John',
        last_name: 'Doe',
        email: 'john@example.com',
        phone: '021-555-1234',
        company: 'Doe Plumbing',
        address: '123 Main St',
      })
    })
  })

  it('displays API error when creation fails', async () => {
    mockPost.mockRejectedValue({
      response: { data: { detail: 'Customer already exists' } },
    })
    const user = userEvent.setup()
    const CustomerCreateScreen = (await import('../CustomerCreateScreen')).default
    render(<CustomerCreateScreen />, { wrapper: Wrapper })

    await user.type(screen.getByPlaceholderText('First name'), 'John')
    await user.click(screen.getByRole('button', { name: /Create Customer/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Customer already exists')
    })
  })

  it('clears field error when user starts typing', async () => {
    const user = userEvent.setup()
    const CustomerCreateScreen = (await import('../CustomerCreateScreen')).default
    render(<CustomerCreateScreen />, { wrapper: Wrapper })

    // Trigger validation error
    await user.click(screen.getByRole('button', { name: /Create Customer/i }))
    await waitFor(() => {
      expect(screen.getByText('First name is required')).toBeInTheDocument()
    })

    // Start typing — error should clear
    await user.type(screen.getByPlaceholderText('First name'), 'A')
    expect(screen.queryByText('First name is required')).not.toBeInTheDocument()
  })

  it('navigates back when Cancel is tapped', async () => {
    const user = userEvent.setup()
    const CustomerCreateScreen = (await import('../CustomerCreateScreen')).default
    render(<CustomerCreateScreen />, { wrapper: Wrapper })

    await user.click(screen.getByRole('button', { name: /Cancel/i }))
    expect(mockNavigate).toHaveBeenCalledWith(-1)
  })
})

// ---------------------------------------------------------------------------
// validateCustomerForm unit tests
// ---------------------------------------------------------------------------

describe('validateCustomerForm', () => {
  it('returns error when first_name is empty', async () => {
    const { validateCustomerForm } = await import('../CustomerCreateScreen')
    const errors = validateCustomerForm({ first_name: '' })
    expect(errors.first_name).toBe('First name is required')
  })

  it('returns error when first_name is whitespace only', async () => {
    const { validateCustomerForm } = await import('../CustomerCreateScreen')
    const errors = validateCustomerForm({ first_name: '   ' })
    expect(errors.first_name).toBe('First name is required')
  })

  it('returns no errors for valid first_name only', async () => {
    const { validateCustomerForm } = await import('../CustomerCreateScreen')
    const errors = validateCustomerForm({ first_name: 'Alice' })
    expect(Object.keys(errors)).toHaveLength(0)
  })

  it('returns email error for invalid email', async () => {
    const { validateCustomerForm } = await import('../CustomerCreateScreen')
    const errors = validateCustomerForm({ first_name: 'Alice', email: 'bad' })
    expect(errors.email).toBe('Invalid email address')
  })

  it('accepts valid email', async () => {
    const { validateCustomerForm } = await import('../CustomerCreateScreen')
    const errors = validateCustomerForm({ first_name: 'Alice', email: 'alice@example.com' })
    expect(errors.email).toBeUndefined()
  })

  it('ignores empty optional email', async () => {
    const { validateCustomerForm } = await import('../CustomerCreateScreen')
    const errors = validateCustomerForm({ first_name: 'Alice', email: '' })
    expect(errors.email).toBeUndefined()
  })
})
