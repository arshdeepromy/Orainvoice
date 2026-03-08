import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
 */

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPut = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, put: mockPut, post: mockPost },
  }
})

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: 'u1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
  }),
}))

vi.mock('@/contexts/TerminologyContext', () => ({
  useTerm: (_key: string, fallback: string) => fallback,
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFlag: () => true,
}))

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  url: string
  close = vi.fn()
  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    // Simulate successful connection
    setTimeout(() => this.onopen?.(), 0)
  }
}

vi.stubGlobal('WebSocket', MockWebSocket)

import apiClient from '@/api/client'
import KitchenDisplay, {
  getUrgencyLevel,
  getBackoffDelay,
  filterByStation,
} from '../pages/kitchen/KitchenDisplay'
import type { KitchenOrderItem } from '../pages/kitchen/KitchenDisplay'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockOrders = [
  {
    id: 'order-1',
    org_id: 'org-1',
    pos_transaction_id: 'txn-1',
    table_id: 'tbl-1',
    item_name: 'Cheeseburger',
    quantity: 2,
    modifications: 'No onions',
    station: 'grill',
    status: 'pending',
    created_at: new Date().toISOString(),
    prepared_at: null,
  },
  {
    id: 'order-2',
    org_id: 'org-1',
    pos_transaction_id: 'txn-1',
    table_id: 'tbl-1',
    item_name: 'Caesar Salad',
    quantity: 1,
    modifications: null,
    station: 'cold',
    status: 'pending',
    created_at: new Date(Date.now() - 20 * 60_000).toISOString(),
    prepared_at: null,
  },
  {
    id: 'order-3',
    org_id: 'org-1',
    pos_transaction_id: 'txn-2',
    table_id: null,
    item_name: 'Fish & Chips',
    quantity: 1,
    modifications: 'Extra tartar',
    station: 'fry',
    status: 'preparing',
    created_at: new Date(Date.now() - 35 * 60_000).toISOString(),
    prepared_at: null,
  },
]

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  MockWebSocket.instances = []
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
    data: { orders: mockOrders, total: mockOrders.length },
  })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
})

/* ------------------------------------------------------------------ */
/*  Component Tests                                                    */
/* ------------------------------------------------------------------ */

