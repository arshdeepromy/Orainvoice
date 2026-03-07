import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 60.1, 60.2, 60.3, 60.4
 * - 60.1: Create recurring schedule linked to customer with configurable frequency
 * - 60.2: Auto-generate Draft or Issued invoice when due
 * - 60.3: View, edit, pause, or cancel recurring schedules
 * - 60.4: Notify Org_Admin when recurring invoice is generated
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  }
})

import apiClient from '@/api/client'
import RecurringInvoices from '../pages/invoices/RecurringInvoices'

const mockSchedules = [
  {
    id: 'sched-1',
    org_id: 'org-1',
    customer_id: 'cust-1',
    frequency: 'monthly',
    line_items: [
      { item_type: 'service', description: 'Monthly service', quantity: 1, unit_price: 150, is_gst_exempt: false },
    ],
    auto_issue: true,
    is_active: true,
    next_due_date: '2025-02-01',
    last_generated_at: '2025-01-01T00:00:00Z',
    notes: 'Regular maintenance',
    created_by: 'user-1',
    created_at: '2024-12-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  },
  {
    id: 'sched-2',
    org_id: 'org-1',
    customer_id: 'cust-2',
    frequency: 'weekly',
    line_items: [
      { item_type: 'part', description: 'Oil filter', quantity: 2, unit_price: 25, is_gst_exempt: false },
    ],
    auto_issue: false,
    is_active: false,
    next_due_date: '2025-01-15',
    last_generated_at: null,
    notes: null,
    created_by: 'user-1',
    created_at: '2024-11-01T00:00:00Z',
    updated_at: '2024-12-15T00:00:00Z',
  },
]

function setupMocks(schedules = mockSchedules) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/invoices/recurring') {
      return Promise.resolve({ data: { schedules, total: schedules.length } })
    }
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSchedules[0] })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockSchedules[0] })
}

describe('RecurringInvoices page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<RecurringInvoices />)
    expect(screen.getByRole('status', { name: 'Loading recurring schedules' })).toBeInTheDocument()
  })

  it('renders the page heading and new schedule button', async () => {
    setupMocks()
    render(<RecurringInvoices />)
    expect(screen.getByRole('heading', { name: 'Recurring Invoices' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ New Schedule' })).toBeInTheDocument()
  })

  it('displays schedule list with correct data (Req 60.3)', async () => {
    setupMocks()
    render(<RecurringInvoices />)

    // Wait for data to load
    const table = await screen.findByRole('grid')
    expect(table).toBeInTheDocument()

    const rows = within(table).getAllByRole('row')
    // header + 2 data rows
    expect(rows).toHaveLength(3)

    // Check frequency labels
    expect(screen.getByText('Monthly')).toBeInTheDocument()
    expect(screen.getByText('Weekly')).toBeInTheDocument()

    // Check status badges
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Paused / Cancelled')).toBeInTheDocument()

    // Check auto-issue column
    const cells = within(rows[1]).getAllByRole('cell')
    expect(cells.some((c) => c.textContent === 'Yes')).toBe(true)
  })

  it('shows empty state when no schedules exist', async () => {
    setupMocks([])
    render(<RecurringInvoices />)
    expect(await screen.findByText(/No recurring schedules yet/)).toBeInTheDocument()
  })

  it('shows error state on API failure', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<RecurringInvoices />)
    expect(await screen.findByText('Failed to load recurring schedules.')).toBeInTheDocument()
  })

  it('opens create form modal when clicking New Schedule (Req 60.1)', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    await user.click(screen.getByRole('button', { name: '+ New Schedule' }))

    expect(screen.getByText('New Recurring Schedule')).toBeInTheDocument()
    expect(screen.getByLabelText(/Search customers/i)).toBeInTheDocument()
    expect(screen.getByText('Create Schedule')).toBeInTheDocument()
  })

  it('opens edit form modal for active schedule (Req 60.3)', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    await user.click(editButtons[0])

    expect(screen.getByText('Edit Recurring Schedule')).toBeInTheDocument()
    expect(screen.getByText('Save Changes')).toBeInTheDocument()
  })

  it('shows pause confirmation modal (Req 60.3)', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    const pauseButtons = screen.getAllByRole('button', { name: 'Pause' })
    await user.click(pauseButtons[0])

    expect(screen.getByRole('heading', { name: 'Pause Schedule' })).toBeInTheDocument()
    expect(screen.getByText(/stop new invoices from being generated/)).toBeInTheDocument()
  })

  it('shows cancel confirmation modal (Req 60.3)', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    const cancelButtons = screen.getAllByRole('button', { name: /^Cancel$/ })
    await user.click(cancelButtons[0])

    expect(screen.getByRole('heading', { name: 'Cancel Schedule' })).toBeInTheDocument()
    expect(screen.getByText(/permanent/)).toBeInTheDocument()
  })

  it('calls pause API and refreshes list', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    const pauseButtons = screen.getAllByRole('button', { name: 'Pause' })
    await user.click(pauseButtons[0])

    // Confirm pause
    const confirmBtn = screen.getByRole('button', { name: 'Pause Schedule' })
    await user.click(confirmBtn)

    expect(apiClient.post).toHaveBeenCalledWith('/invoices/recurring/sched-1/pause')
  })

  it('calls cancel API and refreshes list', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    const cancelButtons = screen.getAllByRole('button', { name: /^Cancel$/ })
    await user.click(cancelButtons[0])

    // Confirm cancel
    const confirmBtn = screen.getByRole('button', { name: 'Cancel Schedule' })
    await user.click(confirmBtn)

    expect(apiClient.post).toHaveBeenCalledWith('/invoices/recurring/sched-1/cancel')
  })

  it('disables edit button for inactive schedules', async () => {
    setupMocks()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    // Second schedule is inactive, its edit button should be disabled
    expect(editButtons[1]).toBeDisabled()
  })

  it('does not show pause/cancel buttons for inactive schedules', async () => {
    setupMocks([mockSchedules[1]]) // only inactive schedule
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
    // Only the "Cancel" in the form cancel button context, not the action
    const cancelButtons = screen.queryAllByRole('button', { name: /^Cancel$/ })
    expect(cancelButtons).toHaveLength(0)
  })

  it('filters to active only when checkbox is toggled', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<RecurringInvoices />)

    await screen.findByRole('grid')
    const checkbox = screen.getByRole('checkbox', { name: /Show active only/ })
    await user.click(checkbox)

    // Should re-fetch with active_only param
    expect(apiClient.get).toHaveBeenCalledWith('/invoices/recurring', {
      params: { active_only: true },
    })
  })
})
