import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import {
  Page,
  Searchbar,
  Card,
  Block,
  Preloader,
  Sheet,
  Button,
  Segmented,
  SegmentedButton,
} from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import { PullRefresh } from '@/components/gestures/PullRefresh'
import HapticButton from '@/components/konsta/HapticButton'
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

function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function calculateCartTotal(items: CartItem[]): number {
  return items.reduce((sum, item) => sum + (item.product.price ?? 0) * item.quantity, 0)
}

/* ------------------------------------------------------------------ */
/* Main Component                                                     */
/* ------------------------------------------------------------------ */

function POSContent() {
  const [search, setSearch] = useState('')
  const [products, setProducts] = useState<Product[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cart, setCart] = useState<CartItem[]>([])
  const [orderSheetOpen, setOrderSheetOpen] = useState(false)
  const [paymentMethod, setPaymentMethod] = useState<'cash' | 'card' | 'other'>('cash')
  const [isProcessing, setIsProcessing] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const total = useMemo(() => calculateCartTotal(cart), [cart])

  const fetchProducts = useCallback(
    async (isRefresh: boolean, signal: AbortSignal) => {
      if (isRefresh) setIsRefreshing(true)
      else setIsLoading(true)
      setError(null)

      try {
        const params: Record<string, string | number> = { offset: 0, limit: 100 }
        if (search.trim()) params.search = search.trim()

        const res = await apiClient.get<{ items?: Product[]; total?: number }>(
          '/api/v1/catalogue/items',
          { params, signal },
        )
        setProducts(res.data?.items ?? [])
      } catch (err: unknown) {
        if ((err as { name?: string })?.name !== 'CanceledError') {
          setError('Failed to load products')
        }
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [search],
  )

  useEffect(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetchProducts(false, controller.signal)
    return () => controller.abort()
  }, [fetchProducts])

  const handleRefresh = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    await fetchProducts(true, controller.signal)
  }, [fetchProducts])

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value),
    [],
  )
  const handleSearchClear = useCallback(() => setSearch(''), [])

  const addToCart = useCallback((product: Product) => {
    setCart((prev) => {
      const existing = prev.find((item) => item.product.id === product.id)
      if (existing) {
        return prev.map((item) =>
          item.product.id === product.id ? { ...item, quantity: item.quantity + 1 } : item,
        )
      }
      return [...prev, { product, quantity: 1 }]
    })
    setSuccessMessage(null)
  }, [])

  const incrementItem = useCallback((productId: string) => {
    setCart((prev) =>
      prev.map((item) =>
        item.product.id === productId ? { ...item, quantity: item.quantity + 1 } : item,
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
      setOrderSheetOpen(false)
      setSuccessMessage('Payment recorded successfully')
    } catch {
      setSuccessMessage(null)
    } finally {
      setIsProcessing(false)
    }
  }, [cart, total, paymentMethod])

  if (isLoading && products.length === 0) {
    return (
      <Page data-testid="pos-page">
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  return (
    <Page data-testid="pos-page">
      <PullRefresh onRefresh={handleRefresh} isRefreshing={isRefreshing}>
        <div className="flex flex-col pb-24">
          {/* Search */}
          <div className="px-4 pt-3">
            <Searchbar
              value={search}
              onChange={handleSearchChange}
              onClear={handleSearchClear}
              placeholder="Search products…"
              data-testid="pos-searchbar"
            />
          </div>

          {error && (
            <Block>
              <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
                {error}
              </div>
            </Block>
          )}

          {/* 2-column product grid */}
          <div className="grid grid-cols-2 gap-2 px-4 pt-3" data-testid="product-grid">
            {products.map((product) => (
              <Card
                key={product.id}
                className="cursor-pointer"
                onClick={() => addToCart(product)}
                data-testid={`product-tile-${product.id}`}
              >
                <div className="flex flex-col items-center justify-center p-2 text-center">
                  <span className="text-sm font-medium text-gray-900 dark:text-gray-100 line-clamp-2">
                    {product.name ?? 'Unnamed'}
                  </span>
                  <span className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {formatNZD(product.price)}
                  </span>
                </div>
              </Card>
            ))}
          </div>

          {products.length === 0 && !isLoading && (
            <Block className="text-center">
              <p className="text-sm text-gray-400 dark:text-gray-500">No products found</p>
            </Block>
          )}

          {/* Success message */}
          {successMessage && (
            <Block>
              <div className="rounded-lg bg-green-50 p-3 text-center text-sm font-medium text-green-700 dark:bg-green-900/30 dark:text-green-300">
                {successMessage}
              </div>
            </Block>
          )}
        </div>
      </PullRefresh>

      {/* Cart FAB-like button */}
      {cart.length > 0 && (
        <div
          className="fixed right-4 z-50"
          style={{ bottom: 'calc(4rem + env(safe-area-inset-bottom, 0px) + 16px)' }}
        >
          <Button
            large
            rounded
            className="k-color-primary shadow-lg"
            onClick={() => setOrderSheetOpen(true)}
            data-testid="cart-button"
          >
            Cart ({cart.length}) · {formatNZD(total)}
          </Button>
        </div>
      )}

      {/* Order Panel Bottom Sheet */}
      <Sheet
        opened={orderSheetOpen}
        onBackdropClick={() => setOrderSheetOpen(false)}
        data-testid="order-sheet"
      >
        <div className="max-h-[70vh] overflow-y-auto p-4">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              Order ({cart.length} items)
            </h2>
            <button type="button" onClick={() => setOrderSheetOpen(false)} className="text-sm text-blue-600 dark:text-blue-400">
              Close
            </button>
          </div>

          {/* Cart items */}
          {cart.map((item) => (
            <div key={item.product.id} className="flex items-center justify-between border-b border-gray-100 py-2 last:border-b-0 dark:border-gray-700">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{item.product.name}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">{formatNZD(item.product.price)} each</p>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => item.quantity <= 1 ? removeItem(item.product.id) : decrementItem(item.product.id)} className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" aria-label="Decrease">−</button>
                <span className="w-6 text-center text-sm font-medium text-gray-900 dark:text-gray-100">{item.quantity}</span>
                <button type="button" onClick={() => incrementItem(item.product.id)} className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" aria-label="Increase">+</button>
              </div>
              <span className="ml-3 w-20 text-right text-sm font-medium text-gray-900 dark:text-gray-100">
                {formatNZD(item.product.price * item.quantity)}
              </span>
            </div>
          ))}

          {/* Total */}
          <div className="mt-3 flex items-center justify-between border-t border-gray-200 pt-3 dark:border-gray-600">
            <span className="text-base font-semibold text-gray-900 dark:text-gray-100">Total</span>
            <span className="text-lg font-bold text-gray-900 dark:text-gray-100">{formatNZD(total)}</span>
          </div>

          {/* Payment method */}
          <div className="mt-4">
            <Segmented strong>
              {(['cash', 'card', 'other'] as const).map((method) => (
                <SegmentedButton
                  key={method}
                  active={paymentMethod === method}
                  onClick={() => setPaymentMethod(method)}
                >
                  {method.charAt(0).toUpperCase() + method.slice(1)}
                </SegmentedButton>
              ))}
            </Segmented>
          </div>

          {/* Pay button */}
          <div className="mt-4">
            <HapticButton
              large
              className="k-color-primary w-full"
              onClick={handlePay}
              hapticStyle="medium"
              data-testid="pay-button"
            >
              {isProcessing ? 'Processing…' : `Pay ${formatNZD(total)}`}
            </HapticButton>
          </div>
        </div>
      </Sheet>
    </Page>
  )
}

/**
 * POS screen — 2-column product grid, order panel bottom sheet.
 * ModuleGate `pos`.
 *
 * Requirements: 38.1, 38.2, 38.3, 38.4, 38.5, 55.1
 */
export default function POSScreen() {
  return (
    <ModuleGate moduleSlug="pos">
      <POSContent />
    </ModuleGate>
  )
}
