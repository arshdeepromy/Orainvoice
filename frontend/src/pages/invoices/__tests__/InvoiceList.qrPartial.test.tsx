/**
 * Unit tests for the QR Partial Payment modal-mediated flow on InvoiceList.
 *
 * Validates: Requirements 1.6, 1.7, 1.8
 *
 * Scenarios covered:
 * - Click QR Payment → modal opens
 * - Modal Continue with Full → apiClient.post called with `{invoice_id}` only
 * - Modal Continue with Partial typed value → apiClient.post called with `{invoice_id, amount: '100.00'}`
 * - Modal Close → no API call made
 */

import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

const mockNavigate = vi.fn()

vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({ id: 'inv-1' }),
  useLocation: () => ({ pathname: '/invoices/inv-1', state: null, key: 'k1', search: '', hash: '' }),
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}))

vi.mock('@/contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport', settings: {} }),
}))

vi.mock('@/contexts/BranchContext', () => ({
  useBranch: () => ({ branches: [], selectedBranchId: null }),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u1', email: 'a@b.com', name: 'A B', role: 'org_admin', org_id: 'org-1' },
  }),
}))

vi.mock('@/utils/navigationGuard', () => ({
  checkNavigationGuard: () => true,
  setNavigationGuard: vi.fn(),
  clearNavigationGuard: vi.fn(),
}))

vi.mock('@/utils/invoiceTemplateStyles', () => ({
  resolveTemplateStyles: () => ({}),
}))

vi.mock('@/components/invoices/AttachmentList', () => ({
  default: () => null,
}))

vi.mock('@/utils/vehicleHelpers', () => ({
  getInspectionLabel: () => 'WOF',
  getInspectionExpiry: () => null,
}))

vi.mock('../../../utils/buildVehicleDisplayFields', () => ({
  buildVehicleDisplayFields: () => [],
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

vi.mock('../../../components/invoices/CreditNoteModal', () => ({
  CreditNoteModal: () => null,
}))

vi.mock('../../../components/invoices/RefundModal', () => ({
  RefundModal: () => null,
}))

vi.mock('../../../components/pos/POSReceiptPreview', () => ({
  default: () => null,
}))

vi.mock('../../../utils/invoiceReceiptMapper', () => ({
  invoiceToReceiptData: () => ({}),
}))

// Avoid loading the full InvoiceCreate component (it pulls in a large
// dependency graph) — render an empty stub instead.
vi.mock('../InvoiceCreate', () => ({
  default: () => null,
}))

// Stub the QR waiting popup so the test focuses on the modal-mediated flow,
// not on the polling popup behaviour (covered separately).
vi.mock('../QrPaymentWaitingPopup', () => ({
  QrPaymentWaitingPopup: () => <div data-testid="qr-waiting-popup" />,
}))

/**
 * Replace the QrPaymentAmountModal with a test stub that exposes the actions
 * the test cares about: continue-with-full, continue-with-partial, and close.
 * The real modal already has its own dedicated test suite.
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

// Replace heavy UI primitives with simple stubs so list/detail render quickly.
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
import InvoiceList from '../InvoiceList'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function createInvoice(overrides: Record<string, unknown> = {}) {
  return {
    id: 'inv-1',
    invoice_number: 'INV-2026-001',
    customer_name: 'John Doe',
    customer_id: 'cust-1',
    total: 200,
    balance_due: 200,
    amount_paid: 0,
    status: 'issued',
    issue_date: '2026-01-10',
    due_date: '2026-02-10',
    created_at: '2026-01-10T00:00:00Z',
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
    discount_type: null,
    discount_value: null,
    discount_amount: 0,
    payments: [],
    credit_notes: [],
    notes_internal: null,
    notes_customer: null,
    ...overrides,
  }
}

/**
 * Configure the apiClient mock with the responses the InvoiceList page needs
 * on mount: a connected Stripe status, a list with one invoice, and the
 * matching detail object.
 */
function setupHappyPathMocks(invoiceOverrides: Record<string, unknown> = {}) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === '/payments/online-payments/status') {
      return Promise.resolve({ data: { is_connected: true, account_id_last4: '1234' } })
    }
    if (url === '/invoices') {
      return Promise.resolve({
        data: { items: [createInvoice(invoiceOverrides)], total: 1 },
      })
    }
    if (url === '/invoices/inv-1') {
      return Promise.resolve({ data: { invoice: createInvoice(invoiceOverrides) } })
    }
    return Promise.resolve({ data: {} })
  })
}

async function waitForQrPaymentButton() {
  await waitFor(() => {
    const buttons = screen.getAllByRole('button', { name: /qr payment/i })
    expect(buttons.length).toBeGreaterThan(0)
  })
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('InvoiceList — QR Partial Payment modal-mediated flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupHappyPathMocks()
  })

  it('clicking the QR Payment button opens the modal without making an API call', async () => {
    const user = userEvent.setup()

    await act(async () => {
      render(<InvoiceList />)
    })

    await waitForQrPaymentButton()

    // No POSTs have been made before clicking
    expect(apiClient.post).not.toHaveBeenCalled()

    // Modal is not open before click
    expect(screen.queryByTestId('qr-amount-modal')).not.toBeInTheDocument()

    const qrButton = screen.getAllByRole('button', { name: /qr payment/i })[0]
    await user.click(qrButton)

    expect(screen.getByTestId('qr-amount-modal')).toBeInTheDocument()
    // Still no API calls — the button only opens the modal
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

    await act(async () => {
      render(<InvoiceList />)
    })
    await waitForQrPaymentButton()

    await user.click(screen.getAllByRole('button', { name: /qr payment/i })[0])
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

    await act(async () => {
      render(<InvoiceList />)
    })
    await waitForQrPaymentButton()

    await user.click(screen.getAllByRole('button', { name: /qr payment/i })[0])
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

    await act(async () => {
      render(<InvoiceList />)
    })
    await waitForQrPaymentButton()

    await user.click(screen.getAllByRole('button', { name: /qr payment/i })[0])
    expect(screen.getByTestId('qr-amount-modal')).toBeInTheDocument()

    await user.click(screen.getByTestId('modal-close'))

    await waitFor(() => {
      expect(screen.queryByTestId('qr-amount-modal')).not.toBeInTheDocument()
    })
    expect(apiClient.post).not.toHaveBeenCalled()
  })
})
