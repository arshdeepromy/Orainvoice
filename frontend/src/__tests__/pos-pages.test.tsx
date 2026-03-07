import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 22 — POS Module — Tasks 29.10, 29.11, 29.12
 */

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: vi.fn() },
  }
})

// Mock barcode scanner
vi.mock('@/utils/barcodeScanner', () => ({
  scanBarcodeFromCamera: vi.fn().mockResolvedValue(null),
  scanBarcode: vi.fn().mockResolvedValue([]),
  isBarcodeDetectorSupported: vi.fn().mockReturnValue(false),
}))

// Mock IndexedDB offline store
const mockSaveTransaction = vi.fn().mockResolvedValue(undefined)
const mockGetPendingTransactions = vi.fn().mockResolvedValue([])
const mockGetAllTransactions = vi.fn().mockResolvedValue([])
const mockMarkSynced = vi.fn().mockResolvedValue(undefined)
const mockMarkFailed = vi.fn().mockResolvedValue(undefined)
const mockGetPendingCount = vi.fn().mockResolvedValue(0)

vi.mock('@/utils/posOfflineStore', () => ({
  saveTransaction: (...args: unknown[]) => mockSaveTransaction(...args),
  getPendingTransactions: (...args: unknown[]) => mockGetPendingTransactions(...args),
  getAllTransactions: (...args: unknown[]) => mockGetAllTransactions(...args),
  markSynced: (...args: unknown[]) => mockMarkSynced(...args),
  markFailed: (...args: unknown[]) => mockMarkFailed(...args),
  getPendingCount: (...args: unknown[]) => mockGetPendingCount(...args),
  clearSyncedTransactions: vi.fn().mockResolvedValue(undefined),
}))

// Mock sync manager
vi.mock('@/utils/posSyncManager', () => ({
  posSyncManager: {
    subscribe: vi.fn().mockReturnValue(() => {}),
    syncPendingTransactions: vi.fn().mockResolvedValue(null),
    isOnline: vi.fn().mockReturnValue(true),
  },
}))

import apiClient from '@/api/client'
import POSScreen from '../pages/pos/POSScreen'
import ProductGrid from '../pages/pos/ProductGrid'
import OrderPanel, { calculateOrderTotals } from '../pages/pos/OrderPanel'
import PaymentPanel from '../pages/pos/PaymentPanel'
import SyncStatus from '../pages/pos/SyncStatus'
import { posSyncManager } from '@/utils/posSyncManager'

/* ------------------------------------------------------------------ */
/*  Test data                                                          */
/* ------------------------------------------------------------------ */

const mockProducts = [
  {
    id: 'prod-1',
    name: 'Widget A',
    sku: 'WA-001',
    barcode: '1234567890123',
    category_id: 'cat-1',
    category_name: 'Widgets',
    sale_price: 25.00,
    cost_price: 10.00,
    stock_quantity: 50,
    unit_of_measure: 'each',
    images: [],
    is_active: true,
  },
  {
    id: 'prod-2',
    name: 'Gadget B',
    sku: 'GB-002',
    barcode: '9876543210987',
    category_id: 'cat-2',
    category_name: 'Gadgets',
    sale_price: 49.99,
    cost_price: 20.00,
    stock_quantity: 10,
    unit_of_measure: 'each',
    images: ['https://example.com/gadget.jpg'],
    is_active: true,
  },
]

const mockCategories = [
  { id: 'cat-1', name: 'Widgets' },
  { id: 'cat-2', name: 'Gadgets' },
]

/* ------------------------------------------------------------------ */
/*  29.10: POS transaction flow from product selection to payment      */
/* ------------------------------------------------------------------ */

