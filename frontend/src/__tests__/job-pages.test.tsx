import { render, screen, within, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 11.1, 11.2, 11.4, 11.5, 11.6
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
import JobBoard from '../pages/jobs/JobBoard'
import JobDetail from '../pages/jobs/JobDetail'
import JobList from '../pages/jobs/JobList'

/* ------------------------------------------------------------------ */
/*  Mock data                                                          */
/* ------------------------------------------------------------------ */

const mockJobs = [
  {
    id: 'job-1', job_number: 'JOB-00001', title: 'Fix leaking tap',
    status: 'draft', priority: 'normal', customer_id: 'cust-1',
    scheduled_start: '2024-06-01T09:00:00Z', scheduled_end: null,
    created_at: '2024-05-30T10:00:00Z', staff_assignments: [],
  },
  {
    id: 'job-2', job_number: 'JOB-00002', title: 'Install new boiler',
    status: 'in_progress', priority: 'high', customer_id: 'cust-2',
    scheduled_start: null, scheduled_end: null,
    created_at: '2024-05-29T10:00:00Z', staff_assignments: [],
  },
  {
    id: 'job-3', job_number: 'JOB-00003', title: 'Bathroom renovation',
    status: 'completed', priority: 'normal', customer_id: 'cust-1',
    scheduled_start: null, scheduled_end: null,
    created_at: '2024-05-28T10:00:00Z', converted_invoice_id: null,
    staff_assignments: [],
  },
]

const mockAttachments = [
  {
    id: 'att-1', file_name: 'photo.jpg', file_size: 1048576,
    content_type: 'image/jpeg', uploaded_at: '2024-06-01T10:00:00Z',
  },
]

const mockHistory = [
  {
    id: 'hist-1', from_status: null, to_status: 'draft',
    changed_at: '2024-05-30T10:00:00Z', notes: null,
  },
  {
    id: 'hist-2', from_status: 'draft', to_status: 'scheduled',
    changed_at: '2024-05-31T10:00:00Z', notes: 'Scheduled for Monday',
  },
]

/* ------------------------------------------------------------------ */
/*  JobBoard tests                                                     */
/* ------------------------------------------------------------------ */

describe('JobBoard', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<JobBoard />)
    expect(screen.getByRole('status', { name: 'Loading jobs' })).toBeInTheDocument()
  })

  it('renders kanban columns for all statuses (Req 11.4)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { jobs: mockJobs, total: 3, page: 1, page_size: 200 },
    })
    render(<JobBoard />)
    await screen.findByRole('grid', { name: 'Job board' })

    expect(screen.getByRole('group', { name: 'Draft column' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Scheduled column' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'In Progress column' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'On Hold column' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Completed column' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Invoiced column' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Cancelled column' })).toBeInTheDocument()
  })

  it('displays jobs in correct status columns', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { jobs: mockJobs, total: 3, page: 1, page_size: 200 },
    })
    render(<JobBoard />)
    await screen.findByRole('grid', { name: 'Job board' })

    const draftCol = screen.getByRole('group', { name: 'Draft column' })
    expect(within(draftCol).getByText('JOB-00001')).toBeInTheDocument()
    expect(within(draftCol).getByText('Fix leaking tap')).toBeInTheDocument()

    const inProgressCol = screen.getByRole('group', { name: 'In Progress column' })
    expect(within(inProgressCol).getByText('JOB-00002')).toBeInTheDocument()
  })

  it('shows job count per column', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { jobs: mockJobs, total: 3, page: 1, page_size: 200 },
    })
    render(<JobBoard />)
    await screen.findByRole('grid', { name: 'Job board' })

    const draftCol = screen.getByRole('group', { name: 'Draft column' })
    expect(within(draftCol).getByText('(1)')).toBeInTheDocument()
  })

  it('shows high priority badge', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { jobs: mockJobs, total: 3, page: 1, page_size: 200 },
    })
    render(<JobBoard />)
    await screen.findByRole('grid', { name: 'Job board' })
    expect(screen.getByText('high')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  JobDetail tests                                                    */
/* ------------------------------------------------------------------ */

describe('JobDetail', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner when loading job', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<JobDetail jobId="job-1" />)
    expect(screen.getByRole('status', { name: 'Loading job' })).toBeInTheDocument()
  })

  it('renders create form when no jobId', () => {
    render(<JobDetail />)
    expect(screen.getByRole('heading', { name: 'New Job' })).toBeInTheDocument()
    expect(screen.getByLabelText('Job title *')).toBeInTheDocument()
    expect(screen.getByLabelText('Description')).toBeInTheDocument()
    expect(screen.getByLabelText('Priority')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Job' })).toBeInTheDocument()
  })

  it('validates required title on create', async () => {
    render(<JobDetail />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Create Job' }))
    expect(await screen.findByText('Job title is required.')).toBeInTheDocument()
  })

  it('renders tabs for existing job (Req 11.1)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/history')) return Promise.resolve({ data: mockHistory })
      if (url.includes('/attachments')) return Promise.resolve({ data: mockAttachments })
      return Promise.resolve({ data: { ...mockJobs[0], checklist: [{ text: 'Check pipes', completed: false }] } })
    })
    render(<JobDetail jobId="job-1" />)
    await screen.findByRole('heading', { name: /JOB-00001/ })

    expect(screen.getByRole('tab', { name: 'Details' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Checklist' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Attachments' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Timeline' })).toBeInTheDocument()
  })

  it('shows checklist items when Checklist tab is clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/history')) return Promise.resolve({ data: [] })
      if (url.includes('/attachments')) return Promise.resolve({ data: [] })
      return Promise.resolve({ data: { ...mockJobs[0], checklist: [{ text: 'Check pipes', completed: false }] } })
    })
    render(<JobDetail jobId="job-1" />)
    await screen.findByRole('heading', { name: /JOB-00001/ })

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Checklist' }))
    expect(screen.getByText('Check pipes')).toBeInTheDocument()
  })

  it('shows attachments with file size', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/history')) return Promise.resolve({ data: [] })
      if (url.includes('/attachments')) return Promise.resolve({ data: mockAttachments })
      return Promise.resolve({ data: mockJobs[0] })
    })
    render(<JobDetail jobId="job-1" />)
    await screen.findByRole('heading', { name: /JOB-00001/ })

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Attachments' }))
    expect(screen.getByText(/photo\.jpg/)).toBeInTheDocument()
    expect(screen.getByText(/1024\.0 KB/)).toBeInTheDocument()
  })

  it('shows convert-to-invoice button for completed jobs (Req 11.6)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/history')) return Promise.resolve({ data: [] })
      if (url.includes('/attachments')) return Promise.resolve({ data: [] })
      return Promise.resolve({ data: mockJobs[2] }) // completed job
    })
    render(<JobDetail jobId="job-3" />)
    await screen.findByRole('heading', { name: /JOB-00003/ })
    expect(screen.getByRole('button', { name: 'Convert to invoice' })).toBeInTheDocument()
  })

  it('shows file upload input on Attachments tab (Req 11.5)', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/history')) return Promise.resolve({ data: [] })
      if (url.includes('/attachments')) return Promise.resolve({ data: [] })
      return Promise.resolve({ data: mockJobs[0] })
    })
    render(<JobDetail jobId="job-1" />)
    await screen.findByRole('heading', { name: /JOB-00001/ })

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Attachments' }))
    expect(screen.getByLabelText('Upload file')).toBeInTheDocument()
  })
})

/* ------------------------------------------------------------------ */
/*  JobList tests                                                      */
/* ------------------------------------------------------------------ */

describe('JobList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<JobList />)
    expect(screen.getByRole('status', { name: 'Loading jobs' })).toBeInTheDocument()
  })

  it('displays jobs in a table with key columns', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { jobs: mockJobs, total: 3, page: 1, page_size: 20 },
    })
    render(<JobList />)
    const table = await screen.findByRole('grid', { name: 'Jobs list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4) // header + 3 data rows
    expect(screen.getByText('JOB-00001')).toBeInTheDocument()
    expect(screen.getByText('Fix leaking tap')).toBeInTheDocument()
  })

  it('renders search and status filter', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { jobs: [], total: 0, page: 1, page_size: 20 },
    })
    render(<JobList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Search jobs')).toBeInTheDocument()
    expect(screen.getByLabelText('Status')).toBeInTheDocument()
  })

  it('shows empty state when no jobs', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { jobs: [], total: 0, page: 1, page_size: 20 },
    })
    render(<JobList />)
    expect(await screen.findByText(/No jobs found/)).toBeInTheDocument()
  })
})
