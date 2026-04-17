import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

/**
 * Validates: Requirements 61.1-61.5
 * - 61.1: Secure web interface accessible via unique token link (no account creation)
 * - 61.2: Display invoice history, outstanding balances, and payment history
 * - 61.3: Pay outstanding invoices via Stripe from the portal
 * - 61.4: Display vehicle service history with dates and services performed
 * - 61.5: Reflect organisation branding (logo, colours)
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import { PortalPage } from '../pages/portal/PortalPage'
import { InvoiceHistory } from '../pages/portal/InvoiceHistory'
import { VehicleHistory } from '../pages/portal/VehicleHistory'
import { PaymentPage } from '../pages/portal/PaymentPage'
import type { PortalInvoice } from '../pages/portal/InvoiceHistory'

/* ── Test data factories ── */

function makePortalInfo(overrides: Record<string, unknown> = {}) {
  return {
    customer_name: 'Jane Smith',
    email: 'jane@example.com',
    phone: '021 555 1234',
    org_name: 'Kiwi Motors',
    logo_url: 'https://example.com/logo.png',
    primary_color: '#16a34a',
    outstanding_balance: 250.0,
    total_invoices: 5,
    total_paid: 1200.0,
    ...overrides,
  }
}

function makeInvoice(overrides: Partial<PortalInvoice> = {}): PortalInvoice {
  return {
    id: 'inv-001',
    invoice_number: 'INV-0042',
    issue_date: '2024-06-01T00:00:00Z',
    due_date: '2024-06-21T00:00:00Z',
    status: 'issued',
    total: 350.0,
    balance_due: 350.0,
    line_items_summary: 'Full service, Oil filter',
    ...overrides,
  }
}

function makeVehicle(overrides: Record<string, unknown> = {}) {
  return {
    id: 'v-001',
    rego: 'ABC123',
    make: 'Toyota',
    model: 'Corolla',
    year: 2020,
    colour: 'Silver',
    wof_expiry: '2025-03-15',
    rego_expiry: '2025-06-01',
    services: [
      {
        invoice_number: 'INV-0042',
        date: '2024-06-01',
        description: 'Full service',
        total: 350.0,
      },
    ],
    ...overrides,
  }
}

