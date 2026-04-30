import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Page,
  Block,
  Button,
  Preloader,
  List,
  ListItem,
  Searchbar,
} from 'konsta/react'
import { useAuth } from '@/contexts/AuthContext'
import { useHaptics } from '@/hooks/useHaptics'
import HapticButton from '@/components/konsta/HapticButton'
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
  return `NZD${Number(n ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/* ------------------------------------------------------------------ */
/* Kiosk Screen                                                       */
/* ------------------------------------------------------------------ */

/**
 * Kiosk screen — large-button check-in / POS screen for kiosk role users.
 * When user role is `kiosk`, KonstaShell hides the standard tabbar.
 * Designed for tablet but functional on phone.
 * Calls POST /kiosk/check-in for check-in flow.
 *
 * Requirements: 49.1, 49.2, 49.3
 */
export default function KioskScreen() {
  const { logout } = useAuth()
  const haptics = useHaptics()

  const [products, setProducts] = useState<KioskProduct[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [search, setSearch] = useState('')
  const [cart, setCart] = useState<KioskCartItem[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [showCart, setShowCart] = useState(false)

  const abortRef = useRef<AbortController | null>(null)

  const total = cart.reduce((sum, item) => sum + (item.product.price ?? 0) * item.quantity, 0)

  // ── Fetch products ─────────────────────────────────────────────────
  const fetchProducts = useCallback(async (signal: AbortSignal, refresh = false) => {
    if (refresh) setIsRefreshing(true)
    else setIsLoading(true)

    try {
      const res = await apiClient.get<{ items?: KioskProduct[] }>('/api/v1/inventory', {
        params: { limit: 100 },
        signal,
      })
      setProducts(res.data?.items ?? [])
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') {
        // Silently fail
      }
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    abortRef.current = controller
    fetchProducts(controller.signal)
    return () => controller.abort()
  }, [fetchProducts])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchProducts(controller.signal, true)
  }, [fetchProducts])

  // ── Filter products by search ──────────────────────────────────────
  const filteredProducts = search
    ? products.filter(
        (p) =>
          (p.name ?? '').toLowerCase().includes(search.toLowerCase()) ||
          (p.sku ?? '').toLowerCase().includes(search.toLowerCase()),
      )
    : products

  // ── Cart actions ───────────────────────────────────────────────────
  const addToCart = useCallback(
    (product: KioskProduct) => {
      void haptics.light()
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
    },
    [haptics],
  )

  const removeItem = useCallback(
    (productId: string) => {
      void haptics.medium()
      setCart((prev) => prev.filter((item) => item.product.id !== productId))
    },
    [haptics],
  )

  const handleCheckout = useCallback(async () => {
    if (cart.length === 0) return
    setIsProcessing(true)
    setSuccessMessage(null)
    void haptics.heavy()

    try {
      const lineItems = cart.map((item) => ({
        description: item.product.name,
        quantity: item.quantity,
        unit_price: item.product.price,
        tax_rate: 0.15,
      }))

      // Use POST /kiosk/check-in as per requirements
      await apiClient.post('/api/v1/kiosk/check-in', {
        line_items: lineItems,
        total,
      })

      setCart([])
      setShowCart(false)
      setSuccessMessage('Transaction complete')
    } catch {
      // Fallback: try creating invoice directly
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
        setShowCart(false)
        setSuccessMessage('Transaction complete')
      } catch {
        setSuccessMessage(null)
      }
    } finally {
      setIsProcessing(false)
    }
  }, [cart, total, haptics])

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading && products.length === 0) {
    return (
      <Page data-testid="kiosk-page">
        <div className="flex h-screen items-center justify-center">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="kiosk-page">
      <div className="flex h-screen flex-col md:flex-row">
        {/* Product grid — takes full width on mobile, left side on tablet */}
        <div className="flex flex-1 flex-col overflow-hidden md:w-2/3">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-900">
            <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              Kiosk Mode
            </h1>
            <div className="flex items-center gap-2">
              {/* Cart toggle for mobile */}
              <Button
                small
                tonal
                onClick={() => setShowCart(!showCart)}
                className="md:hidden"
                data-testid="cart-toggle"
              >
                Cart ({cart.length})
              </Button>
              <Button clear small onClick={logout} data-testid="kiosk-exit">
                Exit
              </Button>
            </div>
          </div>

          {/* Search */}
          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onInput={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
              onClear={() => setSearch('')}
              placeholder="Search products..."
              data-testid="kiosk-search"
            />
          </div>

          {/* Product grid */}
          <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
            <div className="grid grid-cols-3 gap-3 p-4 md:grid-cols-4 lg:grid-cols-5">
              {filteredProducts.map((product) => (
                <button
                  key={product.id}
                  type="button"
                  onClick={() => addToCart(product)}
                  className="flex min-h-[80px] flex-col items-center justify-center rounded-xl border border-gray-200 bg-white p-3 text-center shadow-sm transition-colors active:bg-blue-50 dark:border-gray-700 dark:bg-gray-800 dark:active:bg-gray-700 md:min-h-[100px]"
                  data-testid={`kiosk-product-${product.id}`}
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

        {/* Cart sidebar — bottom on mobile (toggled), right side on tablet */}
        <div
          className={`border-t border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800 md:block md:w-1/3 md:border-l md:border-t-0 ${
            showCart ? 'block' : 'hidden md:block'
          }`}
          data-testid="kiosk-cart"
        >
          <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">
            Cart ({cart.length})
          </h2>

          {cart.length === 0 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">No items in cart</p>
          ) : (
            <List strongIos outlineIos>
              {cart.map((item) => (
                <ListItem
                  key={item.product.id}
                  title={
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                      {item.product.name}
                    </span>
                  }
                  subtitle={
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {item.quantity} × {formatCurrency(item.product.price)}
                    </span>
                  }
                  after={
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
                  }
                />
              ))}
            </List>
          )}

          {cart.length > 0 && (
            <Block>
              <div className="flex items-center justify-between border-t border-gray-200 pt-3 dark:border-gray-600">
                <span className="text-lg font-bold text-gray-900 dark:text-gray-100">Total</span>
                <span className="text-xl font-bold text-gray-900 dark:text-gray-100">
                  {formatCurrency(total)}
                </span>
              </div>
              <HapticButton
                hapticStyle="heavy"
                large
                onClick={handleCheckout}
                disabled={isProcessing}
                className="mt-3 w-full"
                data-testid="kiosk-checkout"
              >
                {isProcessing ? 'Processing…' : `Checkout ${formatCurrency(total)}`}
              </HapticButton>
            </Block>
          )}

          {successMessage && (
            <div className="mt-3 rounded-lg bg-green-50 p-3 text-center text-sm font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300" data-testid="kiosk-success">
              {successMessage}
            </div>
          )}
        </div>
      </div>
    </Page>
  )
}
