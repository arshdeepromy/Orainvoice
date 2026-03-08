/**
 * Full-screen kitchen display with large text, station filtering,
 * colour-coded time highlighting, WebSocket reconnection with
 * exponential backoff, and tick-off interface.
 *
 * Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import apiClient from '@/api/client'
import { useAuth } from '@/contexts/AuthContext'
import { useTerm } from '@/contexts/TerminologyContext'
import { useFlag } from '@/contexts/FeatureFlagContext'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export interface KitchenOrderItem {
  id: string
  org_id: string
  pos_transaction_id: string | null
  table_id: string | null
  item_name: string
  quantity: number
  modifications: string | null
  station: string
  status: string
  created_at: string
  prepared_at: string | null
}

/* ------------------------------------------------------------------ */
/*  Pure utility functions (exported for testing)                       */
/* ------------------------------------------------------------------ */

/**
 * Determine urgency level based on elapsed time and configurable threshold.
 * - normal: elapsed < threshold
 * - warning: threshold <= elapsed < 2 * threshold
 * - critical: elapsed >= 2 * threshold
 */
export function getUrgencyLevel(
  createdAt: string,
  thresholdMinutes: number = 15,
): 'normal' | 'warning' | 'critical' {
  const elapsed = (Date.now() - new Date(createdAt).getTime()) / 60_000
  if (elapsed >= 2 * thresholdMinutes) return 'critical'
  if (elapsed >= thresholdMinutes) return 'warning'
  return 'normal'
}

/**
 * Calculate WebSocket reconnection backoff delay.
 * Sequence: 1000, 2000, 4000, 8000, 16000, 30000, 30000, ...
 */
export function getBackoffDelay(attempt: number): number {
  return Math.min(Math.pow(2, attempt) * 1000, 30000)
}

/**
 * Filter orders by station. "all" returns all orders.
 */
