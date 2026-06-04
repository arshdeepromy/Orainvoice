/**
 * Floor plan editor with drag-and-drop table positioning,
 * real-time status colours, POS integration on tap,
 * table merge/split, touch gestures, and reservation timeline.
 *
 * Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import apiClient from '@/api/client'
import { useModuleGuard } from '@/hooks/useModuleGuard'
import { useFlag } from '@/contexts/FeatureFlagContext'
import { useTerm } from '@/contexts/TerminologyContext'
import { getTableStatusColor } from '@/utils/tableCalcs'

/* ── Types ── */

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
  label?: string
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

/* ── Colour maps driven by getTableStatusColor ── */

const STATUS_BG: Record<string, string> = {
  green: 'bg-ok-soft border-ok text-ok',
  amber: 'bg-warn-soft border-warn text-warn',
  blue: 'bg-accent-soft border-accent text-accent',
  red: 'bg-danger-soft border-danger text-danger',
  gray: 'bg-canvas border-border text-muted',
}

const STATUS_LABELS: Record<string, string> = {
  available: 'Available',
  occupied: 'Occupied',
  needs_cleaning: 'Needs Cleaning',
  reserved: 'Reserved',
}

/* ── New table form ── */

interface NewTableForm {
  table_number: string
  seat_count: number
  label: string
}

const EMPTY_TABLE_FORM: NewTableForm = { table_number: '', seat_count: 4, label: '' }

/* ── Resize handle ── */

interface ResizeState {
  tableId: string
  startX: number
  startY: number
  startW: number
  startH: number
}

interface FloorPlanProps {
  floorPlanId?: string
  onTableTap?: (tableId: string) => void
}

