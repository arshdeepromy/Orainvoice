/**
 * Widget Grid — draggable, module-gated dashboard widget container.
 *
 * Manages widget layout ordering, localStorage persistence, module
 * gating, and drag-and-drop reordering via @dnd-kit.
 *
 * Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3,
 *               3.4, 3.5, 3.6, 13.1, 13.2, 13.3, 13.4
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import {
  SortableContext,
  rectSortingStrategy,
  useSortable,
  arrayMove,
  sortableKeyboardCoordinates,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useModules } from '@/contexts/ModuleContext'
import { useDashboardWidgets } from './useDashboardWidgets'
import { RecentCustomersWidget } from './RecentCustomersWidget'
import { TodaysBookingsWidget } from './TodaysBookingsWidget'
import { PublicHolidaysWidget } from './PublicHolidaysWidget'
import { InventoryOverviewWidget } from './InventoryOverviewWidget'
import { CashFlowChartWidget } from './CashFlowChartWidget'
import { RecentClaimsWidget } from './RecentClaimsWidget'
import { ActiveStaffWidget } from './ActiveStaffWidget'
import { ExpiryRemindersWidget } from './ExpiryRemindersWidget'
import { ReminderConfigWidget } from './ReminderConfigWidget'
import type { DashboardWidgetData } from './types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface WidgetGridProps {
  userId: string
  branchId: string | null
}

// ---------------------------------------------------------------------------
// Widget definitions
// ---------------------------------------------------------------------------

interface WidgetDef {
  id: string
  title: string
  module?: string
  defaultOrder: number
}

const WIDGET_DEFINITIONS: WidgetDef[] = [
  { id: 'recent-customers', title: 'Recent Customers', defaultOrder: 1 },
  { id: 'todays-bookings', title: "Today's Bookings", module: 'bookings', defaultOrder: 2 },
  { id: 'public-holidays', title: 'Upcoming Public Holidays', defaultOrder: 3 },
  { id: 'inventory-overview', title: 'Inventory Overview', module: 'inventory', defaultOrder: 4 },
  { id: 'cash-flow', title: 'Cash Flow', defaultOrder: 5 },
  { id: 'recent-claims', title: 'Recent Claims', module: 'claims', defaultOrder: 6 },
  { id: 'active-staff', title: 'Active Staff', defaultOrder: 7 },
  { id: 'expiry-reminders', title: 'WOF / Service Expiry Reminders', module: 'vehicles', defaultOrder: 8 },
  { id: 'reminder-config', title: 'Reminder Configuration', module: 'vehicles', defaultOrder: 9 },
]

// ---------------------------------------------------------------------------
// Layout persistence helpers (exported for property tests)
// ---------------------------------------------------------------------------

export function saveLayout(userId: string, order: string[]): void {
  try {
    localStorage.setItem(`dashboard_layout_${userId}`, JSON.stringify(order))
  } catch {
    // Private browsing or quota exceeded — silently ignore
  }
}

export function loadLayout(userId: string): string[] | null {
  try {
    const raw = localStorage.getItem(`dashboard_layout_${userId}`)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.every((v) => typeof v === 'string')) {
      return parsed as string[]
    }
    return null
  } catch {
    return null
  }
}

/**
 * Given a saved layout order and the set of currently available widget IDs,
 * return a filtered order that:
 *   (a) contains only IDs present in `availableIds`
 *   (b) preserves the relative order from `savedOrder`
 *   (c) appends any new available IDs not in `savedOrder` at the end
 */
export function filterStaleWidgets(
  savedOrder: string[],
  availableIds: string[],
): string[] {
  const availableSet = new Set(availableIds)
  const kept = savedOrder.filter((id) => availableSet.has(id))
  const keptSet = new Set(kept)
  const newIds = availableIds.filter((id) => !keptSet.has(id))
  return [...kept, ...newIds]
}

// ---------------------------------------------------------------------------
// Widget renderer — maps widget ID to its component
// ---------------------------------------------------------------------------

function renderWidget(
  id: string,
  data: DashboardWidgetData | null,
  isLoading: boolean,
  error: string | null,
  _branchId: string | null,
) {
  switch (id) {
    case 'recent-customers':
      return (
        <RecentCustomersWidget
          data={data?.recent_customers}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'todays-bookings':
      return (
        <TodaysBookingsWidget
          data={data?.todays_bookings}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'public-holidays':
      return (
        <PublicHolidaysWidget
          data={data?.public_holidays}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'inventory-overview':
      return (
        <InventoryOverviewWidget
          data={data?.inventory_overview}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'cash-flow':
      return (
        <CashFlowChartWidget
          data={data?.cash_flow}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'recent-claims':
      return (
        <RecentClaimsWidget
          data={data?.recent_claims}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'active-staff':
      return (
        <ActiveStaffWidget
          data={data?.active_staff}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'expiry-reminders':
      return (
        <ExpiryRemindersWidget
          data={data?.expiry_reminders}
          isLoading={isLoading}
          error={error}
        />
      )
    case 'reminder-config':
      return (
        <ReminderConfigWidget
          data={data?.reminder_config}
          isLoading={isLoading}
          error={error}
        />
      )
    default:
      return null
  }
}

// ---------------------------------------------------------------------------
// SortableWidget wrapper
// ---------------------------------------------------------------------------

interface SortableWidgetProps {
  id: string
  children: React.ReactNode
}

function SortableWidget({ id, children }: SortableWidgetProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
  } = useSortable({ id })

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition: transition ?? undefined,
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// WidgetGrid component
// ---------------------------------------------------------------------------

export function WidgetGrid({ userId, branchId }: WidgetGridProps) {
  const { isEnabled } = useModules()
  const { data, isLoading, error } = useDashboardWidgets()

  // Determine which widgets are available based on module gating
  const availableWidgets = useMemo(() => {
    return WIDGET_DEFINITIONS
      .filter((w) => !w.module || isEnabled(w.module))
      .sort((a, b) => a.defaultOrder - b.defaultOrder)
  }, [isEnabled])

  const availableIds = useMemo(
    () => availableWidgets.map((w) => w.id),
    [availableWidgets],
  )

  // Layout state
  const [orderedIds, setOrderedIds] = useState<string[]>([])

  // Initialise layout from localStorage or defaults
  useEffect(() => {
    const saved = loadLayout(userId)
    if (saved) {
      setOrderedIds(filterStaleWidgets(saved, availableIds))
    } else {
      setOrderedIds(availableIds)
    }
  }, [userId, availableIds])

  // Sensors for drag-and-drop
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  )

  // Handle drag end — reorder and persist
  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event
      if (!over || active.id === over.id) return

      setOrderedIds((prev) => {
        const oldIndex = prev.indexOf(String(active.id))
        const newIndex = prev.indexOf(String(over.id))
        if (oldIndex === -1 || newIndex === -1) return prev

        const next = arrayMove(prev, oldIndex, newIndex)
        saveLayout(userId, next)
        return next
      })
    },
    [userId],
  )

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={orderedIds} strategy={rectSortingStrategy}>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {orderedIds.map((id) => (
            <SortableWidget key={id} id={id}>
              {renderWidget(id, data, isLoading, error, branchId)}
            </SortableWidget>
          ))}
        </div>
      </SortableContext>
    </DndContext>
  )
}
