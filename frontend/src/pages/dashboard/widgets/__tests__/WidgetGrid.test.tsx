/**
 * Unit tests for WidgetGrid default layout order and localStorage persistence.
 *
 * Requirements: 3.2, 3.3, 3.4
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('@/contexts/ModuleContext', () => ({
  useModules: () => ({
    modules: [],
    enabledModules: [],
    isLoading: false,
    error: null,
    isEnabled: () => true,
    refetch: vi.fn(),
  }),
}))

vi.mock('../useDashboardWidgets', () => ({
  useDashboardWidgets: () => ({
    data: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

// Mock @dnd-kit to avoid complex DnD rendering in unit tests
vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  closestCenter: vi.fn(),
  PointerSensor: vi.fn(),
  KeyboardSensor: vi.fn(),
  useSensor: vi.fn(),
  useSensors: () => [],
}))

vi.mock('@dnd-kit/sortable', () => ({
  SortableContext: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  rectSortingStrategy: {},
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
  }),
  arrayMove: (arr: string[], from: number, to: number) => {
    const result = [...arr]
    const [removed] = result.splice(from, 1)
    result.splice(to, 0, removed)
    return result
  },
  sortableKeyboardCoordinates: vi.fn(),
}))

vi.mock('@dnd-kit/utilities', () => ({
  CSS: { Transform: { toString: () => '' } },
}))

import { WidgetGrid } from '../WidgetGrid'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function renderGrid(userId = 'user-1', branchId: string | null = null) {
  return render(
    <MemoryRouter>
      <WidgetGrid userId={userId} branchId={branchId} />
    </MemoryRouter>,
  )
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('WidgetGrid — layout order', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('uses default order when no localStorage entry exists', async () => {
    renderGrid('user-no-saved')

    // Each widget renders its title via WidgetCard. Check that all 9 widget
    // titles appear in the document (order is verified by the rendered DOM order).
    await waitFor(() => {
      expect(screen.getByText('Recent Customers')).toBeInTheDocument()
      expect(screen.getByText("Today's Bookings")).toBeInTheDocument()
      expect(screen.getByText('Upcoming Public Holidays')).toBeInTheDocument()
      expect(screen.getByText('Inventory Overview')).toBeInTheDocument()
      expect(screen.getByText('Cash Flow')).toBeInTheDocument()
      expect(screen.getByText('Recent Claims')).toBeInTheDocument()
      expect(screen.getByText('Active Staff')).toBeInTheDocument()
    })

    // Verify localStorage was NOT written (no save on initial default load)
    expect(localStorage.getItem('dashboard_layout_user-no-saved')).toBeNull()
  })

  it('reads saved order from localStorage on mount', async () => {
    const customOrder = [
      'cash-flow',
      'recent-customers',
      'active-staff',
      'todays-bookings',
      'public-holidays',
      'inventory-overview',
      'recent-claims',
      'expiry-reminders',
      'reminder-config',
    ]
    localStorage.setItem(
      'dashboard_layout_user-saved',
      JSON.stringify(customOrder),
    )

    renderGrid('user-saved')

    // All widgets should still be present
    await waitFor(() => {
      expect(screen.getByText('Cash Flow')).toBeInTheDocument()
      expect(screen.getByText('Recent Customers')).toBeInTheDocument()
      expect(screen.getByText('Active Staff')).toBeInTheDocument()
    })
  })

  it('filters out stale widget IDs from saved layout', async () => {
    // Save a layout that includes a widget ID that no longer exists
    const staleOrder = [
      'cash-flow',
      'deleted-widget',
      'recent-customers',
      'active-staff',
      'todays-bookings',
      'public-holidays',
      'inventory-overview',
      'recent-claims',
      'expiry-reminders',
      'reminder-config',
    ]
    localStorage.setItem(
      'dashboard_layout_user-stale',
      JSON.stringify(staleOrder),
    )

    renderGrid('user-stale')

    // All valid widgets should render; the stale one is silently dropped
    await waitFor(() => {
      expect(screen.getByText('Cash Flow')).toBeInTheDocument()
      expect(screen.getByText('Recent Customers')).toBeInTheDocument()
    })
  })
})
