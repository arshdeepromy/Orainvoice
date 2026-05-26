/**
 * Unit tests for the QR Partial Payment modal-mediated flow on InvoiceDetail.
 *
 * Validates: Requirements 1.6, 1.7, 1.8
 *
 * Mirrors the InvoiceList.qrPartial test for the standalone InvoiceDetail page.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'inv-1' }),
  useNavigate: () => vi.fn(),
  useLocation: () => ({ pathname: '/invoices/inv-1', state: null, key: 'k1', search: '', hash: '' }),
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
}))

vi.mock('../../../contexts/ModuleContext', () => ({
  useModules: () => ({
    isEnabled: () => false,
  }),
}))

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'a@b.com', name: 'A B', role: 'org_admin', org_id: 'org-1' },
  }),
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
  getPaymentBadgeType: () => ({ label: 'Payment', color: 'green' }),
  shouldShowRefundNote: () => false,
  formatNZD: (v: number) => `$${(v ?? 0).toFixed(2)}`,
}))

vi.mock('../../../utils/posReceiptPrinter', () => ({
  printInvoiceReceipt: vi.fn(),
  browserPrintReceipt: vi.fn(),
  NoPrinterError: class NoPrinterError extends Error {},
  setFallbackMode: vi.fn(),
}))

vi.mock('../../../utils/invoiceReceiptMapper', () => ({
  invoiceToReceiptData: () => ({}),
}))

vi.mock('../../../components/pos/POSReceiptPreview', () => ({
  default: () => null,
}))

vi.mock('../../../components/pos/PrinterErrorModal', () => ({
  default: () => null,
}))

vi.mock('../compliance/LinkedComplianceDocs', () => ({
  default: () => null,
}))

vi.mock('@/utils/vehicleHelpers', () => ({
  getInspectionLabel: () => 'WOF',
  getInspectionExpiry: () => null,
}))

// Stub the QR waiting popup so the test focuses on the modal-mediated flow,
// not the polling popup behaviour (covered separately).
vi.mock('../QrPaymentWaitingPopup', () => ({
  QrPaymentWaitingPopup: () => <div data-testid="qr-waiting-popup" />,
}))

/**
 * Replace the QrPaymentAmountModal with a test stub that exposes the actions
 * the test cares about. The real modal already has its own dedicated test suite.
 */
vi.mock('../QrPaymentAmountModal', () => ({
  QrPaymentAmountModal: ({
    open,
    onClose,
    onContinue,
  }: {
    open: boolean
    onClose: () => void
    onContinue: (amount: number | null) => void
  }) =>
    open ? (
      <div data-testid="qr-amount-modal">
        <button data-testid="modal-continue-full" onClick={() => onContinue(null)}>
          Continue Full
        </button>
        <button data-testid="modal-continue-partial" onClick={() => onContinue(100)}>
          Continue Partial 100
        </button>
        <button data-testid="modal-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}))

// Replace heavy UI primitives with simple stubs so the page renders quickly.
vi.mock('../../../components/ui', () => ({
  Button: ({ children, loading, disabled, onClick, ...rest }: any) => (
    <button onClick={onClick} disabled={disabled || loading} {...rest}>
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

import apiClient from '../../../api/client'
import InvoiceDetail from '../InvoiceDetail'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function createInvoice(overrides: Record<string, unknown> = {}) {
  return {
    id: 'inv-1',
    invoice_number: 'INV-2026-001',
    status: 'issued',
    customer_id: 'cust-1',
    customer: {
      id: 'cust-1',
      first_name: 'John',
      last_name: 'Doe',
      email: 'john@example.com',
      phone: '021-555-0001',
    },
    line_items: [],
    subtotal: 174,
    gst_amount: 26,
    total: 200,
    discount_type: null,
    discount_value: null,
    discount_amount: 0,
    amount_paid: 0,
    balance_due: 200,
    notes_internal: null,
    notes_customer: null,
    issue_date: '2026-01-10',
    due_date: '2026-02-10',
    created_at: '2026-01-10T00:00:00Z',
    payments: [],
    credit_notes: [],
    ...overrides,
  }
}

function setupHappyPathMocks(invoiceOverrides: Record<string, unknown> = {}) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === '/payments/online-payments/status') {
      return Promise.resolve({
        data: {
          is_connected: true,
          account_id_last4: '1234',
          connect_client_id_configured: true,
          application_fee_percent: 1,
        },
      })
    }
    if (url.startsWith('/invoices/inv-1')) {
      return Promise.resolve({ data: { invoice: createInvoice(invoiceOverrides) } })
    }
    return Promise.resolve({ data: {} })
  })
}

async function waitForLoaded() {
  await waitFor(() => {
    expect(screen.getAllByRole('heading', { name: /INV-2026-001/i }).length).toBeGreaterThan(0)
  })
}

async function waitForQrPaymentButton() {
  await waitFor(() => {
    expect(screen.getByRole('button', { name: /^QR Payment$/i })).toBeInTheDocument()
  })
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('InvoiceDetail — QR Partial Payment modal-mediated flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupHappyPathMocks()
  })

  it('clicking the QR Payment button opens the modal without making an API call', async () => {
    const user = userEvent.setup()
    render(<InvoiceDetail />)
    await waitForLoaded()
    await waitForQrPaymentButton()

    // No POSTs have been made before clicking
    expect(apiClient.post).not.toHaveBeenCalled()
    expect(screen.queryByTestId('qr-amount-modal')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^QR Payment$/i }))

    expect(screen.getByTestId('qr-amount-modal')).toBeInTheDocument()
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('Continue with Full submits the API call with `{invoice_id}` only (no amount)', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        session_id: 'cs_test_123',
        amount: 200,
        invoice_number: 'INV-2026-001',
        amount_cents: 20000,
        expires_at: '2026-01-10T01:00:00Z',
      },
    })

    render(<InvoiceDetail />)
    await waitForLoaded()
    await waitForQrPaymentButton()

    await user.click(screen.getByRole('button', { name: /^QR Payment$/i }))
    await user.click(screen.getByTestId('modal-continue-full'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledTimes(1)
    })
    expect(apiClient.post).toHaveBeenCalledWith('/payments/qr-session/existing', {
      invoice_id: 'inv-1',
    })
  })

  it('Continue with Partial submits the API call with `{invoice_id, amount}` formatted to 2dp', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        session_id: 'cs_test_456',
        amount: 100,
        invoice_number: 'INV-2026-001',
        amount_cents: 10000,
        expires_at: '2026-01-10T01:00:00Z',
      },
    })

    render(<InvoiceDetail />)
    await waitForLoaded()
    await waitForQrPaymentButton()

    await user.click(screen.getByRole('button', { name: /^QR Payment$/i }))
    await user.click(screen.getByTestId('modal-continue-partial'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledTimes(1)
    })
    expect(apiClient.post).toHaveBeenCalledWith('/payments/qr-session/existing', {
      invoice_id: 'inv-1',
      amount: '100.00',
    })
  })

  it('closing the modal without choosing an action makes no API call', async () => {
    const user = userEvent.setup()

    render(<InvoiceDetail />)
    await waitForLoaded()
    await waitForQrPaymentButton()

    await user.click(screen.getByRole('button', { name: /^QR Payment$/i }))
    expect(screen.getByTestId('qr-amount-modal')).toBeInTheDocument()

    await user.click(screen.getByTestId('modal-close'))

    await waitFor(() => {
      expect(screen.queryByTestId('qr-amount-modal')).not.toBeInTheDocument()
    })
    expect(apiClient.post).not.toHaveBeenCalled()
  })
})
