import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 14.1 (Project Module)
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
import ProjectList from '../pages/projects/ProjectList'
import ProjectDashboard from '../pages/projects/ProjectDashboard'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockProjects = [
  {
    id: 'proj-1', name: 'Office Renovation',
    status: 'active', customer_id: 'cust-1',
    contract_value: '50000.00', budget_amount: '40000.00',
    start_date: '2024-06-01', target_end_date: '2024-12-31',
    retention_percentage: '5.00', created_at: '2024-05-30T10:00:00Z',
  },
  {
    id: 'proj-2', name: 'Kitchen Remodel',
    status: 'completed', customer_id: 'cust-2',
    contract_value: '25000.00', budget_amount: null,
    start_date: null, target_end_date: null,
    retention_percentage: '0', created_at: '2024-04-15T10:00:00Z',
  },
]

const mockProfitability = {
  project_id: 'proj-1',
  revenue: 30000,
  expense_costs: 5000,
  labour_costs: 8000,
  total_costs: 13000,
  profit: 17000,
  margin_percentage: 56.7,
}

const mockProgress = {
  project_id: 'proj-1',
  contract_value: 50000,
  invoiced_amount: 20000,
  progress_percentage: 40.0,
}

const mockActivity = {
  project_id: 'proj-1',
  items: [
    {
      entity_type: 'job', entity_id: 'job-1',
      title: 'JOB-00001: Install wiring', status: 'in_progress',
      created_at: '2024-06-15T10:00:00Z',
    },
    {
      entity_type: 'quote', entity_id: 'quote-1',
      title: 'Quote Q-001', status: 'accepted',
      created_at: '2024-06-10T10:00:00Z',
    },
    {
      entity_type: 'time_entry', entity_id: 'te-1',
      title: 'Electrical work (2.0h)', status: 'recorded',
      created_at: '2024-06-14T10:00:00Z',
    },
  ],
  total: 3,
}

/* ------------------------------------------------------------------ */
/*  ProjectList tests                                                  */
/* ------------------------------------------------------------------ */

