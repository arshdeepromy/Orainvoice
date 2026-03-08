import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
 */

/* ── Mocks ── */

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return { default: { get: mockGet, post: mockPost, put: mockPut } }
})

vi.mock('@/hooks/useModuleGuard', () => ({
  useModuleGuard: () => ({
    isAllowed: true,
    isLoading: false,
    toasts: [],
    dismissToast: vi.fn(),
  }),
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFlag: () => true,
}))

vi.mock('@/contexts/TerminologyContext', () => ({
  useTerm: (_key: string, fallback: string) => fallback,
}))

import apiClient from '@/api/client'
import FloorPlan from '../pages/floor-plan/FloorPlan'
import ReservationList from '../pages/floor-plan/ReservationList'

/* ── Mock data ── */

const mockFloorPlan = {
  id: 'fp-1',
  org_id: 'org-1',
  name: 'Main Floor',
  width: 800,
  height: 600,
  is_active: true,
  created_at: '2025-01-15T00:00:00Z',
}

const mockTables = [
  {
    id: 'tbl-1', org_id: 'org-1', table_number: 'T1', seat_count: 4,
    position_x: 50, position_y: 50, width: 100, height: 100,
    status: 'available', merged_with_id: null, floor_plan_id: 'fp-1',
    created_at: '2025-01-15T00:00:00Z',
  },
  {
    id: 'tbl-2', org_id: 'org-1', table_number: 'T2', seat_count: 6,
    position_x: 200, position_y: 50, width: 120, height: 100,
    status: 'occupied', merged_with_id: null, floor_plan_id: 'fp-1',
    created_at: '2025-01-15T00:00:00Z',
  },
  {
    id: 'tbl-3', org_id: 'org-1', table_number: 'T3', seat_count: 2,
    position_x: 400, position_y: 50, width: 80, height: 80,
    status: 'needs_cleaning', merged_with_id: null, floor_plan_id: 'fp-1',
    created_at: '2025-01-15T00:00:00Z',
  },
]

const mockReservations = [
  {
    id: 'res-1', org_id: 'org-1', table_id: 'tbl-1',
    customer_name: 'Alice Smith', party_size: 4,
    reservation_date: '2025-07-01', reservation_time: '19:00',
    duration_minutes: 90, notes: null, status: 'confirmed',
    created_at: '2025-01-15T00:00:00Z',
  },
]

const mockFloorPlanState = {
  floor_plan: mockFloorPlan,
  tables: mockTables,
  reservations: mockReservations,
}

const mockFloorPlanList = { floor_plans: [mockFloorPlan], total: 1 }
const mockReservationList = { reservations: mockReservations, total: 1 }
const mockTableList = { tables: mockTables, total: 3 }

/* ── FloorPlan tests ── */

describe('FloorPlan', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function mockFloorPlanApi() {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/floor-plans/') && url.includes('/state')) {
        return Promise.resolve({ data: mockFloorPlanState })
      }
      if (url.includes('/floor-plans')) {
        return Promise.resolve({ data: mockFloorPlanList })
      }
      return Promise.resolve({ data: {} })
    })
  }

  it('renders page heading with terminology', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    expect(await screen.findByTestId('floor-plan-heading')).toHaveTextContent('Table Floor Plan')
  })

  it('shows loading state', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<FloorPlan />)
    expect(screen.getByRole('status', { name: 'Loading floor plan' })).toBeInTheDocument()
  })

  it('displays tables with correct status colours via data-testid', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    const t1 = await screen.findByRole('button', { name: /Table T1 - Available/ })
    expect(t1).toBeInTheDocument()
    const t2 = screen.getByRole('button', { name: /Table T2 - Occupied/ })
    expect(t2).toBeInTheDocument()
    const t3 = screen.getByRole('button', { name: /Table T3 - Needs Cleaning/ })
    expect(t3).toBeInTheDocument()
  })

  it('shows reservation customer name on table', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    const names = await screen.findAllByText('Alice Smith')
    // Appears on the table card and in the reservation timeline
    expect(names.length).toBeGreaterThanOrEqual(1)
  })

  it('shows status legend', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    const legend = screen.getByRole('list', { name: 'Status legend' })
    expect(within(legend).getByText('Available')).toBeInTheDocument()
    expect(within(legend).getByText('Occupied')).toBeInTheDocument()
    expect(within(legend).getByText('Needs Cleaning')).toBeInTheDocument()
    expect(within(legend).getByText('Reserved')).toBeInTheDocument()
  })

  it('has edit layout toggle button', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    expect(screen.getByTestId('edit-layout-btn')).toBeInTheDocument()
  })

  it('toggles edit mode and shows toolbar', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    const user = userEvent.setup()
    await user.click(screen.getByTestId('edit-layout-btn'))
    expect(screen.getByText('Done Editing')).toBeInTheDocument()
    expect(screen.getByTestId('edit-toolbar')).toBeInTheDocument()
    expect(screen.getByTestId('add-table-btn')).toBeInTheDocument()
  })

  it('shows quick action buttons for tables', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    expect(screen.getByText('Seat Guests')).toBeInTheDocument()
    expect(screen.getByText('Mark Paid')).toBeInTheDocument()
    expect(screen.getByText('Mark Clean')).toBeInTheDocument()
  })

  it('calls API on status change', async () => {
    mockFloorPlanApi()
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    const user = userEvent.setup()
    await user.click(screen.getByText('Seat Guests'))
    expect(apiClient.put).toHaveBeenCalledWith(
      '/api/v2/tables/tables/tbl-1/status',
      { status: 'occupied' },
    )
  })

  it('shows error on API failure', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network'))
    render(<FloorPlan />)
    expect(await screen.findByText('Failed to load floor plans.')).toBeInTheDocument()
  })

  it('navigates to POS on table tap (Req 14.3)', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    const user = userEvent.setup()
    const t1 = await screen.findByRole('button', { name: /Table T1/ })
    await user.click(t1)
    expect(mockNavigate).toHaveBeenCalledWith('/pos?table=tbl-1')
  })

  it('calls onTableTap prop when provided', async () => {
    const onTap = vi.fn()
    mockFloorPlanApi()
    render(<FloorPlan onTableTap={onTap} />)
    const user = userEvent.setup()
    const t1 = await screen.findByRole('button', { name: /Table T1/ })
    await user.click(t1)
    expect(onTap).toHaveBeenCalledWith('tbl-1')
  })

  it('has zoom controls', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    expect(screen.getByTestId('zoom-in-btn')).toBeInTheDocument()
    expect(screen.getByTestId('zoom-out-btn')).toBeInTheDocument()
    expect(screen.getByTestId('zoom-level')).toHaveTextContent('100%')
  })

  it('shows reservation timeline', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    expect(screen.getByTestId('reservation-timeline')).toBeInTheDocument()
    expect(screen.getByText('Upcoming Reservations')).toBeInTheDocument()
  })

  it('shows new table form in edit mode', async () => {
    mockFloorPlanApi()
    render(<FloorPlan />)
    await screen.findByRole('button', { name: /Table T1/ })
    const user = userEvent.setup()
    await user.click(screen.getByTestId('edit-layout-btn'))
    await user.click(screen.getByTestId('add-table-btn'))
    expect(screen.getByTestId('new-table-form')).toBeInTheDocument()
    expect(screen.getByTestId('new-table-number-input')).toBeInTheDocument()
    expect(screen.getByTestId('new-table-label-input')).toBeInTheDocument()
  })
})