function renderWithRouter(ui: React.ReactElement, { route = '/portal/test-token-123' } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/portal/:token" element={ui} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Customer Portal Pages', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('PortalPage', () => {
    function setupPortalMocks(portalInfo = makePortalInfo()) {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url.endsWith('/invoices')) return Promise.resolve({ data: { invoices: [], org_has_stripe_connect: false, total_outstanding: 0, total_paid: 0 } })
        if (url.endsWith('/vehicles')) return Promise.resolve({ data: [] })
        return Promise.resolve({ data: portalInfo })
      })
    }

    // 61.1: Secure access via token link
    it('fetches portal info using the token from the URL', async () => {
      setupPortalMocks()

      renderWithRouter(<PortalPage />)

      expect(apiClient.get).toHaveBeenCalledWith('/portal/test-token-123')
      expect(await screen.findByText('Welcome, Jane Smith')).toBeInTheDocument()
    })

    // 61.1: Shows error for invalid/expired token
    it('shows error when token is invalid or expired', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Not found'))

      renderWithRouter(<PortalPage />)

      expect(await screen.findByText(/unable to load your portal/i)).toBeInTheDocument()
    })

    // 61.2: Displays outstanding balance
    it('displays outstanding balance and invoice summary cards', async () => {
      setupPortalMocks(makePortalInfo({ outstanding_balance: 250.0, total_invoices: 5, total_paid: 1200.0 }))

      renderWithRouter(<PortalPage />)

      expect(await screen.findByText('Outstanding Balance')).toBeInTheDocument()
      expect(screen.getByText('$250.00')).toBeInTheDocument()
      expect(screen.getByText('Total Invoices')).toBeInTheDocument()
      expect(screen.getByText('5')).toBeInTheDocument()
      expect(screen.getByText('Total Paid')).toBeInTheDocument()
      expect(screen.getByText('$1,200.00')).toBeInTheDocument()
    })

    // 61.5: Reflects organisation branding
    it('displays organisation name in the welcome message', async () => {
      setupPortalMocks(makePortalInfo({ org_name: 'Kiwi Motors' }))

      renderWithRouter(<PortalPage />)

      expect(await screen.findByText(/kiwi motors/i)).toBeInTheDocument()
    })

    // 61.2 + 61.4: Shows tabs for invoices and vehicles
    it('renders Invoices and Vehicles tabs', async () => {
      setupPortalMocks()

      renderWithRouter(<PortalPage />)

      expect(await screen.findByRole('tab', { name: 'Invoices' })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: 'Vehicles' })).toBeInTheDocument()
    })

    // Loading state
    it('shows loading spinner while fetching portal info', () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))

      renderWithRouter(<PortalPage />)

      expect(screen.getByRole('status', { name: /loading portal/i })).toBeInTheDocument()
    })
  })

  describe('InvoiceHistory', () => {
    /** Helper to build a PortalInvoicesResponse shape */
    function makeInvoicesResponse(
      invoices: PortalInvoice[],
      overrides: { org_has_stripe_connect?: boolean } = {},
    ) {
      return {
        invoices,
        org_has_stripe_connect: overrides.org_has_stripe_connect ?? true,
        total_outstanding: 0,
        total_paid: 0,
      }
    }

    // 61.2: Displays invoice history
    it('displays invoice list with status badges', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse([
          makeInvoice({ id: 'i1', invoice_number: 'INV-0042', status: 'issued', total: 350 }),
          makeInvoice({ id: 'i2', invoice_number: 'INV-0041', status: 'paid', total: 200, balance_due: 0 }),
        ]),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      expect(await screen.findByText('INV-0042')).toBeInTheDocument()
      expect(screen.getByText('INV-0041')).toBeInTheDocument()
      expect(screen.getByText('Issued')).toBeInTheDocument()
      expect(screen.getByText('Paid')).toBeInTheDocument()
    })

    // 61.2: Shows outstanding balance per invoice
    it('shows balance due for unpaid invoices', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse([makeInvoice({ balance_due: 150, total: 350 })]),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      expect(await screen.findByText('$150.00 due')).toBeInTheDocument()
    })

    // 61.3 + 5.1: Pay Now button shown when org has Stripe Connect and invoice is payable
    it('shows Pay Now button for invoices with outstanding balance when org has Stripe Connect', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse([makeInvoice({ balance_due: 350, status: 'issued' })]),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      expect(await screen.findByRole('button', { name: /pay now/i })).toBeInTheDocument()
    })

    // 5.5: No Pay Now button when org has no Stripe Connect
    it('does not show Pay Now button when org has no Stripe Connect', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse(
          [makeInvoice({ balance_due: 350, status: 'issued' })],
          { org_has_stripe_connect: false },
        ),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      await screen.findByText('INV-0042')
      expect(screen.queryByRole('button', { name: /pay now/i })).not.toBeInTheDocument()
    })

    // 5.1: Pay Now shown for partially_paid and overdue statuses
    it('shows Pay Now button for partially_paid and overdue invoices', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse([
          makeInvoice({ id: 'i1', invoice_number: 'INV-0050', balance_due: 100, status: 'partially_paid' }),
          makeInvoice({ id: 'i2', invoice_number: 'INV-0051', balance_due: 200, status: 'overdue' }),
        ]),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      const buttons = await screen.findAllByRole('button', { name: /pay now/i })
      expect(buttons).toHaveLength(2)
    })

    // 5.1: No Pay Now button for voided invoices even with Stripe Connect
    it('does not show Pay Now button for voided invoices', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse([makeInvoice({ status: 'voided', balance_due: 350 })]),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      await screen.findByText('INV-0042')
      expect(screen.queryByRole('button', { name: /pay now/i })).not.toBeInTheDocument()
    })

    // 61.3: No Pay Now button for paid invoices
    it('does not show Pay Now button for fully paid invoices', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse([makeInvoice({ status: 'paid', balance_due: 0 })]),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      await screen.findByText('INV-0042')
      expect(screen.queryByRole('button', { name: /pay now/i })).not.toBeInTheDocument()
    })

    // Empty state
    it('shows empty message when no invoices exist', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: makeInvoicesResponse([]),
      })

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      expect(await screen.findByText(/no invoices found/i)).toBeInTheDocument()
    })

    // Error state
    it('shows error when invoices fail to load', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('fail'))

      render(<InvoiceHistory token="test-token" primaryColor="#2563eb" />)

      expect(await screen.findByText(/failed to load invoices/i)).toBeInTheDocument()
    })
  })

  describe('VehicleHistory', () => {
    // 61.4: Displays vehicle service history
    it('displays vehicles with rego, make, model, year', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: [makeVehicle()],
      })

      render(<VehicleHistory token="test-token" />)

      expect(await screen.findByText('ABC123')).toBeInTheDocument()
      expect(screen.getByText('2020 Toyota Corolla')).toBeInTheDocument()
    })

    // 61.4: Expiry badges shown (WOF/Rego)
    it('displays WOF and rego expiry badges', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: [makeVehicle({ wof_expiry: '2025-03-15', rego_expiry: '2025-06-01' })],
      })

      render(<VehicleHistory token="test-token" />)

      await screen.findByText('ABC123')
      expect(screen.getAllByText(/WOF:/i).length).toBeGreaterThan(0)
      expect(screen.getAllByText(/Rego:/i).length).toBeGreaterThan(0)
    })

    // 61.4: Expanding vehicle shows service history
    it('shows service history when vehicle is expanded', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: [makeVehicle()],
      })
      const user = userEvent.setup()

      render(<VehicleHistory token="test-token" />)

      const vehicleButton = await screen.findByRole('button', { name: /abc123/i })
      await user.click(vehicleButton)

      expect(screen.getByText('Full service')).toBeInTheDocument()
      expect(screen.getByText('INV-0042')).toBeInTheDocument()
    })

    // Empty state
    it('shows empty message when no vehicles exist', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] })

      render(<VehicleHistory token="test-token" />)

      expect(await screen.findByText(/no vehicles found/i)).toBeInTheDocument()
    })

    // Error state
    it('shows error when vehicles fail to load', async () => {
      ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('fail'))

      render(<VehicleHistory token="test-token" />)

      expect(await screen.findByText(/failed to load vehicle history/i)).toBeInTheDocument()
    })
  })

  describe('PaymentPage', () => {
    const baseInvoice = makeInvoice({ balance_due: 350, total: 350 })

    // 61.3: Shows invoice payment summary
    it('displays invoice payment summary with amount due', () => {
      render(
        <PaymentPage
          token="test-token"
          invoice={baseInvoice}
          primaryColor="#2563eb"
          onBack={vi.fn()}
        />,
      )

      expect(screen.getByText('Pay Invoice INV-0042')).toBeInTheDocument()
      expect(screen.getByText('Amount Due')).toBeInTheDocument()
      expect(screen.getAllByText('$350.00').length).toBeGreaterThan(0)
    })

    // 61.3: Shows already paid amount for partial payments
    it('shows already paid amount for partially paid invoices', () => {
      const partialInvoice = makeInvoice({ total: 500, balance_due: 200 })

      render(
        <PaymentPage
          token="test-token"
          invoice={partialInvoice}
          primaryColor="#2563eb"
          onBack={vi.fn()}
        />,
      )

      expect(screen.getByText('Already Paid')).toBeInTheDocument()
      expect(screen.getByText('$300.00')).toBeInTheDocument()
      expect(screen.getByText('$200.00')).toBeInTheDocument()
    })

    // 61.3: Clicking Pay calls the Stripe payment API
    it('calls Stripe payment API and redirects on success', async () => {
      const hrefSetter = vi.fn()
      Object.defineProperty(window, 'location', {
        value: { href: '' },
        writable: true,
        configurable: true,
      })
      Object.defineProperty(window.location, 'href', {
        set: hrefSetter,
        get: () => '',
        configurable: true,
      })

      ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
        data: { checkout_url: 'https://checkout.stripe.com/session123' },
      })

      const user = userEvent.setup()
      render(
        <PaymentPage
          token="test-token"
          invoice={baseInvoice}
          primaryColor="#2563eb"
          onBack={vi.fn()}
        />,
      )

      await user.click(screen.getByRole('button', { name: /pay \$350\.00/i }))

      expect(apiClient.post).toHaveBeenCalledWith('/portal/test-token/pay/inv-001')
      expect(hrefSetter).toHaveBeenCalledWith('https://checkout.stripe.com/session123')
    })

    // 61.3: Shows error when payment fails
    it('shows error when payment initiation fails', async () => {
      ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('fail'))

      const user = userEvent.setup()
      render(
        <PaymentPage
          token="test-token"
          invoice={baseInvoice}
          primaryColor="#2563eb"
          onBack={vi.fn()}
        />,
      )

      await user.click(screen.getByRole('button', { name: /pay \$350\.00/i }))

      expect(await screen.findByText(/unable to start payment/i)).toBeInTheDocument()
    })

    // Back button calls onBack
    it('calls onBack when back button is clicked', async () => {
      const onBack = vi.fn()
      const user = userEvent.setup()

      render(
        <PaymentPage
          token="test-token"
          invoice={baseInvoice}
          primaryColor="#2563eb"
          onBack={onBack}
        />,
      )

      await user.click(screen.getByText('← Back to invoices'))

      expect(onBack).toHaveBeenCalled()
    })

    // Cancel button calls onBack
    it('calls onBack when Cancel button is clicked', async () => {
      const onBack = vi.fn()
      const user = userEvent.setup()

      render(
        <PaymentPage
          token="test-token"
          invoice={baseInvoice}
          primaryColor="#2563eb"
          onBack={onBack}
        />,
      )

      await user.click(screen.getByRole('button', { name: 'Cancel' }))

      expect(onBack).toHaveBeenCalled()
    })
  })
})
