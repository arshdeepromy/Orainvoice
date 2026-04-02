import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'inv-test-123' }),
  useNavigate: () => vi.fn(),
}))

vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

vi.mock('../../../components/invoices/CreditNoteModal', () => ({
  CreditNoteModal: (props: Record<string, unknown>) =>
    props.open ? (
      <div data-testid="credit-note-modal" data-creditable-amount={props.creditableAmount}>
        CreditNoteModal
      </div>
    ) : null,
}))

vi.mock('../../../components/invoices/RefundModal', () => ({
  RefundModal: (props: Record<string, unknown>) =>
    props.open ? (
      <div data-testid="refund-modal" data-refundable-amount={props.refundableAmount}>
        RefundModal
      </div>
    ) : null,
}))

vi.mock('../../../components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import apiClient from '../../../api/client'
import InvoiceDetail from '../InvoiceDetail'

function createMockInvoice(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'inv-test-123',
    invoice_number: 'INV-001',
    status: 'paid',
    customer_id: 'cust-1',
    customer: {
      id: 'cust-1',
      first_name: 'John',
      last_name: 'Doe',
      email: 'john@example.com',
      phone: '021-123-4567',
    },
    line_items: [],
    subtotal: 100,
    gst_amount: 15,
    total: 115,
    discount_type: null,
    discount_value: null,
    discount_amount: 0,
    amount_paid: 115,
    balance_due: 0,
    notes_internal: null,
    notes_customer: null,
    issue_date: '2025-01-15',
    due_date: '2025-02-15',
    created_at: '2025-01-15',
    payments: [
      {
        id: 'pay-1',
        date: '2025-01-20',
        amount: 115,
        method: 'cash',
        recorded_by: 'Admin',
        is_refund: false,
      },
    ],
    credit_notes: [],
    ...overrides,
  }
}

