import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'test-id' }),
  useNavigate: () => vi.fn(),
}))

vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

vi.mock('../../../utils/posReceiptPrinter', () => ({
  printInvoiceReceipt: vi.fn(),
  browserPrintReceipt: vi.fn(),
  NoPrinterError: class NoPrinterError extends Error {
    constructor(message: string) {
      super(message)
      this.name = 'NoPrinterError'
    }
  },
  setFallbackMode: vi.fn(),
}))

vi.mock('../../../utils/invoiceReceiptMapper', () => ({
  invoiceToReceiptData: vi.fn(() => ({})),
}))

vi.mock('../../../components/pos/POSReceiptPreview', () => ({
  default: () => <div data-testid="pos-receipt-preview">POSReceiptPreview</div>,
}))

vi.mock('../../../components/pos/PrinterErrorModal', () => ({
  default: (props: { open: boolean; errorMessage: string; onClose: () => void; onBrowserPrint: (f: boolean) => void }) =>
    props.open ? (
      <div data-testid="printer-error-modal">
        <span data-testid="printer-error-message">{props.errorMessage}</span>
        <button onClick={props.onClose}>Close</button>
        <button onClick={() => props.onBrowserPrint(false)}>Use Browser Print</button>
      </div>
    ) : null,
}))

vi.mock('../../../components/ui', () => ({
  Button: ({ children, loading, disabled, onClick, ...rest }: any) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      {...rest}
    >
      {children}
    </button>
  ),
  Badge: ({ children }: any) => <span>{children}</span>,
  Spinner: ({ label }: any) => <div role="status">{label}</div>,
  Modal: ({ open, children, title, onClose }: any) =>
    open ? (
      <div role="dialog" aria-label={title}>
        <button onClick={onClose} aria-label="Close dialog">×</button>
        {children}
      </div>
    ) : null,
}))

vi.mock('../../../components/common/ModuleGate', () => ({
  ModuleGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../../../components/invoices/CreditNoteModal', () => ({
  CreditNoteModal: () => null,
}))

vi.mock('../../../components/invoices/RefundModal', () => ({
  RefundModal: () => null,
}))

vi.mock('../../../components/invoices/refund-credit-note.utils', () => ({
  computeCreditableAmount: () => 0,
  computePaymentSummary: () => ({ totalPaid: 0, totalRefunded: 0, netPaid: 0 }),
  isCreditNoteButtonVisible: () => false,
  isRefundButtonVisible: () => false,
  getPaymentBadgeType: (isRefund: boolean) =>
    isRefund ? { label: 'Refund', color: 'red' } : { label: 'Payment', color: 'green' },
  shouldShowRefundNote: () => false,
  formatNZD: (v: number) => `$${(v ?? 0).toFixed(2)}`,
}))

