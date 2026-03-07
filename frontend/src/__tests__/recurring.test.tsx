import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Recurring Module — Task 34.9
 */

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()
const mockDelete = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
  },
}))

import RecurringList from '../pages/recurring/RecurringList'

/* ------------------------------------------------------------------ */
/*  Fixtures                                                           */
/* ------------------------------------------------------------------ */

const SCHEDULE_1 = {
  id: '11111111-1111-1111-1111-111111111111',
  org_id: 'org-1',
  customer_id: 'cust-1',
  line_items: [{ description: 'Hosting', quantity: '1', unit_price: '50.00' }],
  frequency: 'monthly',
  start_date: '2025-01-01',
  end_date: null,
  next_generation_date: '2025-02-01',
  auto_issue: true,
  auto_email: false,
  status: 'active',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const SCHEDULE_2 = {
  ...SCHEDULE_1,
  id: '22222222-2222-2222-2222-222222222222',
  customer_id: 'cust-2',
  frequency: 'weekly',
  status: 'paused',
  next_generation_date: '2025-01-15',
}

const DASHBOARD = {
  active_count: 3,
  paused_count: 1,
  due_today: 2,
  due_this_week: 5,
}

/* ------------------------------------------------------------------ */
/*  Setup                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/dashboard')) {
      return Promise.resolve({ data: DASHBOARD })
    }
    return Promise.resolve({
      data: { schedules: [SCHEDULE_1, SCHEDULE_2], total: 2 },
    })
  })
  mockPost.mockResolvedValue({ data: SCHEDULE_1 })
  mockPut.mockResolvedValue({ data: SCHEDULE_1 })
  mockDelete.mockResolvedValue({})
})

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('RecurringList', () => {
  it('renders the page heading', async () => {
    render(<RecurringList />)
    expect(screen.getByText('Recurring Invoices')).toBeInTheDocument()
  })

  it('displays the dashboard summary', async () => {
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId('dashboard-active')).toHaveTextContent('Active: 3')
    })
    expect(screen.getByTestId('dashboard-paused')).toHaveTextContent('Paused: 1')
    expect(screen.getByTestId('dashboard-due-today')).toHaveTextContent('Due today: 2')
    expect(screen.getByTestId('dashboard-due-week')).toHaveTextContent('Due this week: 5')
  })

  it('renders schedule rows with correct data', async () => {
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId(`schedule-row-${SCHEDULE_1.id}`)).toBeInTheDocument()
    })
    const row1 = screen.getByTestId(`schedule-row-${SCHEDULE_1.id}`)
    expect(within(row1).getByTestId('schedule-frequency')).toHaveTextContent('Monthly')
    expect(within(row1).getByTestId('schedule-next-date')).toHaveTextContent('2025-02-01')
    expect(within(row1).getByTestId('schedule-status')).toHaveTextContent('active')
    expect(within(row1).getByTestId('schedule-auto-issue')).toHaveTextContent('Yes')
  })

  it('shows empty state when no schedules', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/dashboard')) {
        return Promise.resolve({ data: DASHBOARD })
      }
      return Promise.resolve({ data: { schedules: [], total: 0 } })
    })
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId('empty-state')).toHaveTextContent('No recurring schedules found')
    })
  })

  it('opens create form when New Schedule button is clicked', async () => {
    const user = userEvent.setup()
    render(<RecurringList />)
    await user.click(screen.getByTestId('create-schedule-btn'))
    expect(screen.getByTestId('create-schedule-dialog')).toBeInTheDocument()
  })

  it('submits create form and refreshes list', async () => {
    const user = userEvent.setup()
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId('schedules-table')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('create-schedule-btn'))

    await user.type(screen.getByTestId('input-customer-id'), 'cust-new')
    await user.type(screen.getByTestId('input-start-date'), '2025-03-01')
    await user.type(screen.getByTestId('input-description'), 'Monthly service')
    await user.type(screen.getByTestId('input-unit-price'), '100')

    await user.click(screen.getByTestId('submit-create'))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/api/v2/recurring/', expect.objectContaining({
        customer_id: 'cust-new',
        frequency: 'monthly',
      }))
    })
  })

  it('cancels a schedule via delete button', async () => {
    const user = userEvent.setup()
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId(`cancel-btn-${SCHEDULE_1.id}`)).toBeInTheDocument()
    })
    await user.click(screen.getByTestId(`cancel-btn-${SCHEDULE_1.id}`))
    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith(`/api/v2/recurring/${SCHEDULE_1.id}`)
    })
  })

  it('pauses an active schedule', async () => {
    const user = userEvent.setup()
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId(`pause-btn-${SCHEDULE_1.id}`)).toBeInTheDocument()
    })
    await user.click(screen.getByTestId(`pause-btn-${SCHEDULE_1.id}`))
    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        `/api/v2/recurring/${SCHEDULE_1.id}`,
        { status: 'paused' },
      )
    })
  })

  it('resumes a paused schedule', async () => {
    const user = userEvent.setup()
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId(`pause-btn-${SCHEDULE_2.id}`)).toBeInTheDocument()
    })
    // SCHEDULE_2 is paused, so button should say "Resume"
    expect(screen.getByTestId(`pause-btn-${SCHEDULE_2.id}`)).toHaveTextContent('Resume')
    await user.click(screen.getByTestId(`pause-btn-${SCHEDULE_2.id}`))
    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith(
        `/api/v2/recurring/${SCHEDULE_2.id}`,
        { status: 'active' },
      )
    })
  })

  it('closes create form when cancel button is clicked', async () => {
    const user = userEvent.setup()
    render(<RecurringList />)
    await user.click(screen.getByTestId('create-schedule-btn'))
    expect(screen.getByTestId('create-schedule-dialog')).toBeInTheDocument()
    await user.click(screen.getByTestId('cancel-create'))
    expect(screen.queryByTestId('create-schedule-dialog')).not.toBeInTheDocument()
  })

  it('displays error message on fetch failure', async () => {
    mockGet.mockRejectedValue(new Error('Network error'))
    render(<RecurringList />)
    await waitFor(() => {
      expect(screen.getByTestId('error-message')).toHaveTextContent('Failed to load recurring schedules')
    })
  })
})
