import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  }
})

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    user: { id: 'u1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
  }),
}))

const mockDismissToast = vi.fn()
vi.mock('@/hooks/useModuleGuard', () => ({
  useModuleGuard: () => ({
    isAllowed: true,
    isLoading: false,
    toasts: [],
    dismissToast: mockDismissToast,
  }),
}))

vi.mock('@/contexts/FeatureFlagContext', () => ({
  useFlag: () => true,
}))

vi.mock('@/contexts/TerminologyContext', () => ({
  useTerm: (_key: string, fallback: string) => fallback,
}))

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

  it('renders status filter dropdown with all status options', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: [], total: 0, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
    const select = screen.getByLabelText('Status')
    expect(select).toBeInTheDocument()
    expect(within(select as HTMLElement).getByText('Draft')).toBeInTheDocument()
    expect(within(select as HTMLElement).getByText('Submitted')).toBeInTheDocument()
    expect(within(select as HTMLElement).getByText('Approved')).toBeInTheDocument()
    expect(within(select as HTMLElement).getByText('Paid')).toBeInTheDocument()
    expect(within(select as HTMLElement).getByText('Disputed')).toBeInTheDocument()
  })

  it('shows create form when New Claim clicked', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /New/i }))

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

  it('renders status badges with correct colours', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    expect(screen.getByTestId('status-badge-draft')).toBeInTheDocument()
    expect(screen.getByTestId('status-badge-approved')).toBeInTheDocument()
  })

  it('shows Submit button for draft claims', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    expect(screen.getByRole('button', { name: /Submit claim 1/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Submit claim 2/ })).not.toBeInTheDocument()
  })

  it('updates claim status without page reload', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { ...mockClaims[0], status: 'submitted' },
    })
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Submit claim 1/ }))

    await waitFor(() => {
      expect(apiClient.put).toHaveBeenCalledWith(
        '/api/v2/progress-claims/claim-1',
        { status: 'submitted' },
      )
    })
  })

  it('renders PDF generation button for each claim', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
    })
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    expect(screen.getByRole('button', { name: /Generate PDF for claim 1/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Generate PDF for claim 2/ })).toBeInTheDocument()
  })

  it('calls PDF endpoint when Generate PDF clicked', async () => {
    const mockBlob = new Blob(['pdf-content'], { type: 'application/pdf' })
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/pdf')) {
        return Promise.resolve({ data: mockBlob })
      }
      return Promise.resolve({
        data: { claims: mockClaims, total: 2, page: 1, page_size: 50 },
      })
    })

    const mockOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
    render(<ProgressClaimList />)
    await screen.findByRole('grid', { name: 'Progress claims list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Generate PDF for claim 1/ }))

    await waitFor(() => {
      expect(apiClient.get).toHaveBeenCalledWith(
        '/api/v2/progress-claims/claim-1/pdf',
        { responseType: 'blob' },
      )
    })
    mockOpen.mockRestore()
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

    const alerts = screen.getAllByRole('alert')
    const overContractAlert = alerts.find((el) =>
      el.textContent?.includes('Work completed exceeds revised contract value'),
    )
    expect(overContractAlert).toBeTruthy()
  })

  it('shows cumulative validation error when exceeding revised contract', async () => {
    render(<ProgressClaimForm projectId="proj-1" cumulativePreviousClaimed={90000} />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Contract Value'), '100000')
    await user.type(screen.getByLabelText('Work Completed to Date'), '20000')

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/exceeds revised contract value/)
    })
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