/* ------------------------------------------------------------------ */
/*  Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import apiClient from '../../../api/client'
import { printInvoiceReceipt, NoPrinterError } from '../../../utils/posReceiptPrinter'
import InvoiceDetail from '../InvoiceDetail'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function createMockInvoice(overrides: Record<string, unknown> = {}) {
  return {
    id: 'test-id',
    invoice_number: 'INV-100',
    status: 'issued',
    customer_id: 'cust-1',
    customer: {
      id: 'cust-1',
      first_name: 'Jane',
      last_name: 'Smith',
      email: 'jane@example.com',
      phone: '021-000-0000',
    },
    line_items: [],
    subtotal: 100,
    gst_amount: 15,
    total: 115,
    discount_type: null,
    discount_value: null,
    discount_amount: 0,
    amount_paid: 0,
    balance_due: 115,
    notes_internal: null,
    notes_customer: null,
    issue_date: '2025-03-01',
    due_date: '2025-04-01',
    created_at: '2025-03-01',
    payments: [],
    credit_notes: [],
    ...overrides,
  }
}

async function waitForLoaded() {
  await waitFor(() => {
    expect(screen.getByRole('heading', { level: 1, name: /INV-100/ })).toBeInTheDocument()
  })
}

/* ------------------------------------------------------------------ */
/*  Setup / Teardown                                                   */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiClient.get).mockResolvedValue({
    data: { invoice: createMockInvoice() },
  })
  vi.mocked(printInvoiceReceipt).mockResolvedValue({ success: true, method: 'printer' })
})

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('InvoiceDetail — POS Print integration', () => {
  /**
   * Validates: Requirements 1.1, 1.6
   * POS Print button visible for non-draft, hidden for draft.
   */
  it('shows POS Print button when invoice status is issued', async () => {
    render(<InvoiceDetail />)
    await waitForLoaded()

    expect(screen.getByRole('button', { name: /POS Print/i })).toBeInTheDocument()
  })

  it('hides POS Print button when invoice status is draft', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { invoice: createMockInvoice({ status: 'draft', invoice_number: null }) },
    })

    render(<InvoiceDetail />)
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: /Draft Invoice/ })).toBeInTheDocument()
    })

    expect(screen.queryByRole('button', { name: /POS Print/i })).not.toBeInTheDocument()
  })

  /**
   * Validates: Requirements 1.3
   * Button shows "Printing…" text while print is in progress.
   */
  it('shows "Printing…" text while POS print is in progress', async () => {
    // Make printInvoiceReceipt hang until we resolve it
    let resolvePrint!: (value: { success: boolean; method: 'printer' | 'browser' }) => void
    vi.mocked(printInvoiceReceipt).mockImplementation(
      () => new Promise((resolve) => { resolvePrint = resolve })
    )

    const user = userEvent.setup()
    render(<InvoiceDetail />)
    await waitForLoaded()

    const btn = screen.getByRole('button', { name: /POS Print/i })
    await user.click(btn)

    // While printing, button text should change to "Printing…"
    await waitFor(() => {
      expect(screen.getByText('Printing…')).toBeInTheDocument()
    })

    // Resolve the print to clean up
    await act(async () => {
      resolvePrint({ success: true, method: 'printer' })
    })
  })

  /**
   * Validates: Requirements 1.4, 8.2
   * Success toast "Receipt printed successfully" appears after successful print.
   */
  it('shows success toast after successful POS print', async () => {
    const user = userEvent.setup()
    render(<InvoiceDetail />)
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /POS Print/i }))

    await waitFor(() => {
      expect(screen.getByText('Receipt printed successfully')).toBeInTheDocument()
    })
  })

  /**
   * Validates: Requirements 1.4, 8.2
   * Success toast auto-dismisses after 3 seconds.
   */
  it('auto-dismisses success toast after 3 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

    render(<InvoiceDetail />)
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /POS Print/i }))

    await waitFor(() => {
      expect(screen.getByText('Receipt printed successfully')).toBeInTheDocument()
    })

    // Advance past the 3-second auto-dismiss timer
    act(() => {
      vi.advanceTimersByTime(3100)
    })

    await waitFor(() => {
      expect(screen.queryByText('Receipt printed successfully')).not.toBeInTheDocument()
    })

    vi.useRealTimers()
  })

  /**
   * Validates: Requirements 1.5
   * NoPrinterError opens the PrinterErrorModal.
   */
  it('opens PrinterErrorModal when NoPrinterError is thrown', async () => {
    vi.mocked(printInvoiceReceipt).mockRejectedValue(
      new NoPrinterError('No default printer configured. Please set up a printer in Printer Settings.')
    )

    const user = userEvent.setup()
    render(<InvoiceDetail />)
    await waitForLoaded()

    await user.click(screen.getByRole('button', { name: /POS Print/i }))

    await waitFor(() => {
      expect(screen.getByTestId('printer-error-modal')).toBeInTheDocument()
    })

    expect(screen.getByTestId('printer-error-message')).toHaveTextContent(
      /No default printer configured/
    )
  })
})
