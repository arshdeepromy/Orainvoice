/**
 * Floor plan editor with drag-and-drop table positioning,
 * real-time status colours, and tap-to-open-order.
 *
 * Validates: Requirement — Table Module — Task 31.9
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import apiClient from '@/api/client'

interface TableItem {
  id: string
  table_number: string
  seat_count: number
  position_x: number
  position_y: number
  width: number
  height: number
  status: string
  merged_with_id: string | null
  floor_plan_id: string | null
}

interface FloorPlanData {
  id: string
  org_id: string
  name: string
  width: number
  height: number
  is_active: boolean
}

interface ReservationItem {
  id: string
  table_id: string
  customer_name: string
  party_size: number
  reservation_date: string
  reservation_time: string
  duration_minutes: number
  status: string
}

interface FloorPlanState {
  floor_plan: FloorPlanData
  tables: TableItem[]
  reservations: ReservationItem[]
}

const STATUS_COLOURS: Record<string, string> = {
  available: 'bg-green-200 border-green-500 text-green-900',
  occupied: 'bg-red-200 border-red-500 text-red-900',
  needs_cleaning: 'bg-yellow-200 border-yellow-500 text-yellow-900',
  reserved: 'bg-blue-200 border-blue-500 text-blue-900',
}

const STATUS_LABELS: Record<string, string> = {
  available: 'Available',
  occupied: 'Occupied',
  needs_cleaning: 'Needs Cleaning',
  reserved: 'Reserved',
}

interface FloorPlanProps {
  floorPlanId?: string
  onTableTap?: (tableId: string) => void
}

export default function FloorPlan({ floorPlanId, onTableTap }: FloorPlanProps) {
  const [state, setState] = useState<FloorPlanState | null>(null)
  const [floorPlans, setFloorPlans] = useState<FloorPlanData[]>([])
  const [selectedPlanId, setSelectedPlanId] = useState(floorPlanId || '')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 })
  const canvasRef = useRef<HTMLDivElement>(null)
  const [editMode, setEditMode] = useState(false)

  const fetchFloorPlans = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/tables/floor-plans')
      setFloorPlans(res.data.floor_plans)
      if (!selectedPlanId && res.data.floor_plans.length > 0) {
        setSelectedPlanId(res.data.floor_plans[0].id)
      }
    } catch {
      setError('Failed to load floor plans.')
    }
  }, [selectedPlanId])

  const fetchState = useCallback(async () => {
    if (!selectedPlanId) return
    setLoading(true)
    setError('')
    try {
      const res = await apiClient.get(`/api/v2/tables/floor-plans/${selectedPlanId}/state`)
      setState(res.data)
    } catch {
      setError('Failed to load floor plan.')
    } finally {
      setLoading(false)
    }
  }, [selectedPlanId])

  useEffect(() => { fetchFloorPlans() }, [fetchFloorPlans])
  useEffect(() => { fetchState() }, [fetchState])

  const handleStatusChange = async (tableId: string, newStatus: string) => {
    try {
      await apiClient.put(`/api/v2/tables/tables/${tableId}/status`, { status: newStatus })
      fetchState()
    } catch {
      setError('Failed to update table status.')
    }
  }

  const handleTableTap = (tableId: string) => {
    if (editMode) return
    if (onTableTap) {
      onTableTap(tableId)
    }
  }

  const handleDragStart = (e: React.MouseEvent, tableId: string) => {
    if (!editMode) return
    const table = state?.tables.find((t) => t.id === tableId)
    if (!table || !canvasRef.current) return
    const rect = canvasRef.current.getBoundingClientRect()
    setDraggingId(tableId)
    setDragOffset({
      x: e.clientX - rect.left - table.position_x,
      y: e.clientY - rect.top - table.position_y,
    })
  }

  const handleDragMove = (e: React.MouseEvent) => {
    if (!draggingId || !canvasRef.current || !state) return
    const rect = canvasRef.current.getBoundingClientRect()
    const newX = Math.max(0, e.clientX - rect.left - dragOffset.x)
    const newY = Math.max(0, e.clientY - rect.top - dragOffset.y)
    setState({
      ...state,
      tables: state.tables.map((t) =>
        t.id === draggingId ? { ...t, position_x: newX, position_y: newY } : t,
      ),
    })
  }

  const handleDragEnd = async () => {
    if (!draggingId || !state) return
    const table = state.tables.find((t) => t.id === draggingId)
    if (table) {
      try {
        await apiClient.put(`/api/v2/tables/tables/${table.id}`, {
          position_x: table.position_x,
          position_y: table.position_y,
        })
      } catch {
        setError('Failed to save table position.')
      }
    }
    setDraggingId(null)
  }

  const getReservationsForTable = (tableId: string) =>
    state?.reservations.filter((r) => r.table_id === tableId) ?? []

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Floor Plan</h1>
        <div className="flex items-center gap-3">
          {floorPlans.length > 1 && (
            <select
              aria-label="Select floor plan"
              value={selectedPlanId}
              onChange={(e) => setSelectedPlanId(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              {floorPlans.map((fp) => (
                <option key={fp.id} value={fp.id}>{fp.name}</option>
              ))}
            </select>
          )}
          <button
            onClick={() => setEditMode(!editMode)}
            className={`rounded-md px-4 py-2 text-sm font-medium ${
              editMode
                ? 'bg-blue-600 text-white'
                : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
            aria-pressed={editMode}
          >
            {editMode ? 'Done Editing' : 'Edit Layout'}
          </button>
        </div>
      </div>

      {/* Status legend */}
      <div className="flex gap-4 mb-4" role="list" aria-label="Status legend">
        {Object.entries(STATUS_COLOURS).map(([status, classes]) => (
          <div key={status} className="flex items-center gap-1.5 text-xs" role="listitem">
            <span className={`inline-block h-3 w-3 rounded border ${classes}`} />
            <span>{STATUS_LABELS[status]}</span>
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="py-12 text-center text-sm text-gray-500" role="status" aria-label="Loading floor plan">
          Loading floor plan…
        </div>
      )}

      {!loading && state && (
        <div
          ref={canvasRef}
          className="relative border-2 border-gray-300 rounded-lg bg-gray-50 overflow-hidden"
          style={{
            width: `${state.floor_plan.width}px`,
            height: `${state.floor_plan.height}px`,
            maxWidth: '100%',
          }}
          onMouseMove={handleDragMove}
          onMouseUp={handleDragEnd}
          onMouseLeave={handleDragEnd}
          role="application"
          aria-label="Floor plan canvas"
        >
          {state.tables.map((table) => {
            const colourClass = STATUS_COLOURS[table.status] ?? STATUS_COLOURS.available
            const reservations = getReservationsForTable(table.id)
            const isMerged = table.merged_with_id !== null

            return (
              <div
                key={table.id}
                role="button"
                aria-label={`Table ${table.table_number} - ${STATUS_LABELS[table.status] ?? table.status}${
                  reservations.length > 0 ? ` - ${reservations.length} reservation(s)` : ''
                }`}
                tabIndex={0}
                className={`absolute flex flex-col items-center justify-center rounded-lg border-2 cursor-pointer select-none transition-shadow hover:shadow-lg ${colourClass} ${
                  editMode ? 'cursor-move' : ''
                } ${isMerged ? 'ring-2 ring-purple-400' : ''}`}
                style={{
                  left: `${table.position_x}px`,
                  top: `${table.position_y}px`,
                  width: `${table.width}px`,
                  height: `${table.height}px`,
                }}
                onClick={() => handleTableTap(table.id)}
                onMouseDown={(e) => handleDragStart(e, table.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    handleTableTap(table.id)
                  }
                }}
              >
                <span className="text-sm font-bold">{table.table_number}</span>
                <span className="text-xs">{table.seat_count} seats</span>
                {reservations.length > 0 && (
                  <span className="text-xs mt-0.5 font-medium">
                    {reservations[0].customer_name}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}

      {!loading && state && state.tables.length === 0 && (
        <div className="py-8 text-center text-sm text-gray-500">
          No tables on this floor plan. Add tables to get started.
        </div>
      )}

      {/* Quick status actions for selected table */}
      {!editMode && state && (
        <div className="mt-6">
          <h2 className="text-lg font-medium text-gray-800 mb-3">Quick Actions</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {state.tables.map((table) => (
              <div key={table.id} className="rounded-lg border p-3 text-sm">
                <div className="font-medium mb-2">Table {table.table_number}</div>
                <div className="flex flex-wrap gap-1">
                  {table.status === 'occupied' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'needs_cleaning')}
                      className="rounded bg-yellow-100 px-2 py-1 text-xs text-yellow-800 hover:bg-yellow-200"
                    >
                      Mark Paid
                    </button>
                  )}
                  {table.status === 'needs_cleaning' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'available')}
                      className="rounded bg-green-100 px-2 py-1 text-xs text-green-800 hover:bg-green-200"
                    >
                      Mark Clean
                    </button>
                  )}
                  {table.status === 'available' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'occupied')}
                      className="rounded bg-red-100 px-2 py-1 text-xs text-red-800 hover:bg-red-200"
                    >
                      Seat Guests
                    </button>
                  )}
                  {table.status === 'reserved' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'occupied')}
                      className="rounded bg-red-100 px-2 py-1 text-xs text-red-800 hover:bg-red-200"
                    >
                      Seat Reservation
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
