/**
 * Unit tests for Report Issue button on InvoiceDetail page.
 *
 * Requirements: 8.1-8.4
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'inv-123' }),
  useNavigate: () => mockNavigate,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

vi.mock('../../../contexts/TenantContext', () => ({
  useTenant: () => ({ tradeFamily: 'automotive-transport' }),
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
  computeCreditableAmount: () => 100,
  computePaymentSummary: () => ({ totalPaid: 0, totalRefunded: 0, netPaid: 0 }),
  isCreditNoteButtonVisible: () => false,
  isRefundButtonVisible: () => false,
  getPaymentBadgeType: () => ({ label: 'Payment', color: 'green' }),
  shouldShowRefundNote: () => false,
  formatNZD: (v: number) => `$${v.toFixed(2)}`,
}))

import apiClient from '../../../api/client'
import InvoiceDetail from '../InvoiceDetail'

function createMockInvoice(overrides: Record<string, unknown> = {}) {
  return {
    id: 'inv-123',
    invoice_number: 'INV-001',
    status: 'paid',
    customer_id: 'cust-456',
    customer: {
      id: 'cust-456',
      first_name: 'John',
      last_name: 'Doe',
      email: 'john@example.com',
      phone: '021-555-0001',
    },
    vehicle: null,
    line_items: [
      { id: 'li-1', item_type: 'part', description: 'Brake Pad', quantity: 2, unit_price: 50, line_total: 100 },
    ],
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
    issue_date: '2025-03-01',
    due_date: '2025-03-20',
    created_at: '2025-03-01T10:00:00Z',
    payments: [],
    credit_notes: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
})

describe('InvoiceDetail — Report Issue button', () => {
  it('renders Report Issue button for non-voided invoice', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { invoice: createMockInvoice() } })
    render(<InvoiceDetail />)

    await waitFor(() => {
      expect(screen.getByText('Report Issue')).toBeInTheDocument()
    })
  })

  it('does not render Report Issue button for voided invoice', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { invoice: createMockInvoice({ status: 'voided' }) },
    })
    render(<InvoiceDetail />)

    await waitFor(() => {
      expect(screen.getAllByText('INV-001').length).toBeGreaterThanOrEqual(1)
    })

    expect(screen.queryByText('Report Issue')).not.toBeInTheDocument()
  })

  it('navigates to claim form with invoice_id and customer_id pre-populated', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.get).mockResolvedValue({ data: { invoice: createMockInvoice() } })
    render(<InvoiceDetail />)

    await waitFor(() => {
      expect(screen.getByText('Report Issue')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Report Issue'))
    expect(mockNavigate).toHaveBeenCalledWith(
      '/claims/new?invoice_id=inv-123&customer_id=cust-456'
    )
  })
})