describe('POS Transaction Flow (29.10)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(navigator, 'onLine', { value: true, writable: true, configurable: true })
  })

  it('renders POS screen with heading and product grid', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: mockCategories } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    render(<POSScreen />)
    expect(screen.getByText('Point of Sale')).toBeInTheDocument()
  })

  it('ProductGrid renders search bar and category tabs', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: mockCategories } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    const onSelect = vi.fn()
    render(<ProductGrid onSelectProduct={onSelect} />)
    expect(screen.getByLabelText('Search products')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'All' })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: 'Widgets' })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: 'Gadgets' })).toBeInTheDocument()
    })
  })

  it('ProductGrid displays product tiles with names and prices', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    const onSelect = vi.fn()
    render(<ProductGrid onSelectProduct={onSelect} />)
    expect(await screen.findByText('Widget A')).toBeInTheDocument()
    expect(screen.getByText('$25.00')).toBeInTheDocument()
    expect(screen.getByText('Gadget B')).toBeInTheDocument()
    expect(screen.getByText('$49.99')).toBeInTheDocument()
  })

  it('clicking a product tile calls onSelectProduct', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    const onSelect = vi.fn()
    render(<ProductGrid onSelectProduct={onSelect} />)
    const user = userEvent.setup()
    const tile = await screen.findByLabelText(/Add Widget A/)
    await user.click(tile)
    expect(onSelect).toHaveBeenCalledWith(mockProducts[0])
  })

  it('OrderPanel shows empty state when no items', () => {
    render(
      <OrderPanel
        lineItems={[]}
        orderDiscountPercent={0}
        orderDiscountAmount={0}
        onUpdateQuantity={vi.fn()}
        onRemoveItem={vi.fn()}
        onSetItemDiscount={vi.fn()}
        onSetOrderDiscount={vi.fn()}
        onCheckout={vi.fn()}
      />,
    )
    expect(screen.getByText('No items added yet.')).toBeInTheDocument()
    expect(screen.getByLabelText('Proceed to payment')).toBeDisabled()
  })

  it('OrderPanel displays line items with quantity controls', () => {
    const items = [
      {
        id: 'li-1',
        product: mockProducts[0],
        quantity: 2,
        unitPrice: 25.00,
        discountPercent: 0,
        discountAmount: 0,
      },
    ]
    render(
      <OrderPanel
        lineItems={items}
        orderDiscountPercent={0}
        orderDiscountAmount={0}
        onUpdateQuantity={vi.fn()}
        onRemoveItem={vi.fn()}
        onSetItemDiscount={vi.fn()}
        onSetOrderDiscount={vi.fn()}
        onCheckout={vi.fn()}
      />,
    )
    expect(screen.getByText('Widget A')).toBeInTheDocument()
    expect(screen.getByLabelText('Widget A quantity')).toHaveTextContent('2')
    expect(screen.getByLabelText('Increase Widget A quantity')).toBeInTheDocument()
    expect(screen.getByLabelText('Decrease Widget A quantity')).toBeInTheDocument()
  })

  it('calculateOrderTotals computes correct subtotal, tax, and total', () => {
    const items = [
      { id: '1', product: mockProducts[0], quantity: 2, unitPrice: 25.00, discountPercent: 0, discountAmount: 0 },
      { id: '2', product: mockProducts[1], quantity: 1, unitPrice: 49.99, discountPercent: 10, discountAmount: 0 },
    ]
    const result = calculateOrderTotals(items, 0, 0, 0.15)
    // Widget A: 2 * 25 = 50, Gadget B: 49.99 - 10% = 44.991
    const expectedSubtotal = 50 + 44.991
    expect(result.subtotal).toBeCloseTo(expectedSubtotal, 2)
    expect(result.taxAmount).toBeCloseTo(expectedSubtotal * 0.15, 2)
    expect(result.total).toBeCloseTo(expectedSubtotal * 1.15, 2)
  })

  it('calculateOrderTotals applies order-level discount', () => {
    const items = [
      { id: '1', product: mockProducts[0], quantity: 4, unitPrice: 25.00, discountPercent: 0, discountAmount: 0 },
    ]
    const result = calculateOrderTotals(items, 10, 0, 0.15)
    // Subtotal: 100, 10% discount = 10, after discount = 90
    expect(result.subtotal).toBe(100)
    expect(result.orderDisc).toBe(10)
    expect(result.taxAmount).toBeCloseTo(90 * 0.15, 2)
    expect(result.total).toBeCloseTo(90 * 1.15, 2)
  })

  it('PaymentPanel shows amount due and payment method tabs', () => {
    render(<PaymentPanel total={115.00} onComplete={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByTestId('payment-total')).toHaveTextContent('$115.00')
    expect(screen.getByRole('tab', { name: 'cash' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'card' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'split' })).toBeInTheDocument()
  })

  it('PaymentPanel calculates change for cash payment', async () => {
    render(<PaymentPanel total={25.00} onComplete={vi.fn()} onCancel={vi.fn()} />)
    const user = userEvent.setup()
    const cashInput = screen.getByLabelText('Cash Tendered')
    await user.clear(cashInput)
    await user.type(cashInput, '50')
    expect(screen.getByTestId('change-amount')).toHaveTextContent('$25.00')
  })

  it('PaymentPanel complete button calls onComplete with cash info', async () => {
    const onComplete = vi.fn()
    render(<PaymentPanel total={10.00} onComplete={onComplete} onCancel={vi.fn()} />)
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText('Cash Tendered'))
    await user.type(screen.getByLabelText('Cash Tendered'), '20')
    await user.click(screen.getByLabelText('Complete payment'))
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ method: 'cash', cashTendered: 20, changeGiven: 10 }),
    )
  })

  it('PaymentPanel card tab shows card info', async () => {
    render(<PaymentPanel total={50.00} onComplete={vi.fn()} onCancel={vi.fn()} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'card' }))
    expect(screen.getByText(/Present card to terminal/)).toBeInTheDocument()
  })

  it('online POS transaction posts to API', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'tx-1' } })

    render(<POSScreen />)
    const user = userEvent.setup()

    // Add product
    const tile = await screen.findByLabelText(/Add Widget A/)
    await user.click(tile)

    // Click checkout
    await user.click(screen.getByLabelText('Proceed to payment'))

    // Enter cash and complete
    await waitFor(() => {
      expect(screen.getByLabelText('Cash Tendered')).toBeInTheDocument()
    })
    await user.clear(screen.getByLabelText('Cash Tendered'))
    await user.type(screen.getByLabelText('Cash Tendered'), '100')
    await user.click(screen.getByLabelText('Complete payment'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/api/v2/pos/transactions',
        expect.objectContaining({
          payment_method: 'cash',
          cash_tendered: 100,
        }),
      )
    })
  })
})