describe('ProjectList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ProjectList />)
    expect(screen.getByRole('status', { name: 'Loading projects' })).toBeInTheDocument()
  })

  it('displays projects in a table with key columns', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { projects: mockProjects, total: 2, page: 1, page_size: 20 },
    })
    render(<ProjectList />)
    const table = await screen.findByRole('grid', { name: 'Projects list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
    expect(screen.getByText('Office Renovation')).toBeInTheDocument()
    expect(screen.getByText('Kitchen Remodel')).toBeInTheDocument()
  })

  it('renders search and status filter', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { projects: [], total: 0, page: 1, page_size: 20 },
    })
    render(<ProjectList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Search projects')).toBeInTheDocument()
    expect(screen.getByLabelText('Status')).toBeInTheDocument()
  })

  it('shows empty state when no projects', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { projects: [], total: 0, page: 1, page_size: 20 },
    })
    render(<ProjectList />)
    expect(await screen.findByText(/No projects found/)).toBeInTheDocument()
  })

  it('displays contract value formatted as currency', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { projects: mockProjects, total: 2, page: 1, page_size: 20 },
    })
    render(<ProjectList />)
    await screen.findByRole('grid', { name: 'Projects list' })
    expect(screen.getByText('$50,000')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  ProjectDashboard tests                                             */
/* ------------------------------------------------------------------ */

describe('ProjectDashboard', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ProjectDashboard projectId="proj-1" />)
    expect(screen.getByRole('status', { name: 'Loading project' })).toBeInTheDocument()
  })

  it('renders project name and status', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/profitability')) return Promise.resolve({ data: mockProfitability })
      if (url.includes('/progress')) return Promise.resolve({ data: mockProgress })
      if (url.includes('/activity')) return Promise.resolve({ data: mockActivity })
      return Promise.resolve({ data: mockProjects[0] })
    })
    render(<ProjectDashboard projectId="proj-1" />)
    expect(await screen.findByRole('heading', { name: 'Office Renovation' })).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('shows progress bar with correct percentage', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/profitability')) return Promise.resolve({ data: mockProfitability })
      if (url.includes('/progress')) return Promise.resolve({ data: mockProgress })
      if (url.includes('/activity')) return Promise.resolve({ data: mockActivity })
      return Promise.resolve({ data: mockProjects[0] })
    })
    render(<ProjectDashboard projectId="proj-1" />)
    const progressBar = await screen.findByRole('progressbar', { name: 'Project completion' })
    expect(progressBar).toHaveAttribute('aria-valuenow', '40')
    expect(screen.getByText(/40\.0% complete/)).toBeInTheDocument()
  })

  it('shows profitability breakdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/profitability')) return Promise.resolve({ data: mockProfitability })
      if (url.includes('/progress')) return Promise.resolve({ data: mockProgress })
      if (url.includes('/activity')) return Promise.resolve({ data: mockActivity })
      return Promise.resolve({ data: mockProjects[0] })
    })
    render(<ProjectDashboard projectId="proj-1" />)
    await screen.findByRole('heading', { name: 'Office Renovation' })

    const profSection = screen.getByRole('table', { name: 'Profitability breakdown' })
    expect(within(profSection).getByText('Revenue')).toBeInTheDocument()
    expect(within(profSection).getByText('Labour Costs')).toBeInTheDocument()
    expect(within(profSection).getByText('Expense Costs')).toBeInTheDocument()
    expect(within(profSection).getByText('Profit')).toBeInTheDocument()
    expect(within(profSection).getByText('Margin')).toBeInTheDocument()
    expect(within(profSection).getByText('56.7%')).toBeInTheDocument()
  })

  it('shows activity feed with linked entities', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/profitability')) return Promise.resolve({ data: mockProfitability })
      if (url.includes('/progress')) return Promise.resolve({ data: mockProgress })
      if (url.includes('/activity')) return Promise.resolve({ data: mockActivity })
      return Promise.resolve({ data: mockProjects[0] })
    })
    render(<ProjectDashboard projectId="proj-1" />)
    await screen.findByRole('heading', { name: 'Office Renovation' })

    const activityList = screen.getByRole('list', { name: 'Activity feed' })
    expect(within(activityList).getByText(/JOB-00001/)).toBeInTheDocument()
    expect(within(activityList).getByText(/Quote Q-001/)).toBeInTheDocument()
    expect(within(activityList).getByText(/Electrical work/)).toBeInTheDocument()
  })

  it('renders entity tabs for jobs, quotes, time entries', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/profitability')) return Promise.resolve({ data: mockProfitability })
      if (url.includes('/progress')) return Promise.resolve({ data: mockProgress })
      if (url.includes('/activity')) return Promise.resolve({ data: mockActivity })
      return Promise.resolve({ data: mockProjects[0] })
    })
    render(<ProjectDashboard projectId="proj-1" />)
    await screen.findByRole('heading', { name: 'Office Renovation' })

    expect(screen.getByRole('tab', { name: 'Activity' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Jobs' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Quotes' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Time Entries' })).toBeInTheDocument()
  })

  it('switches to Jobs tab and shows linked jobs', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/profitability')) return Promise.resolve({ data: mockProfitability })
      if (url.includes('/progress')) return Promise.resolve({ data: mockProgress })
      if (url.includes('/activity')) return Promise.resolve({ data: mockActivity })
      return Promise.resolve({ data: mockProjects[0] })
    })
    render(<ProjectDashboard projectId="proj-1" />)
    await screen.findByRole('heading', { name: 'Office Renovation' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Jobs' }))

    const jobsList = screen.getByRole('list', { name: 'Linked jobs' })
    expect(within(jobsList).getByText(/JOB-00001/)).toBeInTheDocument()
  })

  it('shows project details section', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/profitability')) return Promise.resolve({ data: mockProfitability })
      if (url.includes('/progress')) return Promise.resolve({ data: mockProgress })
      if (url.includes('/activity')) return Promise.resolve({ data: mockActivity })
      return Promise.resolve({ data: mockProjects[0] })
    })
    render(<ProjectDashboard projectId="proj-1" />)
    await screen.findByRole('heading', { name: 'Office Renovation' })

    expect(screen.getByText('Contract Value')).toBeInTheDocument()
    expect(screen.getByText('Budget')).toBeInTheDocument()
    expect(screen.getByText('5.00%')).toBeInTheDocument()
  })
})