export default function FloorPlan({ floorPlanId, onTableTap }: FloorPlanProps) {
  const { isAllowed, isLoading: guardLoading, toasts, dismissToast } = useModuleGuard('tables')
  const floorPlanEnabled = useFlag('floor_plan')
  const tableTerm = useTerm('table', 'Table')
  const navigate = useNavigate()

  const [state, setState] = useState<FloorPlanState | null>(null)
  const [floorPlans, setFloorPlans] = useState<FloorPlanData[]>([])
  const [selectedPlanId, setSelectedPlanId] = useState(floorPlanId || '')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editMode, setEditMode] = useState(false)

  /* Drag state */
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 })
  const canvasRef = useRef<HTMLDivElement>(null)

  /* Resize state */
  const resizeRef = useRef<ResizeState | null>(null)

  /* Merge/split state */
  const [mergeSelection, setMergeSelection] = useState<string[]>([])
  const [showMergeFeedback, setShowMergeFeedback] = useState('')

  /* New table form */
  const [showNewTableForm, setShowNewTableForm] = useState(false)
  const [newTableForm, setNewTableForm] = useState<NewTableForm>(EMPTY_TABLE_FORM)

  /* Touch zoom */
  const [zoom, setZoom] = useState(1)
  const lastPinchDist = useRef<number | null>(null)

  /* Long-press */
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [contextMenuTable, setContextMenuTable] = useState<string | null>(null)

  /* Polling interval */
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  /* ── Data fetching ── */

  const fetchFloorPlans = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v2/tables/floor-plans')
      const plans = res.data?.floor_plans ?? []
      setFloorPlans(plans)
      if (!selectedPlanId && plans.length > 0) {
        setSelectedPlanId(plans[0].id)
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

  /* Poll for real-time status updates every 10s */
  useEffect(() => {
    if (!selectedPlanId) return
    pollRef.current = setInterval(() => {
      apiClient
        .get(`/api/v2/tables/floor-plans/${selectedPlanId}/state`)
        .then((res) => setState(res.data))
        .catch(() => { /* silent poll failure */ })
    }, 10_000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [selectedPlanId])

  /* ── Status change ── */

  const handleStatusChange = async (tableId: string, newStatus: string) => {
    try {
      await apiClient.put(`/api/v2/tables/tables/${tableId}/status`, { status: newStatus })
      fetchState()
    } catch {
      setError('Failed to update table status.')
    }
  }

  /* ── POS integration on table tap (Req 14.3) ── */

  const handleTableTap = (tableId: string) => {
    if (editMode) return
    if (onTableTap) {
      onTableTap(tableId)
      return
    }
    // Navigate to POS with table context
    navigate(`/pos?table=${tableId}`)
  }

  /* ── Drag-and-drop (Req 14.1) ── */

  const handleDragStart = (e: React.MouseEvent | React.TouchEvent, tableId: string) => {
    if (!editMode) return
    const table = state?.tables.find((t) => t.id === tableId)
    if (!table || !canvasRef.current) return
    const rect = canvasRef.current.getBoundingClientRect()
    const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
    const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
    setDraggingId(tableId)
    setDragOffset({
      x: clientX - rect.left - table.position_x * zoom,
      y: clientY - rect.top - table.position_y * zoom,
    })
  }

  const handleDragMove = (e: React.MouseEvent | React.TouchEvent) => {
    if (!draggingId || !canvasRef.current || !state) return
    const rect = canvasRef.current.getBoundingClientRect()
    const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
    const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
    const newX = Math.max(0, (clientX - rect.left - dragOffset.x) / zoom)
    const newY = Math.max(0, (clientY - rect.top - dragOffset.y) / zoom)
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
          position_x: Math.round(table.position_x),
          position_y: Math.round(table.position_y),
        })
      } catch {
        setError('Failed to save table position.')
      }
    }
    setDraggingId(null)
  }

  /* ── Resize (Req 14.1) ── */

  const handleResizeStart = (e: React.MouseEvent, tableId: string) => {
    e.stopPropagation()
    if (!editMode || !state) return
    const table = state.tables.find((t) => t.id === tableId)
    if (!table) return
    resizeRef.current = {
      tableId,
      startX: e.clientX,
      startY: e.clientY,
      startW: table.width,
      startH: table.height,
    }
    const onMove = (ev: MouseEvent) => {
      if (!resizeRef.current || !state) return
      const dx = ev.clientX - resizeRef.current.startX
      const dy = ev.clientY - resizeRef.current.startY
      const newW = Math.max(60, resizeRef.current.startW + dx / zoom)
      const newH = Math.max(60, resizeRef.current.startH + dy / zoom)
      setState((prev) =>
        prev
          ? {
              ...prev,
              tables: prev.tables.map((t) =>
                t.id === resizeRef.current!.tableId
                  ? { ...t, width: newW, height: newH }
                  : t,
              ),
            }
          : prev,
      )
    }
    const onUp = async () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      if (!resizeRef.current) return
      const tbl = state.tables.find((t) => t.id === resizeRef.current!.tableId)
      if (tbl) {
        try {
          await apiClient.put(`/api/v2/tables/tables/${tbl.id}`, {
            width: Math.round(tbl.width),
            height: Math.round(tbl.height),
          })
        } catch {
          setError('Failed to save table size.')
        }
      }
      resizeRef.current = null
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  /* ── Add new table (Req 14.1) ── */

  const handleAddTable = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedPlanId) return
    try {
      await apiClient.post('/api/v2/tables/tables', {
        floor_plan_id: selectedPlanId,
        table_number: newTableForm.table_number,
        seat_count: newTableForm.seat_count,
        position_x: 50,
        position_y: 50,
        width: 100,
        height: 100,
        label: newTableForm.label || undefined,
      })
      setNewTableForm(EMPTY_TABLE_FORM)
      setShowNewTableForm(false)
      fetchState()
    } catch {
      setError('Failed to add table.')
    }
  }

  /* ── Merge / Split (Req 14.5) ── */

  const toggleMergeSelect = (tableId: string) => {
    setMergeSelection((prev) =>
      prev.includes(tableId) ? prev.filter((id) => id !== tableId) : [...prev, tableId],
    )
  }

  const handleMerge = async () => {
    if (mergeSelection.length < 2) return
    try {
      await apiClient.post('/api/v2/tables/tables/merge', { table_ids: mergeSelection })
      setMergeSelection([])
      setShowMergeFeedback('Tables merged successfully')
      setTimeout(() => setShowMergeFeedback(''), 3000)
      fetchState()
    } catch {
      setError('Failed to merge tables.')
    }
  }

  const handleSplit = async (tableId: string) => {
    try {
      await apiClient.post(`/api/v2/tables/tables/${tableId}/split`)
      setShowMergeFeedback('Table split successfully')
      setTimeout(() => setShowMergeFeedback(''), 3000)
      fetchState()
    } catch {
      setError('Failed to split table.')
    }
  }

  /* ── Touch gestures (Req 14.6 / 19.5) ── */

  const handleTouchStart = (e: React.TouchEvent, tableId: string) => {
    // Pinch-to-zoom detection
    if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX
      const dy = e.touches[0].clientY - e.touches[1].clientY
      lastPinchDist.current = Math.hypot(dx, dy)
      return
    }
    // Long-press detection
    longPressTimer.current = setTimeout(() => {
      setContextMenuTable(tableId)
    }, 500)
    // Also start drag for single touch in edit mode
    if (editMode) handleDragStart(e, tableId)
  }

  const handleTouchMove = (e: React.TouchEvent) => {
    // Cancel long-press on move
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
    // Pinch-to-zoom
    if (e.touches.length === 2 && lastPinchDist.current !== null) {
      const dx = e.touches[0].clientX - e.touches[1].clientX
      const dy = e.touches[0].clientY - e.touches[1].clientY
      const dist = Math.hypot(dx, dy)
      const scale = dist / lastPinchDist.current
      setZoom((prev) => Math.min(3, Math.max(0.5, prev * scale)))
      lastPinchDist.current = dist
      return
    }
    // Drag move
    if (editMode) handleDragMove(e)
  }

  const handleTouchEnd = () => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
    lastPinchDist.current = null
    if (editMode) handleDragEnd()
  }

  /* ── Helpers ── */

  const getReservationsForTable = (tableId: string) =>
    state?.reservations.filter((r) => r.table_id === tableId) ?? []

  const getColourClass = (status: string) => {
    const colour = getTableStatusColor(status)
    return STATUS_BG[colour] ?? STATUS_BG.gray
  }

  /* ── Guard / loading ── */

  if (guardLoading) {
    return (
      <div className="p-6 text-center text-sm text-muted" role="status" data-testid="floor-plan-guard-loading">
        Loading…
      </div>
    )
  }
  if (!isAllowed) return null

  /* ── Render ── */

  return (
    <div className="p-6" data-testid="floor-plan-page">
      {/* Toast container */}
      {toasts.length > 0 && (
        <div className="fixed top-4 right-4 z-50 space-y-2">
          {toasts.map((t) => (
            <div
              key={t.id}
              className="rounded-ctl bg-warn-soft border border-warn px-4 py-2 text-sm text-warn shadow-card"
            >
              {t.message}
              <button onClick={() => dismissToast(t.id)} className="ml-2 font-bold">×</button>
            </div>
          ))}
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-2xl font-semibold text-text" data-testid="floor-plan-heading">
          {tableTerm} Floor Plan
        </h1>
        <div className="flex flex-wrap items-center gap-3">
          {floorPlans.length > 1 && (
            <select
              aria-label="Select floor plan"
              data-testid="floor-plan-selector"
              value={selectedPlanId}
              onChange={(e) => setSelectedPlanId(e.target.value)}
              className="rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text min-h-[44px]"
            >
              {floorPlans.map((fp) => (
                <option key={fp.id} value={fp.id}>{fp.name}</option>
              ))}
            </select>
          )}
          <button
            onClick={() => setEditMode(!editMode)}
            data-testid="edit-layout-btn"
            className={`rounded-ctl px-4 py-2 text-sm font-medium min-h-[44px] min-w-[44px] ${
              editMode
                ? 'bg-accent text-white'
                : 'border border-border text-text hover:bg-canvas'
            }`}
            aria-pressed={editMode}
          >
            {editMode ? 'Done Editing' : 'Edit Layout'}
          </button>
          {/* Zoom controls */}
          <div className="flex items-center gap-1 text-sm text-muted">
            <button
              onClick={() => setZoom((z) => Math.max(0.5, z - 0.1))}
              className="rounded-ctl border border-border px-2 py-1 min-h-[44px] min-w-[44px]"
              aria-label="Zoom out"
              data-testid="zoom-out-btn"
            >
              −
            </button>
            <span className="mono" data-testid="zoom-level">{Math.round(zoom * 100)}%</span>
            <button
              onClick={() => setZoom((z) => Math.min(3, z + 0.1))}
              className="rounded-ctl border border-border px-2 py-1 min-h-[44px] min-w-[44px]"
              aria-label="Zoom in"
              data-testid="zoom-in-btn"
            >
              +
            </button>
          </div>
        </div>
      </div>

      {/* Status legend */}
      <div className="flex flex-wrap gap-4 mb-4" role="list" aria-label="Status legend" data-testid="status-legend">
        {Object.entries(STATUS_LABELS).map(([status, label]) => {
          const colour = getTableStatusColor(status)
          const dotClass =
            colour === 'green' ? 'bg-ok' :
            colour === 'amber' ? 'bg-warn' :
            colour === 'blue' ? 'bg-accent' :
            colour === 'red' ? 'bg-danger' : 'bg-muted-2'
          return (
            <div key={status} className="flex items-center gap-1.5 text-xs" role="listitem">
              <span className={`inline-block h-3 w-3 rounded-full ${dotClass}`} />
              <span>{label}</span>
            </div>
          )
        })}
      </div>

      {/* Merge/split feedback */}
      {showMergeFeedback && (
        <div className="mb-4 rounded-ctl border border-ok bg-ok-soft px-4 py-3 text-sm text-ok" role="status" data-testid="merge-feedback">
          {showMergeFeedback}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-ctl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger" role="alert" data-testid="floor-plan-error">
          {error}
          <button onClick={() => setError('')} className="ml-2 font-bold">×</button>
        </div>
      )}

      {/* Edit mode toolbar */}
      {editMode && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-card border border-accent bg-accent-soft p-3" data-testid="edit-toolbar">
          <button
            onClick={() => setShowNewTableForm(!showNewTableForm)}
            className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press min-h-[44px]"
            data-testid="add-table-btn"
          >
            + Add {tableTerm}
          </button>
          {mergeSelection.length >= 2 && (
            <button
              onClick={handleMerge}
              className="rounded-ctl bg-purple px-4 py-2 text-sm font-medium text-white hover:brightness-95 min-h-[44px]"
              data-testid="merge-tables-btn"
            >
              Merge Selected ({mergeSelection.length})
            </button>
          )}
          {mergeSelection.length > 0 && (
            <button
              onClick={() => setMergeSelection([])}
              className="rounded-ctl border border-border px-4 py-2 text-sm text-text hover:bg-canvas min-h-[44px]"
              data-testid="clear-merge-btn"
            >
              Clear Selection
            </button>
          )}
          <span className="text-xs text-accent">
            Drag to move • Corner handle to resize • Click to select for merge
          </span>
        </div>
      )}

      {/* New table form */}
      {editMode && showNewTableForm && (
        <form onSubmit={handleAddTable} className="mb-4 rounded-card border border-border p-4 bg-card" data-testid="new-table-form">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label htmlFor="new-table-number" className="block text-sm font-medium text-text mb-1">
                {tableTerm} Number
              </label>
              <input
                id="new-table-number"
                type="text"
                required
                value={newTableForm.table_number}
                onChange={(e) => setNewTableForm({ ...newTableForm, table_number: e.target.value })}
                className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text min-h-[44px]"
                data-testid="new-table-number-input"
              />
            </div>
            <div>
              <label htmlFor="new-table-seats" className="block text-sm font-medium text-text mb-1">Seats</label>
              <input
                id="new-table-seats"
                type="number"
                inputMode="numeric"
                min={1}
                required
                value={newTableForm.seat_count}
                onChange={(e) => setNewTableForm({ ...newTableForm, seat_count: parseInt(e.target.value) || 1 })}
                className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text min-h-[44px]"
                data-testid="new-table-seats-input"
              />
            </div>
            <div>
              <label htmlFor="new-table-label" className="block text-sm font-medium text-text mb-1">Label</label>
              <input
                id="new-table-label"
                type="text"
                value={newTableForm.label}
                onChange={(e) => setNewTableForm({ ...newTableForm, label: e.target.value })}
                className="w-full rounded-ctl border border-border bg-card px-3 py-2 text-sm text-text min-h-[44px]"
                placeholder="e.g. Window, Patio"
                data-testid="new-table-label-input"
              />
            </div>
          </div>
          <div className="mt-3">
            <button
              type="submit"
              disabled={!newTableForm.table_number}
              className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press disabled:opacity-50 min-h-[44px]"
              data-testid="save-new-table-btn"
            >
              Place {tableTerm}
            </button>
          </div>
        </form>
      )}

      {loading && (
        <div className="py-12 text-center text-sm text-muted" role="status" aria-label="Loading floor plan" data-testid="floor-plan-loading">
          Loading floor plan…
        </div>
      )}

      {/* Canvas */}
      {!loading && state && (
        <div
          ref={canvasRef}
          className="relative border-2 border-border rounded-card bg-canvas overflow-auto touch-none"
          style={{
            width: '100%',
            maxWidth: '100%',
            height: `${state.floor_plan.height * zoom}px`,
            maxHeight: '70vh',
          }}
          onMouseMove={handleDragMove}
          onMouseUp={handleDragEnd}
          onMouseLeave={handleDragEnd}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          role="application"
          aria-label="Floor plan canvas"
          data-testid="floor-plan-canvas"
        >
          <div
            style={{
              width: `${state.floor_plan.width * zoom}px`,
              height: `${state.floor_plan.height * zoom}px`,
              position: 'relative',
              transformOrigin: '0 0',
            }}
          >
            {state.tables.map((table) => {
              const colourClass = getColourClass(table.status)
              const reservations = getReservationsForTable(table.id)
              const isMerged = table.merged_with_id !== null
              const isSelected = mergeSelection.includes(table.id)

              return (
                <div
                  key={table.id}
                  role="button"
                  aria-label={`${tableTerm} ${table.table_number} - ${STATUS_LABELS[table.status] ?? table.status}${
                    reservations.length > 0 ? ` - ${reservations.length} reservation(s)` : ''
                  }`}
                  tabIndex={0}
                  data-testid={`table-${table.table_number}`}
                  className={`absolute flex flex-col items-center justify-center rounded-card border-2 cursor-pointer select-none transition-shadow hover:shadow-pop ${colourClass} ${
                    editMode ? 'cursor-move' : ''
                  } ${isMerged ? 'ring-2 ring-purple' : ''} ${
                    isSelected ? 'ring-4 ring-accent ring-offset-2' : ''
                  }`}
                  style={{
                    left: `${table.position_x * zoom}px`,
                    top: `${table.position_y * zoom}px`,
                    width: `${table.width * zoom}px`,
                    height: `${table.height * zoom}px`,
                    minWidth: '44px',
                    minHeight: '44px',
                  }}
                  onClick={() => {
                    if (editMode && mergeSelection.length >= 0) {
                      toggleMergeSelect(table.id)
                    } else {
                      handleTableTap(table.id)
                    }
                  }}
                  onMouseDown={(e) => handleDragStart(e, table.id)}
                  onTouchStart={(e) => handleTouchStart(e, table.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      handleTableTap(table.id)
                    }
                  }}
                >
                  <span className="text-sm font-bold">{table.table_number}</span>
                  <span className="text-xs">{table.seat_count} seats</span>
                  {table.label && <span className="text-xs opacity-75">{table.label}</span>}
                  {reservations.length > 0 && (
                    <span className="text-xs mt-0.5 font-medium">
                      {reservations[0].customer_name}
                    </span>
                  )}
                  {/* Resize handle in edit mode */}
                  {editMode && (
                    <div
                      className="absolute bottom-0 right-0 w-4 h-4 bg-muted rounded-tl cursor-se-resize"
                      onMouseDown={(e) => handleResizeStart(e, table.id)}
                      data-testid={`resize-handle-${table.table_number}`}
                    />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {!loading && state && state.tables.length === 0 && (
        <div className="py-8 text-center text-sm text-muted" data-testid="no-tables-message">
          No tables on this floor plan. {editMode ? 'Use "Add Table" to get started.' : 'Switch to Edit Layout to add tables.'}
        </div>
      )}

      {/* Context menu (long-press) */}
      {contextMenuTable && state && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setContextMenuTable(null)}
          data-testid="context-menu-overlay"
        >
          <div
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-card rounded-card shadow-pop border border-border p-4 z-50 min-w-[200px]"
            onClick={(e) => e.stopPropagation()}
            data-testid="context-menu"
          >
            {(() => {
              const tbl = state.tables.find((t) => t.id === contextMenuTable)
              if (!tbl) return null
              return (
                <>
                  <div className="font-medium mb-3 text-text">{tableTerm} {tbl.table_number}</div>
                  <div className="space-y-2">
                    <button
                      onClick={() => { handleTableTap(tbl.id); setContextMenuTable(null) }}
                      className="w-full text-left px-3 py-2 rounded-ctl hover:bg-canvas text-sm text-text min-h-[44px]"
                      data-testid="ctx-open-order"
                    >
                      Open / Create Order
                    </button>
                    {tbl.merged_with_id && (
                      <button
                        onClick={() => { handleSplit(tbl.id); setContextMenuTable(null) }}
                        className="w-full text-left px-3 py-2 rounded-ctl hover:bg-canvas text-sm text-text min-h-[44px]"
                        data-testid="ctx-split-table"
                      >
                        Split {tableTerm}
                      </button>
                    )}
                    {Object.keys(STATUS_LABELS).filter((s) => s !== tbl.status).map((s) => (
                      <button
                        key={s}
                        onClick={() => { handleStatusChange(tbl.id, s); setContextMenuTable(null) }}
                        className="w-full text-left px-3 py-2 rounded-ctl hover:bg-canvas text-sm text-text min-h-[44px]"
                        data-testid={`ctx-status-${s}`}
                      >
                        Set {STATUS_LABELS[s]}
                      </button>
                    ))}
                  </div>
                </>
              )
            })()}
          </div>
        </div>
      )}

      {/* Quick status actions */}
      {!editMode && state && state.tables.length > 0 && (
        <div className="mt-6" data-testid="quick-actions">
          <h2 className="text-lg font-medium text-text mb-3">Quick Actions</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {state.tables.map((table) => (
              <div key={table.id} className="rounded-card border border-border p-3 text-sm" data-testid={`quick-action-${table.table_number}`}>
                <div className="font-medium mb-2 text-text">{tableTerm} {table.table_number}</div>
                <div className="flex flex-wrap gap-1">
                  {table.status === 'occupied' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'needs_cleaning')}
                      className="rounded-ctl bg-warn-soft px-2 py-1 text-xs text-warn hover:brightness-95 min-h-[44px] min-w-[44px]"
                      data-testid={`mark-paid-${table.table_number}`}
                    >
                      Mark Paid
                    </button>
                  )}
                  {table.status === 'needs_cleaning' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'available')}
                      className="rounded-ctl bg-ok-soft px-2 py-1 text-xs text-ok hover:brightness-95 min-h-[44px] min-w-[44px]"
                      data-testid={`mark-clean-${table.table_number}`}
                    >
                      Mark Clean
                    </button>
                  )}
                  {table.status === 'available' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'occupied')}
                      className="rounded-ctl bg-danger-soft px-2 py-1 text-xs text-danger hover:brightness-95 min-h-[44px] min-w-[44px]"
                      data-testid={`seat-guests-${table.table_number}`}
                    >
                      Seat Guests
                    </button>
                  )}
                  {table.status === 'reserved' && (
                    <button
                      onClick={() => handleStatusChange(table.id, 'occupied')}
                      className="rounded-ctl bg-danger-soft px-2 py-1 text-xs text-danger hover:brightness-95 min-h-[44px] min-w-[44px]"
                      data-testid={`seat-reservation-${table.table_number}`}
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

      {/* Reservation timeline (Req 14.4) — gated by feature flag */}
      {floorPlanEnabled && !editMode && state && state.reservations.length > 0 && (
        <div className="mt-6" data-testid="reservation-timeline">
          <h2 className="text-lg font-medium text-text mb-3">Upcoming Reservations</h2>
          <div className="space-y-2">
            {state.reservations
              .sort((a, b) => a.reservation_time.localeCompare(b.reservation_time))
              .map((r) => {
                const endMinutes =
                  parseInt(r.reservation_time.split(':')[0]) * 60 +
                  parseInt(r.reservation_time.split(':')[1]) +
                  r.duration_minutes
                const endH = String(Math.floor(endMinutes / 60) % 24).padStart(2, '0')
                const endM = String(endMinutes % 60).padStart(2, '0')
                const tbl = state.tables.find((t) => t.id === r.table_id)
                return (
                  <div
                    key={r.id}
                    className="flex items-center gap-4 rounded-card border border-border p-3 text-sm"
                    data-testid={`timeline-reservation-${r.id}`}
                  >
                    <div className="font-medium min-w-[60px] text-text">{r.reservation_time}</div>
                    <div className="h-4 w-px bg-border" />
                    <div className="flex-1">
                      <span className="font-medium text-text">{r.customer_name}</span>
                      <span className="text-muted ml-2">
                        Party of {r.party_size} • {tableTerm} {tbl?.table_number ?? '?'} • until {endH}:{endM}
                      </span>
                    </div>
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                      r.status === 'confirmed' ? 'bg-ok-soft text-ok' :
                      r.status === 'seated' ? 'bg-accent-soft text-accent' :
                      'bg-canvas text-muted'
                    }`}>
                      {r.status}
                    </span>
                  </div>
                )
              })}
          </div>
        </div>
      )}
    </div>
  )
}
