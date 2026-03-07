import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement — ProgressClaim Module
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
import ProgressClaimList from '../pages/construction/ProgressClaimList'
import ProgressClaimForm from '../pages/construction/ProgressClaimForm'

const mockClaims = [
  {
    id: 'claim-1', project_id: 'proj-1', claim_number: 1,
    contract_value: '100000.00', variations_to_date: '5000.00',
    revised_contract_value: '105000.00',
    work_completed_to_date: '30000.00', work_completed_previous: '10000.00',
    work_completed_this_period: '20000.00', materials_on_site: '2000.00',
    retention_withheld: '1000.00', amount_due: '21000.00',
    completion_percentage: '28.57', status: 'draft',
    created_at: '2024-06-15T10:00:00Z',
  },
  {
    id: 'claim-2', project_id: 'proj-1', claim_number: 2,
    contract_value: '100000.00', variations_to_date: '5000.00',
    revised_contract_value: '105000.00',
    work_completed_to_date: '60000.00', work_completed_previous: '30000.00',
    work_completed_this_period: '30000.00', materials_on_site: '0',
    retention_withheld: '1500.00', amount_due: '28500.00',
    completion_percentage: '57.14', status: 'approved',
    created_at: '2024-07-15T10:00:00Z',
  },
]

describe('ProgressClaimList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<ProgressClaimList />)
    expect(screen.getByRole('status', { name: 'Loading claims' })).toBeInTheDocument()
  })

  it('displays claims in a table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    const table = await screen.findByRole('grid', { name: 'Progress claims list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 data rows
  })

  it('shows empty state when no claims', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: [], total: 0, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    expect(await screen.findByText(/No progress claims found/)).toBeInTheDocument()
  })

  it('renders status filter dropdown', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: [], total: 0, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    expect(screen.getByLabelText('Status')).toBeInTheDocument()
  })

  it('shows create form when New Claim clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'New claim' }))

    expect(screen.getByRole('form', { name: 'Create progress claim' })).toBeInTheDocument()
  })

  it('filters by status when dropdown changes', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Status'), 'approved')

    await waitFor(() => {
      const calls = (apiClient.get as ReturnType<typeof vi.fn>).mock.calls
      const lastCall = calls[calls.length - 1][0] as string
      expect(lastCall).toContain('status=approved')
    })
  })
})

describe('ProgressClaimForm', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('renders all input fields', () => {
    render(<ProgressClaimForm projectId="proj-1" />)
    expect(screen.getByLabelText('Contract Value')).toBeInTheDocument()
    expect(screen.getByLabelText('Variations to Date')).toBeInTheDocument()
    expect(screen.getByLabelText('Work Completed to Date')).toBeInTheDocument()
    expect(screen.getByLabelText('Work Completed Previous')).toBeInTheDocument()
    expect(screen.getByLabelText('Materials on Site')).toBeInTheDocument()
    expect(screen.getByLabelText('Retention Withheld')).toBeInTheDocument()
  })

  it('auto-calculates derived fields', async () => {
    render(<ProgressClaimForm projectId="proj-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Contract Value'), '100000')
    await user.clear(screen.getByLabelText('Variations to Date'))
    await user.type(screen.getByLabelText('Variations to Date'), '5000')
    await user.type(screen.getByLabelText('Work Completed to Date'), '30000')

    expect(screen.getByTestId('revised-contract')).toHaveTextContent('$105,000')
  })

  it('shows validation error when work exceeds contract', async () => {
    render(<ProgressClaimForm projectId="proj-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Contract Value'), '100000')
    await user.type(screen.getByLabelText('Work Completed to Date'), '200000')

    expect(screen.getByRole('alert')).toHaveTextContent('Work completed exceeds revised contract value')
  })

  it('submits form with correct data', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new-claim' } })
    render(<ProgressClaimForm projectId="proj-1" />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Contract Value'), '100000')
    await user.type(screen.getByLabelText('Work Completed to Date'), '30000')

    await user.click(screen.getByRole('button', { name: 'Save Claim' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/progress-claims', expect.objectContaining({
      project_id: 'proj-1',
      contract_value: 100000,
      work_completed_to_date: 30000,
    }))
  })
})
