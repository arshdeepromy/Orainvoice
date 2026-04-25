import { useState, useCallback } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { useApiList } from '@/hooks/useApiList'
import { MobileCard, MobileButton, MobileSpinner, MobileSearchBar } from '@/components/ui'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

interface KioskProduct {
  id: string
  name: string
  price: number
  sku: string | null
}

interface KioskCartItem {
  product: KioskProduct
  quantity: number
}

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatCurrency(n: number) {
  return `$${Number(n ?? 0).toFixed(2)}`
}

/* ------------------------------------------------------------------ */
/* Kiosk Screen                                                       */
/* ------------------------------------------------------------------ */

/**
 * Kiosk screen — kiosk-mode display for kiosk role users.
 * Hides TabNavigator, restricts navigation, optimises layout for tablet (768px+).
 *
 * Requirements: 40.1, 40.2, 40.3
 */
export default function KioskScreen() {
  const { user, logout } = useAuth()
  const { items: products, isLoading, isRefreshing, search, setSearch, refresh } =
    useApiList<KioskProduct>({ endpoint: '/api/v1/inventory', dataKey: 'items', pageSize: 100 })

  const [cart, setCart] = useState<KioskCartItem[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const total = cart.reduce((sum, item) => sum + (item.product.price ?? 0) * item.quantity, 0)

  const addToCart = useCallback((product: KioskProduct) => {
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

  const removeItem = useCallback((productId: string) => {
    setCart((prev) => prev.filter((item) => item.product.id !== productId))
  }, [])

  const handleCheckout = useCallback(async () => {
    if (cart.length === 0) return
    setIsProcessing(true)
    setSuccessMessage(null)
    try {
      const lineItems = cart.map((item) => ({
        description: item.product.name,
        quantity: item.quantity,
        unit_price: item.product.price,
        tax_rate: 0.15,
      }))
      const res = await apiClient.post<{ id?: string }>('/api/v1/invoices', {
        line_items: lineItems,
        status: 'sent',
      })
      const invoiceId = res.data?.id
      if (invoiceId) {
        await apiClient.post(`/api/v1/invoices/${invoiceId}/payments`, {
          amount: total,
          method: 'card',
        })
      }
      setCart([])
      setSuccessMessage('Transaction complete')
    } catch {
      setSuccessMessage(null)
    } finally {
      setIsProcessing(false)
    }
  }, [cart, total])

  if (isLoading && products.length === 0) {
    return (
      <div className="flex h-screen items-center justify-center">
        <MobileSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col md:flex-row">
      {/* Product grid — takes full width on mobile, left side on tablet */}
      <div className="flex flex-1 flex-col overflow-hidden md:w-2/3">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-900">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            Kiosk Mode
          </h1>
          <MobileButton variant="ghost" size="sm" onClick={logout}>
            Exit
          </MobileButton>
        </div>

        <div className="p-4">
          <MobileSearchBar value={search} onChange={setSearch} placeholder="Search products..." />
        </div>

        <PullRefresh onRefresh={refresh} isRefreshing={isRefreshing}>
          <div className="grid grid-cols-3 gap-3 p-4 md:grid-cols-4 lg:grid-cols-5">
            {products.map((product) => (
              <button
                key={product.id}
                type="button"
                onClick={() => addToCart(product)}
                className="flex min-h-[80px] flex-col items-center justify-center rounded-xl border border-gray-200 bg-white p-3 text-center shadow-sm transition-colors active:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:active:bg-gray-700 md:min-h-[100px]"
              >
                <span className="text-sm font-medium text-gray-900 dark:text-gray-100 line-clamp-2">
                  {product.name ?? 'Item'}
                </span>
                <span className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {formatCurrency(product.price)}
                </span>
              </button>
            ))}
          </div>
        </PullRefresh>
      </div>

      {/* Cart sidebar — bottom on mobile, right side on tablet */}
      <div className="border-t border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800 md:w-1/3 md:border-l md:border-t-0">
        <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
          Cart ({cart.length})
        </h2>

        {cart.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No items in cart</p>
        ) : (
          <div className="flex flex-col gap-2">
            {cart.map((item) => (
              <div
                key={item.product.id}
                className="flex items-center justify-between rounded-lg bg-white p-2 dark:bg-gray-700"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                    {item.product.name}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {item.quantity} × {formatCurrency(item.product.price)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {formatCurrency(item.product.price * item.quantity)}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeItem(item.product.id)}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-red-500 active:bg-red-50 dark:active:bg-red-900/30"
                    aria-label={`Remove ${item.product.name}`}
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {cart.length > 0 && (
          <div className="mt-4">
            <div className="flex items-center justify-between border-t border-gray-200 pt-3 dark:border-gray-600">
              <span className="text-lg font-bold text-gray-900 dark:text-gray-100">Total</span>
              <span className="text-xl font-bold text-gray-900 dark:text-gray-100">
                {formatCurrency(total)}
              </span>
            </div>
            <MobileButton
              variant="primary"
              fullWidth
              onClick={handleCheckout}
              isLoading={isProcessing}
              className="mt-3"
            >
              Checkout {formatCurrency(total)}
            </MobileButton>
          </div>
        )}

        {successMessage && (
          <div className="mt-3 rounded-lg bg-green-50 p-3 text-center text-sm font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300">
            {successMessage}
          </div>
        )}
      </div>
    </div>
  )
}
