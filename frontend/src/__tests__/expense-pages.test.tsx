import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — Expense Module
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

import apiClient from '@/api/client'
import ExpenseList from '../pages/expenses/ExpenseList'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockExpenses = [
  {
    id: 'exp-1', org_id: 'org-1', job_id: 'job-1', project_id: null,
    invoice_id: null, date: '2024-06-15', description: 'Pipe fittings',
    amount: '125.50', tax_amount: '18.83', category: 'materials',
    receipt_file_key: 'receipts/abc123.pdf', is_pass_through: true,
    is_invoiced: false, created_at: '2024-06-15T10:00:00Z',
  },
  {
    id: 'exp-2', org_id: 'org-1', job_id: null, project_id: 'proj-1',
    invoice_id: null, date: '2024-06-16', description: 'Travel to site',
    amount: '45.00', tax_amount: '0', category: 'travel',
    receipt_file_key: null, is_pass_through: false,
    is_invoiced: false, created_at: '2024-06-16T10:00:00Z',
  },
]

/* ------------------------------------------------------------------ */
/*  ExpenseList tests                                                  */
/* ------------------------------------------------------------------ */

describe('ExpenseList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ExpenseList />)
    expect(screen.getByRole('status', { name: 'Loading expenses' })).toBeInTheDocument()
  })

  it('displays expenses in a table with key columns', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: mockExpenses, total: 2, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    const table = await screen.findByRole('grid', { name: 'Expenses list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
    expect(screen.getByText('Pipe fittings')).toBeInTheDocument()
    expect(screen.getByText('Travel to site')).toBeInTheDocument()
  })

  it('renders category filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: [], total: 0, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Category')).toBeInTheDocument()
  })

  it('renders date range filters', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: [], total: 0, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('From')).toBeInTheDocument()
    expect(screen.getByLabelText('To')).toBeInTheDocument()
  })

  it('shows empty state when no expenses', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: [], total: 0, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    expect(await screen.findByText(/No expenses found/)).toBeInTheDocument()
  })

  it('shows create expense form when Add button clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: mockExpenses, total: 2, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await screen.findByRole('grid', { name: 'Expenses list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add expense' }))

    expect(screen.getByRole('form', { name: 'Create expense' })).toBeInTheDocument()
    expect(screen.getByLabelText('Description')).toBeInTheDocument()
    expect(screen.getByLabelText('Amount')).toBeInTheDocument()
  })

  it('submits create expense form', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: [], total: 0, page: 1, page_size: 20 },
    })
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: 'exp-new', description: 'New expense' },
    })
    render(<ExpenseList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add expense' }))

    await user.type(screen.getByLabelText('Description'), 'Office supplies')
    await user.type(screen.getByLabelText('Amount'), '42.50')

    await user.click(screen.getByRole('button', { name: 'Save Expense' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/expenses', expect.objectContaining({
      description: 'Office supplies',
      amount: 42.50,
    }))
  })

  it('shows receipt upload input in create form', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: [], total: 0, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add expense' }))

    expect(screen.getByLabelText('Receipt')).toBeInTheDocument()
  })

  it('displays receipt link when receipt_file_key exists', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: mockExpenses, total: 2, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await screen.findByRole('grid', { name: 'Expenses list' })

    // First expense has a receipt, second doesn't
    const viewLinks = screen.getAllByText('View')
    expect(viewLinks.length).toBeGreaterThanOrEqual(1)
  })

  it('shows pass-through status in table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: mockExpenses, total: 2, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await screen.findByRole('grid', { name: 'Expenses list' })

    // First expense is pass-through (Yes), second is not (No)
    const yesCells = screen.getAllByText('Yes')
    const noCells = screen.getAllByText('No')
    expect(yesCells.length).toBeGreaterThanOrEqual(1)
    expect(noCells.length).toBeGreaterThanOrEqual(1)
  })

  it('filters by category when dropdown changes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: mockExpenses, total: 2, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await screen.findByRole('grid', { name: 'Expenses list' })

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Category'), 'materials')

    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
      const lastCall = calls[calls.length - 1][0] as string
      expect(lastCall).toContain('category=materials')
    })
  })

  it('shows job and project links', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { expenses: mockExpenses, total: 2, page: 1, page_size: 20 },
    })
    render(<ExpenseList />)
    await screen.findByRole('grid', { name: 'Expenses list' })

    expect(screen.getByText('View Job')).toBeInTheDocument()
    expect(screen.getByText('View Project')).toBeInTheDocument()
  })
})
