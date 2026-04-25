import { useState, useRef, useCallback, type ReactNode } from 'react'

export interface DragDropItem {
  /** Unique identifier for the draggable item */
  id: string
  /** Column/group the item belongs to */
  columnId: string
}

export interface DragDropColumnConfig {
  /** Unique column identifier */
  id: string
  /** Display label for the column header */
  label: string
  /** Tailwind colour class for the column header accent */
  color?: string
}

export interface DragDropProps<T extends DragDropItem> {
  /** Column definitions */
  columns: DragDropColumnConfig[]
  /** All items across all columns */
  items: T[]
  /** Render function for each draggable item */
  renderItem: (item: T, isDragging: boolean) => ReactNode
  /** Called when an item is dropped into a different column */
  onDrop: (itemId: string, fromColumnId: string, toColumnId: string) => void
  /** Additional CSS classes for the container */
  className?: string
}

interface DragState {
  /** ID of the item being dragged */
  itemId: string
  /** Column the item started in */
  fromColumnId: string
  /** Current X position of the touch */
  currentX: number
  /** Current Y position of the touch */
  currentY: number
  /** Offset from touch point to element origin */
  offsetX: number
  /** Offset from touch point to element origin */
  offsetY: number
}

/**
 * Drag-and-drop for kanban board columns with touch support.
 *
 * - Horizontal scrollable columns
 * - Long-press to initiate drag
 * - Visual feedback during drag (elevated card, drop zone highlight)
 * - Touch event based (no HTML5 drag API for mobile compatibility)
 * - Dark mode support
 *
 * Requirements: 10.6
 */
export function DragDrop<T extends DragDropItem>({
  columns,
  items,
  renderItem,
  onDrop,
  className = '',
}: DragDropProps<T>) {
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [hoveredColumn, setHoveredColumn] = useState<string | null>(null)

  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const columnRefsMap = useRef<Map<string, HTMLDivElement>>(new Map())

  const LONG_PRESS_MS = 300

  const getColumnAtPoint = useCallback((x: number, y: number): string | null => {
    for (const [colId, el] of columnRefsMap.current.entries()) {
      const rect = el.getBoundingClientRect()
      if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
        return colId
      }
    }
    return null
  }, [])

  const handleTouchStart = useCallback(
    (itemId: string, columnId: string, e: React.TouchEvent) => {
      const touch = e.touches[0]
      const target = e.currentTarget as HTMLElement
      const rect = target.getBoundingClientRect()

      const offsetX = touch.clientX - rect.left
      const offsetY = touch.clientY - rect.top

      // Start long-press timer
      longPressTimerRef.current = setTimeout(() => {
        setDragState({
          itemId,
          fromColumnId: columnId,
          currentX: touch.clientX,
          currentY: touch.clientY,
          offsetX,
          offsetY,
        })
      }, LONG_PRESS_MS)
    },
    [],
  )

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      // Cancel long-press if user moves before timer fires
      if (!dragState && longPressTimerRef.current) {
        clearTimeout(longPressTimerRef.current)
        longPressTimerRef.current = null
        return
      }

      if (!dragState) return

      const touch = e.touches[0]
      setDragState((prev) =>
        prev
          ? { ...prev, currentX: touch.clientX, currentY: touch.clientY }
          : null,
      )

      const col = getColumnAtPoint(touch.clientX, touch.clientY)
      setHoveredColumn(col)
    },
    [dragState, getColumnAtPoint],
  )

  const handleTouchEnd = useCallback(() => {
    // Clear long-press timer
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }

    if (!dragState) return

    // If dropped on a different column, fire onDrop
    if (hoveredColumn && hoveredColumn !== dragState.fromColumnId) {
      onDrop(dragState.itemId, dragState.fromColumnId, hoveredColumn)
    }

    setDragState(null)
    setHoveredColumn(null)
  }, [dragState, hoveredColumn, onDrop])

  const setColumnRef = useCallback((colId: string, el: HTMLDivElement | null) => {
    if (el) {
      columnRefsMap.current.set(colId, el)
    } else {
      columnRefsMap.current.delete(colId)
    }
  }, [])

  return (
    <div
      className={`flex gap-3 overflow-x-auto pb-4 ${className}`}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      role="group"
      aria-label="Kanban board"
    >
      {columns.map((column) => {
        const columnItems = items.filter((item) => item.columnId === column.id)
        const isDropTarget = hoveredColumn === column.id && dragState?.fromColumnId !== column.id

        return (
          <div
            key={column.id}
            ref={(el) => setColumnRef(column.id, el)}
            className={`flex min-w-[260px] flex-shrink-0 flex-col rounded-lg border transition-colors ${
              isDropTarget
                ? 'border-blue-400 bg-blue-50 dark:border-blue-500 dark:bg-blue-950'
                : 'border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800'
            }`}
            role="region"
            aria-label={`${column.label} column`}
          >
            {/* Column header */}
            <div className="flex items-center gap-2 px-3 py-2">
              {column.color && (
                <div className={`h-2.5 w-2.5 rounded-full ${column.color}`} />
              )}
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                {column.label}
              </h3>
              <span className="ml-auto text-xs text-gray-500 dark:text-gray-400">
                {columnItems.length}
              </span>
            </div>

            {/* Column items */}
            <div className="flex flex-1 flex-col gap-2 px-2 pb-2">
              {columnItems.length === 0 && (
                <div className="py-8 text-center text-xs text-gray-400 dark:text-gray-500">
                  No items
                </div>
              )}
              {columnItems.map((item) => {
                const isDragging = dragState?.itemId === item.id

                return (
                  <div
                    key={item.id}
                    onTouchStart={(e) => handleTouchStart(item.id, column.id, e)}
                    className={`touch-none select-none ${
                      isDragging ? 'opacity-40' : ''
                    }`}
                    role="button"
                    aria-grabbed={isDragging}
                    aria-label={`Drag ${item.id}`}
                    tabIndex={0}
                  >
                    {renderItem(item, isDragging)}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}

      {/* Drag ghost overlay */}
      {dragState && (() => {
        const draggedItem = items.find((i) => i.id === dragState.itemId)
        if (!draggedItem) return null

        return (
          <div
            className="pointer-events-none fixed z-50"
            style={{
              left: dragState.currentX - dragState.offsetX,
              top: dragState.currentY - dragState.offsetY,
              width: 260,
            }}
            aria-hidden="true"
          >
            <div className="rounded-lg shadow-xl ring-2 ring-blue-400 dark:ring-blue-500">
              {renderItem(draggedItem, true)}
            </div>
          </div>
        )
      })()}
    </div>
  )
}