export function filterByStation(
  orders: KitchenOrderItem[],
  station: string,
): KitchenOrderItem[] {
  if (station === 'all') return orders
  return orders.filter((o) => o.station === station)
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const URGENCY_STYLES: Record<string, string> = {
  normal: 'bg-white border-gray-300 text-gray-900',
  warning: 'bg-amber-100 border-amber-400 text-amber-900',
  critical: 'bg-red-100 border-red-500 text-red-900',
}

const DEFAULT_STATIONS = ['all', 'main', 'grill', 'fry', 'cold', 'bar']
const DEFAULT_THRESHOLD_MINUTES = 15

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function KitchenDisplay() {
  const { user } = useAuth()
  const itemLabel = useTerm('item', 'Item')
  const orderLabel = useTerm('order', 'Order')
  const kitchenEnabled = useFlag('kitchen_display')

  const [orders, setOrders] = useState<KitchenOrderItem[]>([])
  const [readyOrders, setReadyOrders] = useState<KitchenOrderItem[]>([])
  const [station, setStation] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [wsConnected, setWsConnected] = useState(true)
  const [thresholdMinutes] = useState(DEFAULT_THRESHOLD_MINUTES)

  const wsRef = useRef<WebSocket | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)

  // Force re-render every 30s to update urgency colours
  const [, setTick] = useState(0)

  /* ---------- Fetch orders from REST API ---------- */

  const fetchOrders = useCallback(async () => {
    try {
      const url =
        station === 'all'
          ? '/api/v2/kitchen/orders'
          : `/api/v2/kitchen/orders?station=${encodeURIComponent(station)}`
      const res = await apiClient.get(url)
      const allOrders: KitchenOrderItem[] = res.data.orders ?? res.data
      setOrders(allOrders.filter((o) => o.status !== 'ready'))
      setReadyOrders(allOrders.filter((o) => o.status === 'ready'))
      setError(null)
    } catch (err: any) {
      setError(err?.message ?? 'Failed to load orders')
    } finally {
      setLoading(false)
    }
  }, [station])

  useEffect(() => {
    fetchOrders()
  }, [fetchOrders])

  /* ---------- Urgency colour refresh timer ---------- */

  useEffect(() => {
    timerRef.current = setInterval(() => setTick((t) => t + 1), 30_000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [])

  /* ---------- Cleanup on unmount ---------- */

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  /* ---------- WebSocket with exponential backoff reconnection ---------- */

  const connectWebSocket = useCallback(() => {
    const orgId = user?.org_id ?? localStorage.getItem('org_id') ?? 'default'
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${protocol}://${window.location.host}/ws/kitchen/${orgId}/${station}`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      if (!isMountedRef.current) return
      setWsConnected(true)
      reconnectAttemptRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.event === 'order_created' && msg.order) {
          if (msg.order.status === 'ready') {
            setReadyOrders((prev) => [...prev, msg.order])
          } else {
            setOrders((prev) => [...prev, msg.order])
          }
        } else if (msg.event === 'order_prepared' && msg.order_id) {
          // Move from pending to ready
          setOrders((prev) => {
            const item = prev.find((o) => o.id === msg.order_id)
            if (item) {
              setReadyOrders((r) => [...r, { ...item, status: 'ready', prepared_at: new Date().toISOString() }])
            }
            return prev.filter((o) => o.id !== msg.order_id)
          })
        } else if (msg.event === 'order_updated' && msg.order) {
          if (msg.order.status === 'ready') {
            setOrders((prev) => prev.filter((o) => o.id !== msg.order.id))
            setReadyOrders((prev) => {
              const exists = prev.some((o) => o.id === msg.order.id)
              if (exists) return prev.map((o) => (o.id === msg.order.id ? msg.order : o))
              return [...prev, msg.order]
            })
          } else {
            setReadyOrders((prev) => prev.filter((o) => o.id !== msg.order.id))
            setOrders((prev) => {
              const exists = prev.some((o) => o.id === msg.order.id)
              if (exists) return prev.map((o) => (o.id === msg.order.id ? msg.order : o))
              return [...prev, msg.order]
            })
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => {
      if (!isMountedRef.current) return
      setWsConnected(false)
    }

    ws.onclose = () => {
      if (!isMountedRef.current) return
      setWsConnected(false)
      // Exponential backoff reconnection
      const delay = getBackoffDelay(reconnectAttemptRef.current)
      reconnectAttemptRef.current += 1
      reconnectTimerRef.current = setTimeout(() => {
        if (isMountedRef.current) {
          connectWebSocket()
        }
      }, delay)
    }

    return ws
  }, [station, user?.org_id])

  useEffect(() => {
    const ws = connectWebSocket()

    return () => {
      ws.close()
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
    }
  }, [connectWebSocket])

  /* ---------- Mark item as prepared (move to Ready column) ---------- */

  const markPrepared = useCallback(
    async (orderId: string) => {
      try {
        await apiClient.put(`/api/v2/kitchen/orders/${orderId}/status`, { status: 'ready' })
        setOrders((prev) => {
          const item = prev.find((o) => o.id === orderId)
          if (item) {
            setReadyOrders((r) => [...r, { ...item, status: 'ready', prepared_at: new Date().toISOString() }])
          }
          return prev.filter((o) => o.id !== orderId)
        })
      } catch {
        setError('Failed to mark item as prepared')
      }
    },
    [],
  )

  /* ---------- Full-screen toggle ---------- */

  const toggleFullScreen = useCallback(() => {
    setIsFullScreen((prev) => !prev)
  }, [])

  /* ---------- Elapsed time display ---------- */

  const formatElapsed = (createdAt: string): string => {
    const mins = Math.floor((Date.now() - new Date(createdAt).getTime()) / 60_000)
    if (mins < 1) return 'Just now'
    if (mins < 60) return `${mins}m`
    return `${Math.floor(mins / 60)}h ${mins % 60}m`
  }

  /* ---------- Full-screen styles ---------- */

  const containerClass = isFullScreen
    ? 'fixed inset-0 z-50 bg-gray-900 text-white p-4 overflow-auto'
    : 'min-h-screen bg-gray-900 text-white p-4'

  const bodyTextClass = isFullScreen ? 'text-lg' : 'text-base' // 18px+ in full-screen
  const headingTextClass = isFullScreen ? 'text-3xl' : 'text-2xl' // 24px+ in full-screen

  /* ---------- Render ---------- */

  if (!kitchenEnabled) {
    return (
      <div className="min-h-screen bg-gray-900 text-white flex items-center justify-center" data-testid="kitchen-display">
        <div className="text-center text-xl text-gray-400">Kitchen display is not enabled for this organisation.</div>
      </div>
    )
  }

  return (
    <div
      className={containerClass}
      data-testid="kitchen-display"
      style={isFullScreen ? { fontSize: '18px' } : undefined}
    >
      {/* Connection Lost banner */}
      {!wsConnected && (
        <div
          className="bg-red-700 text-white px-4 py-3 rounded mb-4 text-center font-bold text-xl animate-pulse"
          role="alert"
          data-testid="connection-lost-banner"
        >
          ⚠ Connection Lost — Reconnecting…
        </div>
      )}

      {/* Header bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h1 className={`${headingTextClass} font-extrabold`}>
          Kitchen Display
        </h1>

        <div className="flex items-center gap-3">
          {/* Full-screen toggle */}
          <button
            onClick={toggleFullScreen}
            data-testid="fullscreen-toggle"
            className="px-4 py-3 bg-gray-700 hover:bg-gray-600 text-white rounded-lg font-bold transition-colors"
            style={{ minWidth: '44px', minHeight: '44px' }}
            aria-label={isFullScreen ? 'Exit full-screen mode' : 'Enter full-screen mode'}
          >
            {isFullScreen ? '⊡ Exit' : '⊞ Full Screen'}
          </button>
        </div>
      </div>

      {/* Station filter tabs */}
      <div className="flex gap-2 mb-6 overflow-x-auto" role="tablist" aria-label="Station filter">
        {DEFAULT_STATIONS.map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={station === s}
            onClick={() => setStation(s)}
            className={`px-6 py-3 rounded-lg text-lg font-bold uppercase tracking-wide transition-colors ${
              station === s
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
            style={{ minWidth: '44px', minHeight: '44px' }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-800 text-white px-4 py-2 rounded mb-4" role="alert">
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="text-center text-2xl text-gray-400 mt-20">Loading orders…</div>
      )}

      {/* Main content: Pending + Ready columns */}
      {!loading && (
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Pending Orders Column */}
          <div className="flex-1">
            <h2 className={`${headingTextClass} font-bold mb-4 text-yellow-400`}>
              Pending {orderLabel}s
              <span className="ml-2 text-lg text-gray-400">({orders.length})</span>
            </h2>

            {orders.length === 0 && (
              <div className="text-center text-xl text-gray-500 mt-10" data-testid="empty-state">
                No pending orders
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {orders.map((order) => {
                const urgency = getUrgencyLevel(order.created_at, thresholdMinutes)
                return (
                  <div
                    key={order.id}
                    data-testid="kitchen-order-card"
                    className={`rounded-xl border-2 p-4 shadow-lg ${URGENCY_STYLES[urgency]}`}
                  >
                    <h3 className={`${headingTextClass} font-extrabold mb-1 leading-tight`}>
                      {order.item_name}
                    </h3>
                    <div className={`${bodyTextClass} font-bold mb-2`}>×{order.quantity}</div>
                    {order.modifications && (
                      <p className={`${bodyTextClass} italic mb-2 opacity-80`}>
                        {order.modifications}
                      </p>
                    )}
                    {order.table_id && (
                      <div className={`${bodyTextClass} mb-1`}>
                        Table: {order.table_id}
                      </div>
                    )}
                    <span className="inline-block bg-gray-800 text-white text-sm px-2 py-1 rounded mb-2 uppercase">
                      {order.station}
                    </span>
                    <div className="text-sm opacity-70 mb-3">
                      {formatElapsed(order.created_at)}
                    </div>
                    <button
                      data-testid="mark-prepared-btn"
                      onClick={() => markPrepared(order.id)}
                      className="w-full py-3 bg-green-600 hover:bg-green-700 text-white text-xl font-bold rounded-lg transition-colors"
                      style={{ minHeight: '44px' }}
                      aria-label={`Mark ${order.item_name} as prepared`}
                    >
                      ✓ Done
                    </button>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Ready Orders Column */}
          <div className="lg:w-80 xl:w-96 flex-shrink-0">
            <h2 className={`${headingTextClass} font-bold mb-4 text-green-400`}>
              Ready {itemLabel}s
              <span className="ml-2 text-lg text-gray-400">({readyOrders.length})</span>
            </h2>

            {readyOrders.length === 0 && (
              <div className="text-center text-lg text-gray-500 mt-10">
                No ready items
              </div>
            )}

            <div className="flex flex-col gap-3">
              {readyOrders.map((order) => (
                <div
                  key={order.id}
                  data-testid="kitchen-ready-card"
                  className="rounded-xl border-2 border-green-500 bg-green-900 bg-opacity-30 p-4 shadow-lg text-green-100"
                >
                  <h3 className={`${headingTextClass} font-extrabold mb-1 leading-tight`}>
                    {order.item_name}
                  </h3>
                  <div className={`${bodyTextClass} font-bold mb-1`}>×{order.quantity}</div>
                  {order.table_id && (
                    <div className={`${bodyTextClass} mb-1`}>
                      Table: {order.table_id}
                    </div>
                  )}
                  <span className="inline-block bg-green-700 text-white text-sm px-2 py-1 rounded uppercase">
                    {order.station}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
