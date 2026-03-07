import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — Kitchen Display Module — Task 32.12
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

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  url: string
  close = vi.fn()
  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }
}

vi.stubGlobal('WebSocket', MockWebSocket)

import apiClient from '@/api/client'
import KitchenDisplay, { getUrgencyLevel } from '../pages/kitchen/KitchenDisplay'

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
    created_at: new Date(Date.now() - 20 * 60_000).toISOString(), // 20 min ago
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
    created_at: new Date(Date.now() - 35 * 60_000).toISOString(), // 35 min ago
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
/*  Tests                                                              */
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
    // Should fetch station-specific orders
    expect(apiClient.get).toHaveBeenCalledWith('/api/v2/kitchen/stations/grill/orders')
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
    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/kitchen/orders/order-1/prepared')
  })

  it('removes order from display after marking prepared', async () => {
    const user = userEvent.setup()
    render(<KitchenDisplay />)
    expect(await screen.findByText('Cheeseburger')).toBeInTheDocument()
    const buttons = screen.getAllByTestId('mark-prepared-btn')
    await user.click(buttons[0])
    // Order should be removed from the list
    expect(screen.queryByText('Cheeseburger')).not.toBeInTheDocument()
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
})

/* ------------------------------------------------------------------ */
/*  Urgency level unit tests                                           */
/* ------------------------------------------------------------------ */

describe('getUrgencyLevel', () => {
  it('returns normal for orders under 15 minutes', () => {
    const recent = new Date(Date.now() - 5 * 60_000).toISOString()
    expect(getUrgencyLevel(recent)).toBe('normal')
  })

  it('returns warning for orders between 15 and 30 minutes', () => {
    const older = new Date(Date.now() - 20 * 60_000).toISOString()
    expect(getUrgencyLevel(older)).toBe('warning')
  })

  it('returns critical for orders over 30 minutes', () => {
    const old = new Date(Date.now() - 45 * 60_000).toISOString()
    expect(getUrgencyLevel(old)).toBe('critical')
  })
})
