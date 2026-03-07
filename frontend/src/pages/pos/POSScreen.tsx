/**
 * Full-screen touch-optimised POS layout with product grid (left)
 * and order panel (right). Includes offline indicator banner,
 * barcode scanner integration, and payment flow.
 *
 * Validates: Requirement 22.1–22.10 — POS Module
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import ProductGrid from './ProductGrid'
import OrderPanel, { calculateOrderTotals } from './OrderPanel'
import PaymentPanel from './PaymentPanel'
import SyncStatus from './SyncStatus'
import { saveTransaction, getPendingCount } from '@/utils/posOfflineStore'
import { posSyncManager } from '@/utils/posSyncManager'
import { scanBarcodeFromCamera } from '@/utils/barcodeScanner'
import type { POSProduct, POSLineItem, PaymentInfo, OfflineTransaction } from './types'

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export default function POSScreen() {
  const [lineItems, setLineItems] = useState<POSLineItem[]>([])
  const [orderDiscountPercent, setOrderDiscountPercent] = useState(0)
  const [orderDiscountAmount, setOrderDiscountAmount] = useState(0)
  const [showPayment, setShowPayment] = useState(false)
  const [showSyncStatus, setShowSyncStatus] = useState(false)
  const [isOnline, setIsOnline] = useState(navigator.onLine)
  const [pendingCount, setPendingCount] = useState(0)
  const [scanning, setScanning] = useState(false)
  const barcodeBufferRef = useRef('')
  const barcodeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Track online/offline status
  useEffect(() => {
    const goOnline = () => setIsOnline(true)
    const goOffline = () => setIsOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  // Update pending count
  const refreshPendingCount = useCallback(async () => {
    try {
      const count = await getPendingCount()
      setPendingCount(count)
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => { refreshPendingCount() }, [refreshPendingCount])

  // Subscribe to sync manager updates
  useEffect(() => {
    return posSyncManager.subscribe((_state, count) => {
      setPendingCount(count)
    })
  }, [])

  // USB/Bluetooth barcode scanner: listen for keyboard input pattern
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if user is typing in an input field
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if (e.key === 'Enter' && barcodeBufferRef.current.length >= 4) {
        const barcode = barcodeBufferRef.current
        barcodeBufferRef.current = ''
        lookupBarcode(barcode)
      } else if (e.key.length === 1) {
        barcodeBufferRef.current += e.key
        if (barcodeTimerRef.current) clearTimeout(barcodeTimerRef.current)
        barcodeTimerRef.current = setTimeout(() => { barcodeBufferRef.current = '' }, 200)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const lookupBarcode = async (barcode: string) => {
    try {
      const res = await apiClient.get(`/api/v2/products/barcode/${encodeURIComponent(barcode)}`)
      if (res.data) {
        addProduct(res.data)
      }
    } catch {
      /* product not found — ignore */
    }
  }

  const handleCameraScan = async () => {
    setScanning(true)
    try {
      const result = await scanBarcodeFromCamera()
      if (result) {
        await lookupBarcode(result.rawValue)
      }
    } finally {
      setScanning(false)
    }
  }

  const addProduct = (product: POSProduct) => {
    setLineItems((prev) => {
      const existing = prev.find((li) => li.product.id === product.id)
      if (existing) {
        return prev.map((li) =>
          li.product.id === product.id ? { ...li, quantity: li.quantity + 1 } : li,
        )
      }
      return [
        ...prev,
        {
          id: generateId(),
          product,
          quantity: 1,
          unitPrice: product.sale_price,
          discountPercent: 0,
          discountAmount: 0,
        },
      ]
    })
  }

  const updateQuantity = (itemId: string, delta: number) => {
    setLineItems((prev) =>
      prev
        .map((li) => (li.id === itemId ? { ...li, quantity: Math.max(0, li.quantity + delta) } : li))
        .filter((li) => li.quantity > 0),
    )
  }

  const removeItem = (itemId: string) => {
    setLineItems((prev) => prev.filter((li) => li.id !== itemId))
  }

  const setItemDiscount = (itemId: string, percent: number) => {
    setLineItems((prev) =>
      prev.map((li) => (li.id === itemId ? { ...li, discountPercent: percent } : li)),
    )
  }

  const setOrderDiscount = (percent: number, amount: number) => {
    setOrderDiscountPercent(percent)
    setOrderDiscountAmount(amount)
  }

  const { total, subtotal, taxAmount } = calculateOrderTotals(
    lineItems, orderDiscountPercent, orderDiscountAmount,
  )

  const handlePaymentComplete = async (payment: PaymentInfo) => {
    if (isOnline) {
      // Online: submit directly to server
      try {
        await apiClient.post('/api/v2/pos/transactions', {
          line_items: lineItems.map((li) => ({
            product_id: li.product.id,
            product_name: li.product.name,
            quantity: li.quantity,
            unit_price: li.unitPrice,
            discount_percent: li.discountPercent,
            discount_amount: li.discountAmount,
          })),
          payment_method: payment.method,
          subtotal,
          tax_amount: taxAmount,
          discount_amount: orderDiscountPercent > 0
            ? subtotal * (orderDiscountPercent / 100)
            : orderDiscountAmount,
          tip_amount: 0,
          total,
          cash_tendered: payment.cashTendered,
          change_given: payment.changeGiven,
        })
      } catch {
        // If online submission fails, store offline
        await storeOffline(payment)
      }
    } else {
      await storeOffline(payment)
    }

    // Reset order
    setLineItems([])
    setOrderDiscountPercent(0)
    setOrderDiscountAmount(0)
    setShowPayment(false)
    refreshPendingCount()
  }

  const storeOffline = async (payment: PaymentInfo) => {
    const offlineTx: OfflineTransaction = {
      offlineId: generateId(),
      timestamp: new Date().toISOString(),
      userId: 'current-user',
      lineItems: lineItems.map((li) => ({
        productId: li.product.id,
        productName: li.product.name,
        quantity: li.quantity,
        unitPrice: li.unitPrice,
        discountPercent: li.discountPercent,
        discountAmount: li.discountAmount,
      })),
      paymentMethod: payment.method,
      subtotal,
      taxAmount,
      discountAmount: orderDiscountPercent > 0
        ? subtotal * (orderDiscountPercent / 100)
        : orderDiscountAmount,
      tipAmount: 0,
      total,
      cashTendered: payment.cashTendered,
      changeGiven: payment.changeGiven,
      syncStatus: 'pending',
    }
    await saveTransaction(offlineTx)
  }

  return (
    <div className="h-screen flex flex-col bg-gray-100">
      {/* Offline indicator banner */}
      {!isOnline && (
        <div
          className="bg-yellow-500 text-white text-center py-2 text-sm font-medium"
          role="alert"
          aria-label="Offline status"
        >
          ⚠ Offline — Transactions will be saved locally
          {pendingCount > 0 && ` (${pendingCount} pending)`}
        </div>
      )}

      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-4 py-2 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Point of Sale</h1>
        <div className="flex items-center gap-3">
          <button
            onClick={handleCameraScan}
            disabled={scanning}
            className="px-3 py-1.5 rounded-md bg-gray-100 hover:bg-gray-200 text-sm font-medium text-gray-700"
            aria-label="Scan barcode"
          >
            {scanning ? 'Scanning…' : '📷 Scan'}
          </button>
          <button
            onClick={() => setShowSyncStatus(true)}
            className="px-3 py-1.5 rounded-md bg-gray-100 hover:bg-gray-200 text-sm font-medium text-gray-700 relative"
            aria-label="Sync status"
          >
            🔄 Sync
            {pendingCount > 0 && (
              <span className="absolute -top-1 -right-1 bg-yellow-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
                {pendingCount}
              </span>
            )}
          </button>
        </div>
      </header>

      {/* Main content: product grid (left) + order panel (right) */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 border-r border-gray-200 bg-white">
          <ProductGrid onSelectProduct={addProduct} />
        </div>
        <div className="w-96 flex-shrink-0">
          <OrderPanel
            lineItems={lineItems}
            orderDiscountPercent={orderDiscountPercent}
            orderDiscountAmount={orderDiscountAmount}
            onUpdateQuantity={updateQuantity}
            onRemoveItem={removeItem}
            onSetItemDiscount={setItemDiscount}
            onSetOrderDiscount={setOrderDiscount}
            onCheckout={() => setShowPayment(true)}
          />
        </div>
      </div>

      {/* Payment modal */}
      {showPayment && (
        <PaymentPanel
          total={total}
          onComplete={handlePaymentComplete}
          onCancel={() => setShowPayment(false)}
        />
      )}

      {/* Sync status modal */}
      {showSyncStatus && (
        <SyncStatus onClose={() => setShowSyncStatus(false)} />
      )}
    </div>
  )
}
