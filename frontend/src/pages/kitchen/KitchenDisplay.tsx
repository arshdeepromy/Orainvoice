/**
 * Full-screen kitchen display with large text, station filtering,
 * colour-coded time highlighting, and tick-off interface.
 *
 * Validates: Requirement — Kitchen Display Module — Tasks 32.10, 32.11
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import apiClient from '@/api/client'

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
/*  Urgency helpers                                                    */
/* ------------------------------------------------------------------ */

export function getUrgencyLevel(createdAt: string): 'normal' | 'warning' | 'critical' {
  const elapsed = (Date.now() - new Date(createdAt).getTime()) / 60_000
  if (elapsed > 30) return 'critical'
  if (elapsed > 15) return 'warning'
  return 'normal'
}

const URGENCY_STYLES: Record<string, string> = {
  normal: 'bg-white border-gray-300 text-gray-900',
  warning: 'bg-amber-100 border-amber-400 text-amber-900',
  critical: 'bg-red-100 border-red-500 text-red-900',
}

const STATIONS = ['all', 'main', 'grill', 'fry', 'cold', 'bar']

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function KitchenDisplay() {
  const [orders, setOrders] = useState<KitchenOrderItem[]>([])
  const [station, setStation] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // Force re-render every 30s to update urgency colours
  const [, setTick] = useState(0)

  /* ---------- Fetch orders from REST API ---------- */

  const fetchOrders = useCallback(async () => {
    try {
      const url =
        station === 'all'
          ? '/api/v2/kitchen/orders'
          : `/api/v2/kitchen/stations/${station}/orders`
      const res = await apiClient.get(url)
      setOrders(res.data.orders ?? res.data)
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

  /* ---------- WebSocket for real-time updates ---------- */

  useEffect(() => {
    const orgId = localStorage.getItem('org_id') ?? 'default'
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${protocol}://${window.location.host}/ws/kitchen/${orgId}/${station}`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.event === 'order_created' && msg.order) {
          setOrders((prev) => [...prev, msg.order])
        } else if (msg.event === 'order_prepared' && msg.order_id) {
          setOrders((prev) => prev.filter((o) => o.id !== msg.order_id))
        } else if (msg.event === 'order_updated' && msg.order) {
          setOrders((prev) =>
            prev.map((o) => (o.id === msg.order.id ? msg.order : o)),
          )
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => setError('WebSocket connection error')
    ws.onclose = () => {
      // Auto-reconnect after 3s
      setTimeout(() => fetchOrders(), 3000)
    }

    return () => {
      ws.close()
    }
  }, [station, fetchOrders])

  /* ---------- Mark item as prepared ---------- */

  const markPrepared = useCallback(
    async (orderId: string) => {
      try {
        await apiClient.put(`/api/v2/kitchen/orders/${orderId}/prepared`)
        setOrders((prev) => prev.filter((o) => o.id !== orderId))
      } catch {
        setError('Failed to mark item as prepared')
      }
    },
    [],
  )

  /* ---------- Elapsed time display ---------- */

  const formatElapsed = (createdAt: string): string => {
    const mins = Math.floor((Date.now() - new Date(createdAt).getTime()) / 60_000)
    if (mins < 1) return 'Just now'
    if (mins < 60) return `${mins}m`
    return `${Math.floor(mins / 60)}h ${mins % 60}m`
  }

  /* ---------- Render ---------- */

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4" data-testid="kitchen-display">
      {/* Station filter tabs */}
      <div className="flex gap-2 mb-6 overflow-x-auto" role="tablist" aria-label="Station filter">
        {STATIONS.map((s) => (
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

      {/* Empty state */}
      {!loading && orders.length === 0 && (
        <div className="text-center text-3xl text-gray-500 mt-20" data-testid="empty-state">
          No pending orders
        </div>
      )}

      {/* Order grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {orders.map((order) => {
          const urgency = getUrgencyLevel(order.created_at)
          return (
            <div
              key={order.id}
              data-testid="kitchen-order-card"
              className={`rounded-xl border-2 p-4 shadow-lg ${URGENCY_STYLES[urgency]}`}
            >
              {/* Item name — large text */}
              <h2 className="text-2xl font-extrabold mb-1 leading-tight">
                {order.item_name}
              </h2>

              {/* Quantity */}
              <div className="text-xl font-bold mb-2">×{order.quantity}</div>

              {/* Modifications */}
              {order.modifications && (
                <p className="text-base italic mb-2 opacity-80">
                  {order.modifications}
                </p>
              )}

              {/* Station badge */}
              <span className="inline-block bg-gray-800 text-white text-sm px-2 py-1 rounded mb-2 uppercase">
                {order.station}
              </span>

              {/* Elapsed time */}
              <div className="text-sm opacity-70 mb-3">
                {formatElapsed(order.created_at)}
              </div>

              {/* Tick-off button */}
              <button
                data-testid="mark-prepared-btn"
                onClick={() => markPrepared(order.id)}
                className="w-full py-3 bg-green-600 hover:bg-green-700 text-white text-xl font-bold rounded-lg transition-colors"
                aria-label={`Mark ${order.item_name} as prepared`}
              >
                ✓ Done
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
