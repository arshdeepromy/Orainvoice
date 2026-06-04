/**
 * RosterGrid — staff rows × 14 day columns (Workstream B / task B5).
 *
 * Pure presentational component. Accepts already-loaded staff,
 * entries, and a leave overlay map — no fetching here.
 *
 * Workstream B extensions (B7, B9, B10, B13, B14, B20):
 *   - Paint-mode pointer capture with rectangle highlight.
 *   - Drag-resize handle on entry blocks.
 *   - Multi-select staff rows + day columns (Shift+click range).
 *   - Focused-cell state with `tabindex=0` only on the focus.
 *   - Saving placeholder visual state (`opacity-60 animate-pulse`).
 *   - `data-conflict="true"` outline for conflict cells.
 *
 * Logic copied verbatim from
 * frontend/src/pages/staff-schedule/components/RosterGrid.tsx; the grid
 * chrome (borders/backgrounds/selection highlights) is remapped onto the
 * design-system tokens. The colour-coded entry legend (job/booking/break/
 * leave/other) is preserved as-is so the visual distinction between entry
 * types stays intact.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type {
  ScheduleEntryResponse,
  ShiftTemplateResponse,
} from '@/types/schedule'
import type {
  LeaveOverlay,
  StaffMember,
} from '../hooks/useRosterGridData'
import { computePaintRectangle } from '../utils/paint'
import { toIsoDate } from '../utils/time'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDayHeader(date: Date): { dow: string; dom: string } {
  const dow = new Intl.DateTimeFormat('en-NZ', { weekday: 'short' }).format(
    date,
  )
  const dom = new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric',
    month: 'short',
  }).format(date)
  return { dow, dom }
}

function formatEntryTimes(entry: ScheduleEntryResponse): string {
  const fmt = (iso: string) => {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    const h = String(d.getHours()).padStart(2, '0')
    const m = String(d.getMinutes()).padStart(2, '0')
    return `${h}:${m}`
  }
  return `${fmt(entry.start_time)}-${fmt(entry.end_time)}`
}

function indexEntries(
  entries: ScheduleEntryResponse[],
): Map<string, Map<string, ScheduleEntryResponse[]>> {
  const out = new Map<string, Map<string, ScheduleEntryResponse[]>>()
  for (const e of entries ?? []) {
    if (!e.staff_id) continue
    const start = new Date(e.start_time)
    if (Number.isNaN(start.getTime())) continue
    const dateKey = toIsoDate(start)
    if (!out.has(e.staff_id)) out.set(e.staff_id, new Map())
    const inner = out.get(e.staff_id)!
    if (!inner.has(dateKey)) inner.set(dateKey, [])
    inner.get(dateKey)!.push(e)
  }
  for (const inner of out.values()) {
    for (const list of inner.values()) {
      list.sort((a, b) => a.start_time.localeCompare(b.start_time))
    }
  }
  return out
}

const ENTRY_COLOURS: Record<
  string,
  { bg: string; border: string; text: string }
> = {
  job: { bg: 'bg-blue-100', border: 'border-blue-400', text: 'text-blue-800' },
  booking: {
    bg: 'bg-emerald-100',
    border: 'border-emerald-400',
    text: 'text-emerald-800',
  },
  break: {
    bg: 'bg-amber-100',
    border: 'border-amber-400',
    text: 'text-amber-800',
  },
  leave: {
    bg: 'bg-gray-200',
    border: 'border-gray-400',
    text: 'text-gray-600',
  },
  other: {
    bg: 'bg-purple-100',
    border: 'border-purple-400',
    text: 'text-purple-800',
  },
}

function GridSkeleton() {
  const rows = 5
  const cols = 14
  return (
    <div
      className="overflow-hidden rounded-card border border-border bg-card"
      data-testid="roster-grid-skeleton"
      aria-busy="true"
    >
      <div
        className="grid"
        style={{
          gridTemplateColumns: `200px repeat(${cols}, minmax(80px, 1fr))`,
        }}
      >
        <div className="border-b border-r border-border bg-canvas p-2" />
        {Array.from({ length: cols }).map((_, c) => (
          <div
            key={`skh-${c}`}
            className="border-b border-r border-border bg-canvas p-2"
          >
            <div className="h-3 w-12 animate-pulse rounded bg-border" />
          </div>
        ))}
        {Array.from({ length: rows }).map((_, r) => (
          <div key={`skr-${r}`} className="contents">
            <div className="border-b border-r border-border p-2">
              <div className="h-3 w-32 animate-pulse rounded bg-border" />
            </div>
            {Array.from({ length: cols }).map((__, c) => (
              <div
                key={`sk-${r}-${c}`}
                className="border-b border-r border-border p-2"
              >
                <div className="h-6 w-full animate-pulse rounded bg-canvas" />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyStaffState() {
  return (
    <div
      className="mx-auto mt-12 max-w-md rounded-card border border-border bg-card p-8 text-center"
      data-testid="roster-grid-empty"
    >
      <h2 className="text-base font-semibold text-text">
        No active staff
      </h2>
      <p className="mt-2 text-sm text-muted">
        Add a staff member to start rostering.
      </p>
      <Link
        to="/staff"
        className="mt-4 inline-block rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Go to Staff
      </Link>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export interface CellResizeRequest {
  entry: ScheduleEntryResponse
  newEndTime: Date
}

export interface RosterGridProps {
  staff: StaffMember[]
  entries: ScheduleEntryResponse[]
  leaveByStaffDate: Map<string, Map<string, LeaveOverlay>>
  visibleWindow: { start: Date; end: Date }
  isLoading: boolean
  onCellClick?: (
    staffId: string,
    date: Date,
    cellEntries: ScheduleEntryResponse[],
    anchor: { x: number; y: number },
  ) => void

  paintMode?: boolean
  selectedTemplate?: ShiftTemplateResponse | null
  onPaintCommit?: (rect: {
    cells: Array<{ staffId: string; date: Date }>
    altKey: boolean
  }) => void
  onPaintCancel?: () => void

  selectedStaff?: Set<string>
  setSelectedStaff?: (next: Set<string>) => void
  selectedDays?: Set<string>
  setSelectedDays?: (next: Set<string>) => void

  focusedCell?: { row: number; col: number } | null
  setFocusedCell?: (cell: { row: number; col: number }) => void
  selectionAnchor?: { row: number; col: number } | null

  onResizeCommit?: (req: CellResizeRequest) => void
  pixelsPerHour?: number

  conflictCells?: Set<string>
  savingEntryIds?: Set<string>
  ariaBusy?: boolean
}

function cellKey(staffId: string, dateKey: string): string {
  return `${staffId}|${dateKey}`
}

export default function RosterGrid({
  staff,
  entries,
  leaveByStaffDate,
  visibleWindow,
  isLoading,
  onCellClick,
  paintMode = false,
  selectedTemplate = null,
  onPaintCommit,
  onPaintCancel,
  selectedStaff,
  setSelectedStaff,
  selectedDays,
  setSelectedDays,
  focusedCell,
  setFocusedCell,
  selectionAnchor,
  onResizeCommit,
  pixelsPerHour = 60,
  conflictCells,
  savingEntryIds,
  ariaBusy = false,
}: RosterGridProps) {
  const [paintAnchor, setPaintAnchor] = useState<{
    row: number
    col: number
  } | null>(null)
  const [paintEnd, setPaintEnd] = useState<{ row: number; col: number } | null>(
    null,
  )
  const [resizeDrag, setResizeDrag] = useState<{
    entryId: string
    startX: number
    ghostEndIso: string | null
  } | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const lastStaffClickRef = useRef<number | null>(null)
  const lastDayClickRef = useRef<number | null>(null)

  const dates = useMemo(() => {
    const out: Date[] = []
    for (let i = 0; i < 14; i += 1) {
      const d = new Date(visibleWindow.start)
      d.setDate(d.getDate() + i)
      d.setHours(0, 0, 0, 0)
      out.push(d)
    }
    return out
  }, [visibleWindow.start])

  const sortedStaff = useMemo(() => {
    return [...(staff ?? [])].sort((a, b) => {
      const aLast = (a.last_name ?? '').toLowerCase()
      const bLast = (b.last_name ?? '').toLowerCase()
      if (aLast !== bLast) return aLast < bLast ? -1 : 1
      const aFirst = (a.first_name ?? '').toLowerCase()
      const bFirst = (b.first_name ?? '').toLowerCase()
      if (aFirst === bFirst) return 0
      return aFirst < bFirst ? -1 : 1
    })
  }, [staff])

  const entriesByStaffDate = useMemo(() => indexEntries(entries), [entries])

  useEffect(() => {
    if (!paintMode) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setPaintAnchor(null)
        setPaintEnd(null)
        onPaintCancel?.()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [paintMode, onPaintCancel])

  const paintHighlight = useMemo(() => {
    const set = new Set<string>()
    if (!paintMode || !paintAnchor || !paintEnd) return set
    const rect = computePaintRectangle(paintAnchor, paintEnd)
    for (let r = rect.rowStart; r <= rect.rowEnd; r += 1) {
      const s = sortedStaff[r]
      if (!s) continue
      for (let c = rect.colStart; c <= rect.colEnd; c += 1) {
        const d = dates[c]
        if (!d) continue
        set.add(cellKey(s.id, toIsoDate(d)))
      }
    }
    return set
  }, [paintMode, paintAnchor, paintEnd, sortedStaff, dates])

  const selectionRectHighlight = useMemo(() => {
    const set = new Set<string>()
    if (!focusedCell || !selectionAnchor) return set
    const rowStart = Math.min(focusedCell.row, selectionAnchor.row)
    const rowEnd = Math.max(focusedCell.row, selectionAnchor.row)
    const colStart = Math.min(focusedCell.col, selectionAnchor.col)
    const colEnd = Math.max(focusedCell.col, selectionAnchor.col)
    if (rowStart === rowEnd && colStart === colEnd) return set
    for (let r = rowStart; r <= rowEnd; r += 1) {
      const s = sortedStaff[r]
      if (!s) continue
      for (let c = colStart; c <= colEnd; c += 1) {
        const d = dates[c]
        if (!d) continue
        set.add(cellKey(s.id, toIsoDate(d)))
      }
    }
    return set
  }, [focusedCell, selectionAnchor, sortedStaff, dates])

  /* All hooks declared above; safe to early return below. */

  if (isLoading && sortedStaff.length === 0) {
    return <GridSkeleton />
  }
  if (!isLoading && sortedStaff.length === 0) {
    return <EmptyStaffState />
  }

  const cols = 14
  const useContentVisibilityHint = sortedStaff.length > 100
  const rowStyle: React.CSSProperties | undefined = useContentVisibilityHint
    ? {
        contentVisibility: 'auto',
        containIntrinsicSize: 'auto 56px',
      }
    : undefined

  /* ------------------------------------------------------------ */
  /*  Header click handlers (B10)                                  */
  /* ------------------------------------------------------------ */

  const handleStaffHeaderClick = (e: React.MouseEvent, rowIndex: number) => {
    if (!setSelectedStaff || !selectedStaff) return
    const next = new Set(selectedStaff)
    const id = sortedStaff[rowIndex]?.id
    if (!id) return
    if (e.shiftKey && lastStaffClickRef.current != null) {
      const start = Math.min(lastStaffClickRef.current, rowIndex)
      const end = Math.max(lastStaffClickRef.current, rowIndex)
      for (let i = start; i <= end; i += 1) {
        const sid = sortedStaff[i]?.id
        if (sid) next.add(sid)
      }
    } else {
      if (next.has(id)) next.delete(id)
      else next.add(id)
      lastStaffClickRef.current = rowIndex
    }
    setSelectedStaff(next)
  }

  const handleDayHeaderClick = (e: React.MouseEvent, colIndex: number) => {
    if (!setSelectedDays || !selectedDays) return
    const dateKey = toIsoDate(dates[colIndex])
    const next = new Set(selectedDays)
    if (e.shiftKey && lastDayClickRef.current != null) {
      const start = Math.min(lastDayClickRef.current, colIndex)
      const end = Math.max(lastDayClickRef.current, colIndex)
      for (let i = start; i <= end; i += 1) {
        next.add(toIsoDate(dates[i]))
      }
    } else {
      if (next.has(dateKey)) next.delete(dateKey)
      else next.add(dateKey)
      lastDayClickRef.current = colIndex
    }
    setSelectedDays(next)
  }

  /* ------------------------------------------------------------ */
  /*  Paint pointer handlers (B9)                                  */
  /* ------------------------------------------------------------ */

  const handleCellPointerDown = (
    e: React.PointerEvent,
    rowIndex: number,
    colIndex: number,
  ) => {
    if (!paintMode || !selectedTemplate) return
    e.preventDefault()
    setPaintAnchor({ row: rowIndex, col: colIndex })
    setPaintEnd({ row: rowIndex, col: colIndex })
  }

  const handleCellPointerEnter = (rowIndex: number, colIndex: number) => {
    if (!paintMode || !paintAnchor) return
    setPaintEnd({ row: rowIndex, col: colIndex })
  }

  const handleContainerPointerUp = (e: React.PointerEvent) => {
    if (paintMode && paintAnchor && paintEnd && onPaintCommit) {
      const rect = computePaintRectangle(paintAnchor, paintEnd)
      const cells: Array<{ staffId: string; date: Date }> = []
      for (let r = rect.rowStart; r <= rect.rowEnd; r += 1) {
        const s = sortedStaff[r]
        if (!s) continue
        for (let c = rect.colStart; c <= rect.colEnd; c += 1) {
          const d = dates[c]
          if (!d) continue
          cells.push({ staffId: s.id, date: d })
        }
      }
      onPaintCommit({ cells, altKey: e.altKey })
    }
    setPaintAnchor(null)
    setPaintEnd(null)
  }

  /* ------------------------------------------------------------ */
  /*  Resize handle pointer handlers (B7)                          */
  /* ------------------------------------------------------------ */

  const handleResizePointerDown = (
    e: React.PointerEvent,
    entry: ScheduleEntryResponse,
  ) => {
    if (!onResizeCommit) return
    e.stopPropagation()
    e.preventDefault()
    setResizeDrag({
      entryId: entry.id,
      startX: e.clientX,
      ghostEndIso: entry.end_time,
    })
    const target = e.currentTarget as HTMLElement
    if (target?.setPointerCapture) {
      try {
        target.setPointerCapture(e.pointerId)
      } catch {
        /* ignore — environments without pointer capture */
      }
    }
  }

  const handleResizePointerMove = (
    e: React.PointerEvent,
    entry: ScheduleEntryResponse,
  ) => {
    if (!resizeDrag || resizeDrag.entryId !== entry.id) return
    e.stopPropagation()
    const dx = e.clientX - resizeDrag.startX
    import('../utils/resize')
      .then(({ computeResizedEndTime }) => {
        const newEnd = computeResizedEndTime(
          new Date(entry.start_time),
          dx,
          pixelsPerHour,
        )
        setResizeDrag((prev) =>
          prev && prev.entryId === entry.id
            ? { ...prev, ghostEndIso: newEnd.toISOString() }
            : prev,
        )
      })
      .catch(() => {})
  }

  const handleResizePointerUp = (
    e: React.PointerEvent,
    entry: ScheduleEntryResponse,
  ) => {
    if (!resizeDrag || resizeDrag.entryId !== entry.id) return
    e.stopPropagation()
    const dx = e.clientX - resizeDrag.startX
    setResizeDrag(null)
    if (Math.abs(dx) < 4) return
    import('../utils/resize')
      .then(({ computeResizedEndTime }) => {
        const newEnd = computeResizedEndTime(
          new Date(entry.start_time),
          dx,
          pixelsPerHour,
        )
        onResizeCommit?.({ entry, newEndTime: newEnd })
      })
      .catch(() => {})
  }

  /* ------------------------------------------------------------ */
  /*  Render                                                       */
  /* ------------------------------------------------------------ */

  return (
    <div
      ref={containerRef}
      role="grid"
      aria-label="Roster grid"
      aria-busy={ariaBusy ? 'true' : undefined}
      data-testid="roster-grid"
      data-paint-mode={paintMode ? 'true' : undefined}
      className={`overflow-hidden rounded-card border border-border bg-card ${
        paintMode ? 'cursor-crosshair' : ''
      }`}
      onPointerUp={handleContainerPointerUp}
    >
      <div
        className="grid text-xs"
        style={{
          gridTemplateColumns: `200px repeat(${cols}, minmax(80px, 1fr))`,
        }}
      >
        {/* Header row */}
        <div
          role="columnheader"
          aria-label="Staff"
          className="sticky top-0 z-10 border-b border-r border-border bg-canvas px-2 py-2 font-medium text-text"
        >
          Staff
        </div>
        {dates.map((d, idx) => {
          const { dow, dom } = formatDayHeader(d)
          const isWeek2Start = idx === 7
          const dateKey = toIsoDate(d)
          const isSelectedDay = selectedDays?.has(dateKey)
          return (
            <button
              type="button"
              key={`h-${dateKey}`}
              role="columnheader"
              data-testid={`day-header-${dateKey}`}
              aria-pressed={isSelectedDay}
              onClick={(e) => handleDayHeaderClick(e, idx)}
              className={`sticky top-0 z-10 cursor-pointer border-b border-r border-border px-2 py-2 text-center font-medium text-text ${
                isWeek2Start ? 'border-l-2 border-l-border-strong' : ''
              } ${
                isSelectedDay ? 'bg-accent-soft' : 'bg-canvas hover:bg-border'
              }`}
            >
              <div>{dow}</div>
              <div className="mono text-[11px] font-normal text-muted">
                {dom}
              </div>
            </button>
          )
        })}

        {/* Body rows */}
        {sortedStaff.map((s, rowIndex) => {
          const isSelectedStaff = selectedStaff?.has(s.id)
          return (
            <div
              key={`row-${s.id}`}
              role="row"
              className="contents"
              style={rowStyle}
            >
              <button
                type="button"
                role="rowheader"
                onClick={(e) => handleStaffHeaderClick(e, rowIndex)}
                aria-pressed={isSelectedStaff}
                className={`cursor-pointer border-b border-r border-border px-2 py-2 text-left ${
                  isSelectedStaff ? 'bg-accent-soft' : 'bg-card hover:bg-canvas'
                }`}
              >
                <div className="font-medium text-text">
                  {s.name ??
                    `${s.first_name ?? ''} ${s.last_name ?? ''}`.trim()}
                </div>
                {s.position && (
                  <div className="text-[11px] text-muted">{s.position}</div>
                )}
              </button>
              {dates.map((d, colIndex) => {
                const dateKey = toIsoDate(d)
                const isWeek2Start = colIndex === 7
                const cellEntries =
                  entriesByStaffDate.get(s.id)?.get(dateKey) ?? []
                const leave = leaveByStaffDate.get(s.id)?.get(dateKey)
                const isLeave = !!leave
                const cId = cellKey(s.id, dateKey)
                const isFocused =
                  !!focusedCell &&
                  focusedCell.row === rowIndex &&
                  focusedCell.col === colIndex
                const isInPaint = paintHighlight.has(cId)
                const isInSelectionRect = selectionRectHighlight.has(cId)
                const isConflict = conflictCells?.has(cId)

                const baseCellClass = `relative min-h-[56px] border-b border-r border-border p-1 ${
                  isWeek2Start ? 'border-l-2 border-l-border-strong' : ''
                }`

                if (isLeave) {
                  return (
                    <div
                      key={`c-${s.id}-${dateKey}`}
                      role="gridcell"
                      tabIndex={isFocused ? 0 : -1}
                      aria-disabled="true"
                      data-staff-id={s.id}
                      data-date={dateKey}
                      data-leave="true"
                      data-conflict={isConflict ? 'true' : undefined}
                      onPointerDown={(e) =>
                        handleCellPointerDown(e, rowIndex, colIndex)
                      }
                      onPointerEnter={() =>
                        handleCellPointerEnter(rowIndex, colIndex)
                      }
                      className={`${baseCellClass} bg-canvas text-muted ${
                        isInPaint ? 'ring-2 ring-accent' : ''
                      } ${
                        isConflict ? 'outline outline-2 outline-danger' : ''
                      }`}
                      style={{
                        backgroundImage:
                          'repeating-linear-gradient(45deg, rgba(0,0,0,0.04) 0 4px, transparent 4px 8px)',
                      }}
                      title={`${leave.leave_type_label} (leave)`}
                    >
                      <div className="text-[11px] font-medium">
                        {leave.leave_type_label}
                      </div>
                    </div>
                  )
                }

                const empty = cellEntries.length === 0
                return (
                  <button
                    type="button"
                    key={`c-${s.id}-${dateKey}`}
                    role="gridcell"
                    tabIndex={isFocused ? 0 : -1}
                    data-staff-id={s.id}
                    data-date={dateKey}
                    data-row={rowIndex}
                    data-col={colIndex}
                    data-conflict={isConflict ? 'true' : undefined}
                    aria-selected={isInSelectionRect || undefined}
                    onPointerDown={(e) =>
                      handleCellPointerDown(e, rowIndex, colIndex)
                    }
                    onPointerEnter={() =>
                      handleCellPointerEnter(rowIndex, colIndex)
                    }
                    onClick={(e) => {
                      if (paintMode && paintAnchor) return
                      setFocusedCell?.({ row: rowIndex, col: colIndex })
                      onCellClick?.(s.id, d, cellEntries, {
                        x: e.clientX,
                        y: e.clientY,
                      })
                    }}
                    className={`${baseCellClass} group cursor-pointer text-left hover:bg-accent-soft focus:bg-accent-soft focus:outline-none focus:ring-2 focus:ring-accent ${
                      isInPaint ? 'ring-2 ring-accent bg-accent-soft' : ''
                    } ${
                      isInSelectionRect ? 'bg-accent-soft' : ''
                    } ${
                      isConflict ? 'outline outline-2 outline-danger' : ''
                    } ${isFocused ? 'ring-2 ring-accent' : ''}`}
                  >
                    {empty ? (
                      <span className="invisible text-[11px] text-accent group-hover:visible">
                        + Add
                      </span>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        {cellEntries.map((e) => {
                          const colour =
                            ENTRY_COLOURS[e.entry_type] ??
                            ENTRY_COLOURS.other
                          const isSaving = savingEntryIds?.has(e.id)
                          const isResizing = resizeDrag?.entryId === e.id
                          return (
                            <div
                              key={e.id}
                              className={`relative truncate rounded border ${colour.bg} ${colour.border} ${colour.text} px-1 py-0.5 text-[11px] ${
                                isSaving ? 'opacity-60 animate-pulse' : ''
                              } ${isResizing ? 'ring-2 ring-accent' : ''}`}
                              data-entry-id={e.id}
                              title={`${e.title ?? e.entry_type} ${formatEntryTimes(e)}`}
                            >
                              <span className="mono font-medium">
                                {formatEntryTimes(e)}
                              </span>{' '}
                              <span>{e.title ?? e.entry_type}</span>
                              {onResizeCommit && !isSaving && (
                                <span
                                  role="presentation"
                                  data-testid={`resize-handle-${e.id}`}
                                  className="absolute right-0 top-0 h-full w-[6px] cursor-ew-resize bg-transparent hover:bg-accent/40"
                                  onPointerDown={(ev) =>
                                    handleResizePointerDown(ev, e)
                                  }
                                  onPointerMove={(ev) =>
                                    handleResizePointerMove(ev, e)
                                  }
                                  onPointerUp={(ev) =>
                                    handleResizePointerUp(ev, e)
                                  }
                                />
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}
