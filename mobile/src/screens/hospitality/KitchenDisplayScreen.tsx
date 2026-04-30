import { useState, useCallback, useRef, useEffect } from 'react'
import { Page, Card, Block, Preloader } from 'konsta/react'
import { ModuleGate } from '@/components/common/ModuleGate'
import HapticButton from '@/components/konsta/HapticButton'
import apiClient from '@/api/client'

interface KitchenOrder {
  id: string
  order_number: string
  table_number: number | null
  items: KitchenOrderItem[]
  status: string
  created_at: string
  notes: string | null
}

interface KitchenOrderItem {
  id: string
  name: string
  quantity: number
  modifications: string | null
}

function formatTime(dateStr: string): string {
  if (!dateStr) return ''
  try { return new Date(dateStr).toLocaleTimeString('en-NZ', { hour: '2-digit', minute: '2-digit' }) }
  catch { return dateStr }
}

function statusColor(status: string): string {
  switch (status) {
    case 'ready': return 'border-green-500 bg-green-50 dark:bg-green-900/20'
    case 'preparing': return 'border-amber-500 bg-amber-50 dark:bg-amber-900/20'
    default: return 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
  }
}

function KitchenContent() {
  const [orders, setOrders] = useState<KitchenOrder[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const refreshIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchOrders = useCallback(async (signal: AbortSignal) => {
    try {
      const res = await apiClient.get<{ items?: KitchenOrder[]; total?: number }>('/api/v1/kitchen/orders', { signal })
      setOrders(res.data?.items ?? [])
      setError(null)
    } catch (err: unknown) {
      if ((err as { name?: string })?.name !== 'CanceledError') setError('Failed to load orders')
    } finally { setIsLoading(false) }
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    const c = new AbortController(); abortRef.current = c
    fetchOrders(c.signal)

    // Auto-refresh every 5 seconds
    refreshIntervalRef.current = setInterval(() => {
      const controller = new AbortController()
      abortRef.current = controller
      fetchOrders(controller.signal)
    }, 5000)

    return () => {
      c.abort()
      if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current)
    }
  }, [fetchOrders])

  const handleMarkReady = useCallback(async (orderId: string) => {
    try {
      await apiClient.put(`/api/v1/kitchen/orders/${orderId}`, { status: 'ready' })
      setOrders((prev) => prev.map((o) => o.id === orderId ? { ...o, status: 'ready' } : o))
    } catch {
      // Error handled silently
    }
  }, [])

  if (isLoading) {
    return (<Page data-testid="kitchen-page"><div className="flex flex-1 items-center justify-center p-8"><Preloader /></div></Page>)
  }

  return (
    <Page data-testid="kitchen-page">
      <div className="flex flex-col pb-24">
        {error && (
          <Block><div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</div></Block>
        )}

        {orders.length === 0 ? (
          <Block className="text-center"><p className="text-sm text-gray-400 dark:text-gray-500">No active orders</p></Block>
        ) : (
          <div className="flex flex-col gap-3 px-4 pt-4">
            {orders.map((order) => (
              <Card key={order.id} className={`border-l-4 ${statusColor(order.status)}`} data-testid={`kitchen-order-${order.id}`}>
                <div className="p-4">
                  {/* Order header */}
                  <div className="mb-2 flex items-center justify-between">
                    <div>
                      <span className="text-lg font-bold text-gray-900 dark:text-gray-100">
                        #{order.order_number}
                      </span>
                      {order.table_number && (
                        <span className="ml-2 text-sm text-gray-500 dark:text-gray-400">
                          Table {order.table_number}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {formatTime(order.created_at)}
                    </span>
                  </div>

                  {/* Items */}
                  <div className="flex flex-col gap-1">
                    {(order.items ?? []).map((item) => (
                      <div key={item.id} className="flex items-start justify-between">
                        <div>
                          <span className="text-base font-medium text-gray-900 dark:text-gray-100">
                            {item.quantity}× {item.name}
                          </span>
                          {item.modifications && (
                            <p className="text-xs text-amber-600 dark:text-amber-400">{item.modifications}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Notes */}
                  {order.notes && (
                    <p className="mt-2 text-xs italic text-gray-500 dark:text-gray-400">{order.notes}</p>
                  )}

                  {/* Mark Ready button */}
                  {order.status !== 'ready' && (
                    <div className="mt-3">
                      <HapticButton
                        large
                        className="k-color-primary w-full"
                        onClick={() => handleMarkReady(order.id)}
                        hapticStyle="medium"
                        data-testid={`mark-ready-${order.id}`}
                      >
                        Mark Ready
                      </HapticButton>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </Page>
  )
}

/**
 * Kitchen Display screen — large order cards, tap-to-mark-ready, auto-refresh every 5s.
 * Gate by `kitchen_display` module + `food-hospitality` trade.
 * Requirements: 42.2, 42.3, 55.1, 55.5
 */
export default function KitchenDisplayScreen() {
  return (
    <ModuleGate moduleSlug="kitchen_display" tradeFamily="food-hospitality">
      <KitchenContent />
    </ModuleGate>
  )
}