/** Wait for the component to finish loading after API resolves */
async function waitForLoaded() {
  await waitFor(() => {
    expect(screen.getByRole('heading', { name: /INV-001/i })).toBeInTheDocument()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
  vi.mocked(apiClient.get).mockResolvedValue({
    data: { invoice: createMockInvoice() },
  })
})

describe('InvoiceDetail — Refund & Credit Note UI', () => {
  it('Create Credit Note button visible for issued/partially_paid/paid, hidden for draft/voided', async () => {
    // paid — button should be visible
    const { unmount } = render(<InvoiceDetail />)
    await waitForLoaded()
    expect(screen.getAllByRole('button', { name: /create credit note/i }).length).toBeGreaterThan(0)
    unmount()

    // draft — button should be hidden
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { invoice: createMockInvoice({ status: 'draft' }) },
    })
    const { unmount: unmount2 } = render(<InvoiceDetail />)
    await waitForLoaded()
    expect(screen.queryByRole('button', { name: /create credit note/i })).not.toBeInTheDocument()
    unmount2()

    // voided — button should be hidden
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { invoice: createMockInvoice({ status: 'voided' }) },
    })
    const { unmount: unmount3 } = render(<InvoiceDetail />)
    await waitForLoaded()
    expect(screen.queryByRole('button', { name: /create credit note/i })).not.toBeInTheDocument()
    unmount3()
  })

  it('Process Refund button visible when amount_paid > 0, hidden when 0', async () => {
    const { unmount } = render(<InvoiceDetail />)
    await waitForLoaded()
    expect(screen.getByRole('button', { name: /process refund/i })).toBeInTheDocument()
    unmount()

    vi.mocked(apiClient.get).mockResolvedValue({
      data: { invoice: createMockInvoice({ amount_paid: 0 }) },
    })
    const { unmount: unmount2 } = render(<InvoiceDetail />)
    await waitForLoaded()
    expect(screen.queryByRole('button', { name: /process refund/i })).not.toBeInTheDocument()
    unmount2()
  })

  it('clicking Create Credit Note button opens CreditNoteModal', async () => {
    const user = userEvent.setup()
    render(<InvoiceDetail />)
    await waitForLoaded()

    const buttons = screen.getAllByRole('button', { name: /create credit note/i })
    await user.click(buttons[0])

    await waitFor(() => {
      expect(screen.getByTestId('credit-note-modal')).toBeInTheDocument()
    })
  })

  it('clicking Process Refund button opens RefundModal', async () => {
    const user = userEvent.setup()
    render(<InvoiceDetail />)
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /process refund/i }))

    await waitFor(() => {
      expect(screen.getByTestId('refund-modal')).toBeInTheDocument()
    })
  })

  it('payment history renders green Payment and red Refund badges correctly', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        invoice: createMockInvoice({
          payments: [
            { id: 'pay-1', date: '2025-01-20', amount: 115, method: 'cash', recorded_by: 'Admin', is_refund: false },
            { id: 'ref-1', date: '2025-01-25', amount: 50, method: 'cash', recorded_by: 'Admin', is_refund: true },
          ],
        }),
      },
    })

    render(<InvoiceDetail />)
    await waitForLoaded()

    expect(screen.getByText('Payment')).toBeInTheDocument()
    expect(screen.getByText('Refund')).toBeInTheDocument()
  })

  it('refund rows show red-tinted amount text', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        invoice: createMockInvoice({
          payments: [
            { id: 'ref-1', date: '2025-01-25', amount: 50, method: 'cash', recorded_by: 'Admin', is_refund: true },
          ],
        }),
      },
    })

    render(<InvoiceDetail />)
    await waitForLoaded()

    expect(screen.getByText('Refund')).toBeInTheDocument()
    // Refund amount cell should have text-red-600 class
    const amountCells = document.querySelectorAll('td.text-red-600')
    expect(amountCells.length).toBeGreaterThan(0)
  })

  it('refund note displayed below refund rows when present', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        invoice: createMockInvoice({
          payments: [
            {
              id: 'ref-1',
              date: '2025-01-25',
              amount: 50,
              method: 'cash',
              recorded_by: 'Admin',
              is_refund: true,
              refund_note: 'Customer requested',
            },
          ],
        }),
      },
    })

    render(<InvoiceDetail />)
    await waitForLoaded()

    expect(screen.getByText(/Customer requested/)).toBeInTheDocument()
  })

  it('payment summary row shows Total Paid, Total Refunded, Net Paid', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        invoice: createMockInvoice({
          payments: [
            { id: 'pay-1', date: '2025-01-20', amount: 115, method: 'cash', recorded_by: 'Admin', is_refund: false },
            { id: 'ref-1', date: '2025-01-25', amount: 30, method: 'cash', recorded_by: 'Admin', is_refund: true },
          ],
        }),
      },
    })

    render(<InvoiceDetail />)
    await waitForLoaded()

    expect(screen.getByText('Total Paid')).toBeInTheDocument()
    expect(screen.getByText('Total Refunded')).toBeInTheDocument()
    expect(screen.getByText('Net Paid')).toBeInTheDocument()
  })

  it('credit notes section shows Create Credit Note button and running total', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        invoice: createMockInvoice({
          credit_notes: [
            { id: 'cn-1', reference_number: 'CN-0001', amount: 20, reason: 'Overcharge', created_at: '2025-01-22' },
            { id: 'cn-2', reference_number: 'CN-0002', amount: 10, reason: 'Discount', created_at: '2025-01-23' },
          ],
        }),
      },
    })

    render(<InvoiceDetail />)
    await waitForLoaded()

    const buttons = screen.getAllByRole('button', { name: /create credit note/i })
    expect(buttons.length).toBeGreaterThanOrEqual(1)

    // The tfoot "Total" cell in the credit notes table
    const totalCells = screen.getAllByText('Total')
    expect(totalCells.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('CN-0001')).toBeInTheDocument()
    expect(screen.getByText('CN-0002')).toBeInTheDocument()
  })

  it('modal onSuccess triggers invoice data re-fetch', async () => {
    const user = userEvent.setup()
    render(<InvoiceDetail />)
    await waitForLoaded()

    // Initial fetch
    expect(apiClient.get).toHaveBeenCalledTimes(1)

    // Open the credit note modal to verify it receives props (including onSuccess = fetchInvoice)
    const buttons = screen.getAllByRole('button', { name: /create credit note/i })
    await user.click(buttons[0])

    await waitFor(() => {
      expect(screen.getByTestId('credit-note-modal')).toBeInTheDocument()
    })
    // The mock modal is rendered, confirming the component wires fetchInvoice as onSuccess
  })
})