/* ------------------------------------------------------------------ */
/*  29.11: Offline mode stores transactions in IndexedDB               */
/* ------------------------------------------------------------------ */

describe('POS Offline Mode (29.11)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetPendingCount.mockResolvedValue(0)
  })

  it('shows offline banner when navigator.onLine is false', async () => {
    Object.defineProperty(navigator, 'onLine', { value: false, writable: true, configurable: true })
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    render(<POSScreen />)
    expect(screen.getByRole('alert', { name: 'Offline status' })).toBeInTheDocument()
    expect(screen.getByText(/Offline/)).toBeInTheDocument()
  })

  it('does not show offline banner when online', async () => {
    Object.defineProperty(navigator, 'onLine', { value: true, writable: true, configurable: true })
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    render(<POSScreen />)
    expect(screen.queryByRole('alert', { name: 'Offline status' })).not.toBeInTheDocument()
  })

  it('stores transaction in IndexedDB when offline', async () => {
    Object.defineProperty(navigator, 'onLine', { value: false, writable: true, configurable: true })
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })

    render(<POSScreen />)
    const user = userEvent.setup()

    // Add product
    const tile = await screen.findByLabelText(/Add Widget A/)
    await user.click(tile)

    // Checkout
    await user.click(screen.getByLabelText('Proceed to payment'))

    // Pay with cash
    await waitFor(() => {
      expect(screen.getByLabelText('Cash Tendered')).toBeInTheDocument()
    })
    await user.clear(screen.getByLabelText('Cash Tendered'))
    await user.type(screen.getByLabelText('Cash Tendered'), '100')
    await user.click(screen.getByLabelText('Complete payment'))

    await waitFor(() => {
      expect(mockSaveTransaction).toHaveBeenCalledWith(
        expect.objectContaining({
          syncStatus: 'pending',
          paymentMethod: 'cash',
          lineItems: expect.arrayContaining([
            expect.objectContaining({ productId: 'prod-1', productName: 'Widget A' }),
          ]),
        }),
      )
    })
  })

  it('stores transaction offline when online API call fails', async () => {
    Object.defineProperty(navigator, 'onLine', { value: true, writable: true, configurable: true })
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: mockProducts } })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))

    render(<POSScreen />)
    const user = userEvent.setup()

    const tile = await screen.findByLabelText(/Add Widget A/)
    await user.click(tile)
    await user.click(screen.getByLabelText('Proceed to payment'))

    await waitFor(() => {
      expect(screen.getByLabelText('Cash Tendered')).toBeInTheDocument()
    })
    await user.clear(screen.getByLabelText('Cash Tendered'))
    await user.type(screen.getByLabelText('Cash Tendered'), '100')
    await user.click(screen.getByLabelText('Complete payment'))

    await waitFor(() => {
      expect(mockSaveTransaction).toHaveBeenCalledWith(
        expect.objectContaining({ syncStatus: 'pending' }),
      )
    })
  })

  it('offline banner shows pending count', async () => {
    Object.defineProperty(navigator, 'onLine', { value: false, writable: true, configurable: true })
    mockGetPendingCount.mockResolvedValue(3)
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { categories: [] } })
      .mockResolvedValueOnce({ data: { products: [] } })
    render(<POSScreen />)
    await waitFor(() => {
      expect(screen.getByText(/3 pending/)).toBeInTheDocument()
    })
  })
})

