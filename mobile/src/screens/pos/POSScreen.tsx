import { useState, useCallback, useMemo } from 'react'
import { MobileButton, MobileCard, MobileSearchBar, MobileSpinner } from '@/components/ui'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import { useApiList } from '@/hooks/useApiList'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface Product {
  id: string
  name: string
  sku: string | null
  price: number
  stock_level: number | null
  image_url: string | null
}

interface CartItem {
  product: Product
  quantity: number
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(amount: number): string {
  return `$${Number(amount ?? 0).toFixed(2)}`
}

/* ------------------------------------------------------------------ */
/* Cart logic (pure for testability)                                  */
/* ------------------------------------------------------------------ */

export function calculateCartTotal(items: CartItem[]): number {
  return items.reduce((sum, item) => sum + (item.product.price ?? 0) * item.quantity, 0)
}

/* ------------------------------------------------------------------ */
/* Product Grid Item                                                  */
/* ------------------------------------------------------------------ */

function ProductTile({
  product,
  onAdd,
}: {
  product: Product
  onAdd: (product: Product) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onAdd(product)}
      className="flex min-h-[80px] flex-col items-center justify-center rounded-lg border border-gray-200 bg-white p-3 text-center shadow-sm transition-colors active:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:active:bg-gray-700"
    >
      <span className="text-sm font-medium text-gray-900 dark:text-gray-100 line-clamp-2">
        {product.name ?? 'Unnamed'}
      </span>
      <span className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        {formatCurrency(product.price)}
      </span>
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Cart Item Row                                                      */
/* ------------------------------------------------------------------ */

function CartItemRow({
  item,
  onIncrement,
  onDecrement,
  onRemove,
}: {
  item: CartItem
  onIncrement: () => void
  onDecrement: () => void
  onRemove: () => void
}) {
  return (
    <div className="flex items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
          {item.product.name}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {formatCurrency(item.product.price)} each
        </p>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={item.quantity <= 1 ? onRemove : onDecrement}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-100 text-gray-600 active:bg-gray-200 dark:bg-gray-700 dark:text-gray-300"
          aria-label="Decrease quantity"
        >
          −
        </button>
        <span className="w-6 text-center text-sm font-medium text-gray-900 dark:text-gray-100">
          {item.quantity}
        </span>
        <button
          type="button"
          onClick={onIncrement}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-blue-700 active:bg-blue-200 dark:bg-blue-900/30 dark:text-blue-300"
          aria-label="Increase quantity"
        >
          +
        </button>
      </div>
      <span className="ml-3 w-16 text-right text-sm font-medium text-gray-900 dark:text-gray-100">
        {formatCurrency(item.product.price * item.quantity)}
      </span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* POS Screen                                                         */
/* ------------------------------------------------------------------ */

function POSScreenContent() {
  const {
    items: products,
    isLoading,
    isRefreshing,
    search,
    setSearch,
    refresh,
  } = useApiList<Product>({
    endpoint: '/api/v1/inventory',
    dataKey: 'items',
    pageSize: 100,
  })

  const [cart, setCart] = useState<CartItem[]>([])
  const [paymentMethod, setPaymentMethod] = useState<'cash' | 'card' | 'other'>('cash')
  const [isProcessing, setIsProcessing] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const total = useMemo(() => calculateCartTotal(cart), [cart])

  const addToCart = useCallback((product: Product) => {
    setCart((prev) => {
      const existing = prev.find((item) => item.product.id === product.id)
      if (existing) {
        return prev.map((item) =>
          item.product.id === product.id
            ? { ...item, quantity: item.quantity + 1 }
            : item,
        )
      }
      return [...prev, { product, quantity: 1 }]
    })
    setSuccessMessage(null)
  }, [])

  const incrementItem = useCallback((productId: string) => {
    setCart((prev) =>
      prev.map((item) =>
        item.product.id === productId
          ? { ...item, quantity: item.quantity + 1 }
          : item,
      ),
    )
  }, [])

  const decrementItem = useCallback((productId: string) => {
    setCart((prev) =>
      prev.map((item) =>
        item.product.id === productId && item.quantity > 1
          ? { ...item, quantity: item.quantity - 1 }
          : item,
      ),
    )
  }, [])

  const removeItem = useCallback((productId: string) => {
    setCart((prev) => prev.filter((item) => item.product.id !== productId))
  }, [])

  const handlePay = useCallback(async () => {
    if (cart.length === 0) return
    setIsProcessing(true)
    setSuccessMessage(null)
    try {
      // Create invoice + record payment in one flow
      const lineItems = cart.map((item) => ({
        description: item.product.name,
        quantity: item.quantity,
        unit_price: item.product.price,
        tax_rate: 0.15,
        inventory_item_id: item.product.id,
      }))

      const invoiceRes = await apiClient.post<{ id?: string }>('/api/v1/invoices', {
        line_items: lineItems,
        status: 'sent',
      })

      const invoiceId = invoiceRes.data?.id
      if (invoiceId) {
        await apiClient.post(`/api/v1/invoices/${invoiceId}/payments`, {
          amount: total,
          method: paymentMethod,
        })
      }

      setCart([])
      setSuccessMessage('Payment recorded successfully')
    } catch {
      setSuccessMessage(null)
    } finally {
      setIsProcessing(false)
    }
  }, [cart, total, paymentMethod])

  if (isLoading && products.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <MobileSpinner size="md" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Point of Sale
      </h1>

      {/* Search */}
      <MobileSearchBar
        value={search}
        onChange={setSearch}
        placeholder="Search products..."
      />

      {/* Product Grid */}
      <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
        <div className="grid grid-cols-3 gap-2">
          {products.map((product) => (
            <ProductTile key={product.id} product={product} onAdd={addToCart} />
          ))}
        </div>
        {products.length === 0 && !isLoading && (
          <p className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
            No products found
          </p>
        )}
      </PullRefresh>

      {/* Cart */}
      {cart.length > 0 && (
        <MobileCard>
          <h2 className="mb-2 text-base font-semibold text-gray-900 dark:text-gray-100">
            Cart ({cart.length} items)
          </h2>
          {cart.map((item) => (
            <CartItemRow
              key={item.product.id}
              item={item}
              onIncrement={() => incrementItem(item.product.id)}
              onDecrement={() => decrementItem(item.product.id)}
              onRemove={() => removeItem(item.product.id)}
            />
          ))}
          <div className="mt-3 flex items-center justify-between border-t border-gray-200 pt-3 dark:border-gray-600">
            <span className="text-base font-semibold text-gray-900 dark:text-gray-100">
              Total
            </span>
            <span className="text-lg font-bold text-gray-900 dark:text-gray-100">
              {formatCurrency(total)}
            </span>
          </div>

          {/* Payment method */}
          <div className="mt-3 flex gap-2">
            {(['cash', 'card', 'other'] as const).map((method) => (
              <button
                key={method}
                type="button"
                onClick={() => setPaymentMethod(method)}
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium capitalize transition-colors ${
                  paymentMethod === method
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300'
                }`}
              >
                {method}
              </button>
            ))}
          </div>

          {/* Pay button */}
          <MobileButton
            variant="primary"
            fullWidth
            onClick={handlePay}
            isLoading={isProcessing}
            className="mt-3"
          >
            Pay {formatCurrency(total)}
          </MobileButton>
        </MobileCard>
      )}

      {/* Success message */}
      {successMessage && (
        <div className="rounded-lg bg-green-50 p-3 text-center text-sm font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300">
          {successMessage}
        </div>
      )}
    </div>
  )
}

/**
 * POS Screen — product grid, cart, total calculation, Pay button.
 * Wrapped in ModuleGate for pos module.
 *
 * Requirements: 31.1, 31.2, 31.3, 31.4, 31.5
 */
export default function POSScreen() {
  return (
    <ModuleGate moduleSlug="pos">
      <POSScreenContent />
    </ModuleGate>
  )
}