/* ── ReservationList tests ── */

describe('ReservationList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function mockReservationApi() {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/reservations')) {
        return Promise.resolve({ data: mockReservationList })
      }
      if (url.includes('/tables')) {
        return Promise.resolve({ data: mockTableList })
      }
      return Promise.resolve({ data: {} })
    })
  }

  it('renders page heading', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { reservations: [], total: 0 } })
      .mockResolvedValueOnce({ data: mockTableList })
    render(<ReservationList />)
    expect(screen.getByTestId('reservations-heading')).toHaveTextContent('Reservations')
  })

  it('shows loading state', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ReservationList />)
    expect(screen.getByRole('status', { name: 'Loading reservations' })).toBeInTheDocument()
  })

  it('shows empty state when no reservations', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { reservations: [], total: 0 } })
      .mockResolvedValueOnce({ data: mockTableList })
    render(<ReservationList />)
    expect(await screen.findByText('No reservations found for this date.')).toBeInTheDocument()
  })

  it('displays reservations in table', async () => {
    mockReservationApi()
    render(<ReservationList />)
    expect(await screen.findByText('Alice Smith')).toBeInTheDocument()
    expect(screen.getByText('19:00')).toBeInTheDocument()
    expect(screen.getByText('90 min')).toBeInTheDocument()
  })

  it('has date and status filters', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { reservations: [], total: 0 } })
      .mockResolvedValueOnce({ data: mockTableList })
    render(<ReservationList />)
    expect(screen.getByLabelText('Filter by date')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by status')).toBeInTheDocument()
  })

  it('has new reservation button that shows form', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { reservations: [], total: 0 } })
      .mockResolvedValueOnce({ data: mockTableList })
    render(<ReservationList />)
    await screen.findByText('No reservations found for this date.')
    const user = userEvent.setup()
    await user.click(screen.getByTestId('new-reservation-btn'))
    expect(screen.getByLabelText('Customer Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Table')).toBeInTheDocument()
    expect(screen.getByLabelText('Party Size')).toBeInTheDocument()
  })

  it('shows cancel button for confirmed reservations', async () => {
    mockReservationApi()
    render(<ReservationList />)
    await screen.findByText('Alice Smith')
    expect(screen.getByText('Cancel')).toBeInTheDocument()
  })

  it('shows error on API failure', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network'))
    render(<ReservationList />)
    expect(await screen.findByText('Failed to load reservations.')).toBeInTheDocument()
  })

  it('has list/calendar view toggle', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ data: { reservations: [], total: 0 } })
      .mockResolvedValueOnce({ data: mockTableList })
    render(<ReservationList />)
    await screen.findByText('No reservations found for this date.')
    expect(screen.getByTestId('view-list-btn')).toBeInTheDocument()
    expect(screen.getByTestId('view-calendar-btn')).toBeInTheDocument()
  })

  it('switches to calendar view', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/reservations')) {
        return Promise.resolve({ data: { reservations: mockReservations, total: 1 } })
      }
      if (url.includes('/tables')) {
        return Promise.resolve({ data: mockTableList })
      }
      return Promise.resolve({ data: {} })
    })
    render(<ReservationList />)
    await screen.findByText('Alice Smith')
    const user = userEvent.setup()
    await user.click(screen.getByTestId('view-calendar-btn'))
    await waitFor(() => {
      expect(screen.getByTestId('calendar-view')).toBeInTheDocument()
    })
    expect(screen.getByTestId('calendar-prev')).toBeInTheDocument()
    expect(screen.getByTestId('calendar-next')).toBeInTheDocument()
    expect(screen.getByTestId('calendar-month-label')).toBeInTheDocument()
  })

  it('uses terminology for table column header', async () => {
    mockReservationApi()
    render(<ReservationList />)
    await screen.findByText('Alice Smith')
    // The table header should use the term fallback "Table"
    const headers = screen.getAllByRole('columnheader')
    const tableHeader = headers.find((h) => h.textContent === 'Table')
    expect(tableHeader).toBeInTheDocument()
  })
})