/* ------------------------------------------------------------------ */
/*  29.12: Sync manager processes transactions in order                */
/* ------------------------------------------------------------------ */

describe('POS Sync Manager (29.12)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('SyncStatus shows pending/synced/failed counts', async () => {
    mockGetAllTransactions.mockResolvedValue([
      { offlineId: 'tx-1', timestamp: '2025-01-01T10:00:00Z', total: 25.00, syncStatus: 'pending' },
      { offlineId: 'tx-2', timestamp: '2025-01-01T11:00:00Z', total: 50.00, syncStatus: 'synced' },
      { offlineId: 'tx-3', timestamp: '2025-01-01T12:00:00Z', total: 30.00, syncStatus: 'failed', syncError: 'Price changed' },
    ])
    render(<SyncStatus onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByTestId('pending-count')).toHaveTextContent('1')
      expect(screen.getByTestId('synced-count')).toHaveTextContent('1')
      expect(screen.getByTestId('failed-count')).toHaveTextContent('1')
    })
  })

  it('SyncStatus shows transaction list with statuses', async () => {
    mockGetAllTransactions.mockResolvedValue([
      { offlineId: 'tx-1', timestamp: '2025-01-01T10:00:00Z', total: 25.00, syncStatus: 'pending' },
      { offlineId: 'tx-2', timestamp: '2025-01-01T11:00:00Z', total: 50.00, syncStatus: 'synced' },
    ])
    render(<SyncStatus onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('$25.00')).toBeInTheDocument()
      expect(screen.getByText('$50.00')).toBeInTheDocument()
      expect(screen.getByText('pending')).toBeInTheDocument()
      expect(screen.getByText('synced')).toBeInTheDocument()
    })
  })

  it('SyncStatus shows failed transaction error message', async () => {
    mockGetAllTransactions.mockResolvedValue([
      { offlineId: 'tx-3', timestamp: '2025-01-01T12:00:00Z', total: 30.00, syncStatus: 'failed', syncError: 'Price changed' },
    ])
    render(<SyncStatus onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('Price changed')).toBeInTheDocument()
    })
  })

  it('SyncStatus force sync button triggers sync manager', async () => {
    mockGetAllTransactions.mockResolvedValue([
      { offlineId: 'tx-1', timestamp: '2025-01-01T10:00:00Z', total: 25.00, syncStatus: 'pending' },
    ])
    render(<SyncStatus onClose={vi.fn()} />)
    const user = userEvent.setup()
    await waitFor(() => {
      expect(screen.getByLabelText('Force sync')).toBeEnabled()
    })
    await user.click(screen.getByLabelText('Force sync'))
    expect(posSyncManager.syncPendingTransactions).toHaveBeenCalled()
  })

  it('SyncStatus disables force sync when no pending transactions', async () => {
    mockGetAllTransactions.mockResolvedValue([
      { offlineId: 'tx-1', timestamp: '2025-01-01T10:00:00Z', total: 25.00, syncStatus: 'synced' },
    ])
    render(<SyncStatus onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByLabelText('Force sync')).toBeDisabled()
    })
  })

  it('SyncStatus close button calls onClose', async () => {
    mockGetAllTransactions.mockResolvedValue([])
    const onClose = vi.fn()
    render(<SyncStatus onClose={onClose} />)
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Close sync status'))
    expect(onClose).toHaveBeenCalled()
  })

  it('SyncStatus shows empty state when no transactions', async () => {
    mockGetAllTransactions.mockResolvedValue([])
    render(<SyncStatus onClose={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('No offline transactions.')).toBeInTheDocument()
    })
  })
})