describe('KitchenDisplay', () => {
  it('renders kitchen display container', async () => {
    render(<KitchenDisplay />)
    expect(await screen.findByTestId('kitchen-display')).toBeInTheDocument()
  })

  it('renders order cards with item names', async () => {
    render(<KitchenDisplay />)
    expect(await screen.findByText('Cheeseburger')).toBeInTheDocument()
    expect(screen.getByText('Caesar Salad')).toBeInTheDocument()
    expect(screen.getByText('Fish & Chips')).toBeInTheDocument()
  })

  it('displays quantity for each order', async () => {
    render(<KitchenDisplay />)
    expect(await screen.findByText('×2')).toBeInTheDocument()
  })

  it('displays modifications when present', async () => {
    render(<KitchenDisplay />)
    expect(await screen.findByText('No onions')).toBeInTheDocument()
    expect(screen.getByText('Extra tartar')).toBeInTheDocument()
  })

  it('renders station filter tabs', async () => {
    render(<KitchenDisplay />)
    expect(await screen.findByRole('tab', { name: /all/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /main/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /grill/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /fry/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /cold/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /bar/i })).toBeInTheDocument()
  })

  it('switches station filter on tab click', async () => {
    const user = userEvent.setup()
    render(<KitchenDisplay />)
    const grillTab = await screen.findByRole('tab', { name: /grill/i })
    await user.click(grillTab)
    expect(grillTab).toHaveAttribute('aria-selected', 'true')
    expect(apiClient.get).toHaveBeenCalledWith('/api/v2/kitchen/orders?station=grill')
  })

  it('renders tick-off buttons for each order', async () => {
    render(<KitchenDisplay />)
    const buttons = await screen.findAllByTestId('mark-prepared-btn')
    expect(buttons).toHaveLength(3)
  })

  it('calls API to mark item prepared on tick-off click', async () => {
    const user = userEvent.setup()
    render(<KitchenDisplay />)
    const buttons = await screen.findAllByTestId('mark-prepared-btn')
    await user.click(buttons[0])
    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/kitchen/orders/order-1/status', { status: 'ready' })
  })

  it('moves order to ready column after marking prepared', async () => {
    const user = userEvent.setup()
    render(<KitchenDisplay />)
    expect(await screen.findByText('Cheeseburger')).toBeInTheDocument()
    const buttons = screen.getAllByTestId('mark-prepared-btn')
    await user.click(buttons[0])
    // Order should now be in the ready column
    const readyCards = screen.getAllByTestId('kitchen-ready-card')
    expect(readyCards.length).toBeGreaterThanOrEqual(1)
  })

  it('shows empty state when no orders', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { orders: [], total: 0 },
    })
    render(<KitchenDisplay />)
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
    expect(screen.getByText('No pending orders')).toBeInTheDocument()
  })

  it('establishes WebSocket connection', async () => {
    render(<KitchenDisplay />)
    await screen.findByTestId('kitchen-display')
    expect(MockWebSocket.instances.length).toBeGreaterThan(0)
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    expect(ws.url).toContain('/ws/kitchen/')
  })

  it('renders full-screen toggle button', async () => {
    render(<KitchenDisplay />)
    expect(await screen.findByTestId('fullscreen-toggle')).toBeInTheDocument()
  })

  it('toggles full-screen mode on button click', async () => {
    const user = userEvent.setup()
    render(<KitchenDisplay />)
    const btn = await screen.findByTestId('fullscreen-toggle')
    expect(btn).toHaveTextContent('Full Screen')
    await user.click(btn)
    expect(btn).toHaveTextContent('Exit')
  })

  it('shows connection lost banner when WebSocket disconnects', async () => {
    render(<KitchenDisplay />)
    await screen.findByTestId('kitchen-display')
    // Simulate WebSocket close
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    ws.onclose?.()
    expect(await screen.findByTestId('connection-lost-banner')).toBeInTheDocument()
  })

  it('renders Pending and Ready column headers', async () => {
    render(<KitchenDisplay />)
    await screen.findByTestId('kitchen-display')
    expect(screen.getByText(/Pending/)).toBeInTheDocument()
    expect(screen.getByText(/Ready/)).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  Pure utility function tests                                        */
/* ------------------------------------------------------------------ */

describe('getUrgencyLevel', () => {
  it('returns normal for orders under threshold', () => {
    const recent = new Date(Date.now() - 5 * 60_000).toISOString()
    expect(getUrgencyLevel(recent)).toBe('normal')
  })

  it('returns warning for orders between threshold and 2x threshold', () => {
    const older = new Date(Date.now() - 20 * 60_000).toISOString()
    expect(getUrgencyLevel(older)).toBe('warning')
  })

  it('returns critical for orders over 2x threshold', () => {
    const old = new Date(Date.now() - 45 * 60_000).toISOString()
    expect(getUrgencyLevel(old)).toBe('critical')
  })

  it('respects custom threshold', () => {
    const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString()
    expect(getUrgencyLevel(tenMinAgo, 5)).toBe('critical') // 10 >= 2*5
    expect(getUrgencyLevel(tenMinAgo, 8)).toBe('warning')  // 8 <= 10 < 16
    expect(getUrgencyLevel(tenMinAgo, 15)).toBe('normal')  // 10 < 15
  })
})

describe('getBackoffDelay', () => {
  it('returns 1000ms for attempt 0', () => {
    expect(getBackoffDelay(0)).toBe(1000)
  })

  it('returns 2000ms for attempt 1', () => {
    expect(getBackoffDelay(1)).toBe(2000)
  })

  it('returns 4000ms for attempt 2', () => {
    expect(getBackoffDelay(2)).toBe(4000)
  })

  it('returns 8000ms for attempt 3', () => {
    expect(getBackoffDelay(3)).toBe(8000)
  })

  it('returns 16000ms for attempt 4', () => {
    expect(getBackoffDelay(4)).toBe(16000)
  })

  it('caps at 30000ms for attempt 5+', () => {
    expect(getBackoffDelay(5)).toBe(30000)
    expect(getBackoffDelay(6)).toBe(30000)
    expect(getBackoffDelay(10)).toBe(30000)
  })
})

describe('filterByStation', () => {
  const orders: KitchenOrderItem[] = [
    {
      id: '1', org_id: 'o', pos_transaction_id: null, table_id: null,
      item_name: 'A', quantity: 1, modifications: null, station: 'grill',
      status: 'pending', created_at: '', prepared_at: null,
    },
    {
      id: '2', org_id: 'o', pos_transaction_id: null, table_id: null,
      item_name: 'B', quantity: 1, modifications: null, station: 'cold',
      status: 'pending', created_at: '', prepared_at: null,
    },
    {
      id: '3', org_id: 'o', pos_transaction_id: null, table_id: null,
      item_name: 'C', quantity: 1, modifications: null, station: 'grill',
      status: 'pending', created_at: '', prepared_at: null,
    },
  ]

  it('returns all orders when station is "all"', () => {
    expect(filterByStation(orders, 'all')).toHaveLength(3)
  })

  it('returns only matching orders for a specific station', () => {
    const result = filterByStation(orders, 'grill')
    expect(result).toHaveLength(2)
    expect(result.every((o) => o.station === 'grill')).toBe(true)
  })

  it('returns empty array when no orders match station', () => {
    expect(filterByStation(orders, 'bar')).toHaveLength(0)
  })

  it('returns empty array for empty input', () => {
    expect(filterByStation([], 'grill')).toHaveLength(0)
  })
})
