import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

// Track the onSelectProduct callback from ProductGrid
let capturedOnSelectProduct: ((product: any) => void) | null = null

vi.mock('../ProductGrid', () => ({
  default: (props: { onSelectProduct: (p: any) => void }) => {
    capturedOnSelectProduct = props.onSelectProduct
    return <div data-testid="product-grid">ProductGrid</div>
  },
}))

// Track the onCheckout callback from OrderPanel
let capturedOnCheckout: (() => void) | null = null

vi.mock('../OrderPanel', () => ({
  default: (props: { onCheckout: () => void; lineItems: any[] }) => {
    capturedOnCheckout = props.onCheckout
    return (
      <div data-testid="order-panel">
        <span data-testid="line-item-count">{props.lineItems.length}</span>
        <button onClick={props.onCheckout} data-testid="checkout-btn">Checkout</button>
      </div>
    )
  },
  calculateOrderTotals: () => ({ subtotal: 100, orderDisc: 0, taxAmount: 15, total: 115 }),
}))

// Track the onComplete callback from PaymentPanel
let capturedOnComplete: ((payment: any) => void) | null = null

vi.mock('../PaymentPanel', () => ({
  default: (props: { total: number; onComplete: (p: any) => void; onCancel: () => void }) => {
    capturedOnComplete = props.onComplete
    return (
      <div data-testid="payment-panel">
        <button
          onClick={() => props.onComplete({ method: 'cash', cashTendered: 120, changeGiven: 5 })}
          data-testid="complete-payment-btn"
        >
          Complete Payment
        </button>
      </div>
    )
  },
}))

vi.mock('../SyncStatus', () => ({
  default: () => null,
}))

vi.mock('../types', () => ({}))

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

vi.mock('@/utils/posReceiptPrinter', () => ({
  printReceipt: vi.fn(),
  browserPrintReceipt: vi.fn(),
  NoPrinterError: class NoPrinterError extends Error {
    constructor(message: string) {
      super(message)
      this.name = 'NoPrinterError'
    }
  },
  setFallbackMode: vi.fn(),
}))

vi.mock('@/utils/invoiceReceiptMapper', () => ({
  formatReceiptDate: vi.fn(() => '01/01/2025'),
}))

vi.mock('@/utils/escpos', () => ({}))

vi.mock('@/utils/posOfflineStore', () => ({
  saveTransaction: vi.fn().mockResolvedValue(undefined),
  getPendingCount: vi.fn().mockResolvedValue(0),
}))

vi.mock('@/utils/posSyncManager', () => ({
  posSyncManager: { subscribe: vi.fn(() => () => {}) },
}))

vi.mock('@/utils/barcodeScanner', () => ({
  scanBarcodeFromCamera: vi.fn(),
}))

vi.mock('@/components/pos/PrinterErrorModal', () => ({
  default: (props: { open: boolean; errorMessage: string; onClose: () => void; onBrowserPrint: (f: boolean) => void }) =>
    props.open ? (
      <div data-testid="printer-error-modal">
        <span data-testid="printer-error-message">{props.errorMessage}</span>
        <button onClick={props.onClose}>Close</button>
        <button onClick={() => props.onBrowserPrint(false)}>Use Browser Print</button>
      </div>
    ) : null,
}))

/* ------------------------------------------------------------------ */
/*  Imports (after mocks)                                              */
/* ------------------------------------------------------------------ */

import apiClient from '@/api/client'
import { printReceipt, NoPrinterError } from '@/utils/posReceiptPrinter'
import POSScreen from '../POSScreen'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function createMockProduct(overrides: Record<string, unknown> = {}) {
  return {
    id: 'prod-1',
    name: 'Widget',
    sku: 'WDG-001',
    barcode: null,
    category_id: null,
    category_name: null,
    sale_price: 50,
    cost_price: 25,
    stock_quantity: 100,
    unit_of_measure: 'each',
    images: [],
    is_active: true,
    ...overrides,
  }
}

/**
 * Drives the POSScreen through the full payment flow:
 * 1. Add a product via ProductGrid mock
 * 2. Click checkout via OrderPanel mock
 * 3. Complete payment via PaymentPanel mock
 * Returns after the payment complete overlay is visible.
 */
async function completePaymentFlow() {
  // 1. Add a product
  await act(async () => {
    capturedOnSelectProduct?.(createMockProduct())
  })

  // 2. Click checkout
  await act(async () => {
    capturedOnCheckout?.()
  })

  // 3. Complete payment
  await act(async () => {
    capturedOnComplete?.({ method: 'cash', cashTendered: 120, changeGiven: 5 })
  })

  // Wait for the payment complete overlay
  await waitFor(() => {
    expect(screen.getByText('Payment Complete')).toBeInTheDocument()
  })
}

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  capturedOnSelectProduct = null
  capturedOnCheckout = null
  capturedOnComplete = null

  vi.mocked(apiClient.post).mockResolvedValue({ data: {} })
  vi.mocked(printReceipt).mockResolvedValue({ success: true, method: 'printer' })
})

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('POSScreen — Print Receipt integration', () => {
  /**
   * Validates: Requirements 7.2
   * Print Receipt button appears after payment completion.
   */
  it('shows Print Receipt button after payment completion', async () => {
    render(<POSScreen />)

    // Before payment, no Print Receipt button
    expect(screen.queryByRole('button', { name: /Print Receipt/i })).not.toBeInTheDocument()

    await completePaymentFlow()

    expect(screen.getByRole('button', { name: /Print Receipt/i })).toBeInTheDocument()
  })

  /**
   * Validates: Requirements 7.3
   * Clicking Print Receipt calls printReceipt and shows success toast.
   */
  it('calls printReceipt and shows success toast when Print Receipt is clicked', async () => {
    const user = userEvent.setup()
    render(<POSScreen />)
    await completePaymentFlow()

    await user.click(screen.getByRole('button', { name: /Print Receipt/i }))

    await waitFor(() => {
      expect(printReceipt).toHaveBeenCalledTimes(1)
    })

    await waitFor(() => {
      expect(screen.getByText('Receipt printed successfully')).toBeInTheDocument()
    })
  })

  /**
   * Validates: Requirements 7.4
   * Print error opens PrinterErrorModal with error details.
   */
  it('opens PrinterErrorModal when printReceipt throws NoPrinterError', async () => {
    vi.mocked(printReceipt).mockRejectedValue(
      new NoPrinterError('No default printer configured. Please set up a printer in Printer Settings.')
    )

    const user = userEvent.setup()
    render(<POSScreen />)
    await completePaymentFlow()

    await user.click(screen.getByRole('button', { name: /Print Receipt/i }))

    await waitFor(() => {
      expect(screen.getByTestId('printer-error-modal')).toBeInTheDocument()
    })

    expect(screen.getByTestId('printer-error-message')).toHaveTextContent(
      /No default printer configured/
    )
  })
})
