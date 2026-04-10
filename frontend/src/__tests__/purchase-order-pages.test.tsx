import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 16 — Purchase Order Module
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
  }
})

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'po-1' }),
  useNavigate: () => vi.fn(),
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

import apiClient from '@/api/client'
import POList from '../pages/purchase-orders/POList'
import PODetail from '../pages/purchase-orders/PODetail'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockPOs = [
  {
    id: 'po-1', org_id: 'org-1', po_number: 'PO-00001',
    supplier_id: 'sup-1', status: 'sent',
    expected_delivery: '2024-07-15', total_amount: '500.00',
    notes: null, created_at: '2024-06-15T10:00:00Z',
    updated_at: '2024-06-15T10:00:00Z',
    lines: [],
  },
  {
    id: 'po-2', org_id: 'org-1', po_number: 'PO-00002',
    supplier_id: 'sup-2', status: 'draft',
    expected_delivery: null, total_amount: '250.00',
    notes: 'Urgent order', created_at: '2024-06-16T10:00:00Z',
    updated_at: '2024-06-16T10:00:00Z',
    lines: [],
  },
]

const mockPODetail = {
  id: 'po-1', org_id: 'org-1', po_number: 'PO-00001',
  supplier_id: 'sup-1', status: 'sent',
  expected_delivery: '2024-07-15', total_amount: '500.00',
  notes: 'Test notes', created_at: '2024-06-15T10:00:00Z',
  updated_at: '2024-06-15T10:00:00Z',
  lines: [
    {
      id: 'line-1', product_id: 'prod-1', description: 'Widget A',
      quantity_ordered: '20', quantity_received: '5',
      unit_cost: '25.00', line_total: '500.00',
    },
  ],
}

/* ------------------------------------------------------------------ */
/*  POList tests                                                       */
/* ------------------------------------------------------------------ */

describe('POList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<POList />)
    expect(screen.getByRole('status', { name: 'Loading purchase orders' })).toBeInTheDocument()
  })

  it('displays purchase orders in a table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { purchase_orders: mockPOs, total: 2, page: 1, page_size: 20 },
    })
    render(<POList />)
    const table = await screen.findByRole('grid', { name: 'Purchase orders list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
    expect(screen.getByText('PO-00001')).toBeInTheDocument()
    expect(screen.getByText('PO-00002')).toBeInTheDocument()
  })

  it('renders status filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { purchase_orders: [], total: 0, page: 1, page_size: 20 },
    })
    render(<POList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Status')).toBeInTheDocument()
  })

  it('renders supplier filter input', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { purchase_orders: [], total: 0, page: 1, page_size: 20 },
    })
    render(<POList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Supplier ID')).toBeInTheDocument()
  })

  it('shows empty state when no POs', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { purchase_orders: [], total: 0, page: 1, page_size: 20 },
    })
    render(<POList />)
    expect(await screen.findByText(/No purchase orders found/)).toBeInTheDocument()
  })

  it('filters by status when dropdown changes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { purchase_orders: mockPOs, total: 2, page: 1, page_size: 20 },
    })
    render(<POList />)
    await screen.findByRole('grid', { name: 'Purchase orders list' })

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Status'), 'sent')

    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
      const lastCall = calls[calls.length - 1][0] as string
      expect(lastCall).toContain('status=sent')
    })
  })

  it('has create purchase order button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { purchase_orders: [], total: 0, page: 1, page_size: 20 },
    })
    render(<POList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: 'Create purchase order' })).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  PODetail tests                                                     */
/* ------------------------------------------------------------------ */

describe('PODetail', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<PODetail />)
    expect(screen.getByRole('status', { name: 'Loading purchase order' })).toBeInTheDocument()
  })

  it('displays PO details and line items', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockPODetail })
    render(<PODetail />)

    expect(await screen.findByText('PO-00001')).toBeInTheDocument()
    expect(screen.getByTestId('po-status')).toHaveTextContent('sent')
    expect(screen.getByText('Test notes')).toBeInTheDocument()

    const lineTable = screen.getByRole('grid', { name: 'PO line items' })
    const rows = within(lineTable).getAllByRole('row')
    expect(rows).toHaveLength(2) // header + 1 line
    expect(screen.getByText('Widget A')).toBeInTheDocument()
  })

  it('shows receive goods button for sent PO', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockPODetail })
    render(<PODetail />)
    expect(await screen.findByRole('button', { name: 'Receive goods' })).toBeInTheDocument()
  })

  it('shows send button for draft PO', async () => {
    const draftPO = { ...mockPODetail, status: 'draft' }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: draftPO })
    render(<PODetail />)
    expect(await screen.findByRole('button', { name: 'Send to supplier' })).toBeInTheDocument()
  })

  it('shows download PDF button', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockPODetail })
    render(<PODetail />)
    expect(await screen.findByRole('button', { name: 'Download PDF' })).toBeInTheDocument()
  })

  it('opens receive goods form with quantity inputs', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockPODetail })
    render(<PODetail />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Receive goods' }))

    expect(screen.getByRole('form', { name: 'Receive goods' })).toBeInTheDocument()
    expect(screen.getByLabelText('Receive quantity for line 1')).toBeInTheDocument()
  })

  it('submits receive goods form', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockPODetail })
    const receivedPO = {
      ...mockPODetail,
      status: 'partial',
      lines: [{ ...mockPODetail.lines[0], quantity_received: '10' }],
    }
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: receivedPO })

    render(<PODetail />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Receive goods' }))

    const qtyInput = screen.getByLabelText('Receive quantity for line 1')
    await user.clear(qtyInput)
    await user.type(qtyInput, '5')

    await user.click(screen.getByRole('button', { name: 'Confirm Receive' }))

    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/v2/purchase-orders/po-1/receive',
      expect.objectContaining({
        lines: expect.arrayContaining([
          expect.objectContaining({ line_id: 'line-1', quantity: 5 }),
        ]),
      }),
    )
  })

  it('displays outstanding quantities in line items', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockPODetail })
    render(<PODetail />)

    await screen.findByText('PO-00001')
    // Outstanding = 20 - 5 = 15
    expect(screen.getByText('15')).toBeInTheDocument()
  })

  it('sends PO to supplier', async () => {
    const draftPO = { ...mockPODetail, status: 'draft' }
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: draftPO })
    const sentPO = { ...mockPODetail, status: 'sent' }
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: sentPO })

    render(<PODetail />)

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Send to supplier' }))

    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/purchase-orders/po-1/send')
  })
})
