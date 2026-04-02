/**
 * Unit tests for ClaimDetail component.
 *
 * Requirements: 2.1-2.7, 3.1-3.8, 7.1-7.5
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'claim-test-123' }),
  useNavigate: () => mockNavigate,
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

vi.mock('../../../components/claims/ClaimResolveModal', () => ({
  ClaimResolveModal: (props: Record<string, unknown>) =>
    props.open ? (
      <div data-testid="resolve-modal">
        <button onClick={() => (props.onSubmit as Function)({ resolution_type: 'full_refund' })}>
          Submit Resolve
        </button>
      </div>
    ) : null,
}))

vi.mock('../../../components/claims/ClaimNoteModal', () => ({
  ClaimNoteModal: (props: Record<string, unknown>) =>
    props.open ? (
      <div data-testid="note-modal">
        <button onClick={() => (props.onSubmit as Function)('Test note')}>
          Submit Note
        </button>
      </div>
    ) : null,
}))

import apiClient from '../../../api/client'
import ClaimDetail from '../ClaimDetail'

function createMockClaim(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'claim-test-123',
    org_id: 'org-1',
    branch_id: null,
    customer_id: 'cust-1',
    customer: {
      id: 'cust-1',
      first_name: 'John',
      last_name: 'Doe',
      email: 'john@example.com',
      phone: null,
      company_name: null,
    },
    invoice_id: 'inv-1',
    invoice: {
      id: 'inv-1',
      invoice_number: 'INV-001',
      total: 500,
      status: 'paid',
    },
    job_card_id: null,
    job_card: null,
    line_item_ids: [],
    claim_type: 'warranty',
    status: 'open',
    description: 'Product stopped working after 2 weeks.',
    resolution_type: null,
    resolution_amount: null,
    resolution_notes: null,
    resolved_at: null,
    resolved_by: null,
    refund_id: null,
    credit_note_id: null,
    return_movement_ids: [],
    warranty_job_id: null,
    cost_to_business: 0,
    cost_breakdown: { labour_cost: 0, parts_cost: 0, write_off_cost: 0 },
    created_by: 'user-1',
    created_at: '2025-03-15T10:00:00Z',
    updated_at: '2025-03-15T10:00:00Z',
    actions: [
      {
        id: 'action-1',
        action_type: 'status_change',
        from_status: null,
        to_status: 'open',
        action_data: {},
        notes: null,
        performed_by: 'user-1',
        performed_by_name: 'Admin User',
        performed_at: '2025-03-15T10:00:00Z',
      },
    ],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  HTMLDialogElement.prototype.showModal = vi.fn()
  HTMLDialogElement.prototype.close = vi.fn()
  vi.mocked(apiClient.get).mockResolvedValue({ data: createMockClaim() })
})

describe('ClaimDetail', () => {
  it('renders claim header with status badge and customer info', async () => {
    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Claim')).toBeInTheDocument()
    })

    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText(/John Doe/)).toBeInTheDocument()
    expect(screen.getByText('Warranty')).toBeInTheDocument()
  })

  it('renders description section', async () => {
    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Product stopped working after 2 weeks.')).toBeInTheDocument()
    })
  })

  it('renders original transaction with invoice link', async () => {
    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })
  })

  it('renders timeline actions', async () => {
    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText(/Admin User/)).toBeInTheDocument()
    })
  })

  it('shows Start Investigation button when status is open', async () => {
    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Start Investigation')).toBeInTheDocument()
    })
  })

  it('shows Approve and Reject buttons when status is investigating', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: createMockClaim({ status: 'investigating' }),
    })

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Approve')).toBeInTheDocument()
      expect(screen.getByText('Reject')).toBeInTheDocument()
    })
  })

  it('shows Resolve button when status is approved', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: createMockClaim({ status: 'approved' }),
    })

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Resolve')).toBeInTheDocument()
    })
  })

  it('hides action buttons when status is resolved', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: createMockClaim({ status: 'resolved', resolution_type: 'full_refund' }),
    })

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Claim')).toBeInTheDocument()
    })

    expect(screen.queryByText('Start Investigation')).not.toBeInTheDocument()
    expect(screen.queryByText('Approve')).not.toBeInTheDocument()
    expect(screen.queryByText('Reject')).not.toBeInTheDocument()
    expect(screen.queryByText('Add Note')).not.toBeInTheDocument()
  })

  it('calls status update API when Start Investigation clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.patch).mockResolvedValue({ data: createMockClaim({ status: 'investigating' }) })

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Start Investigation')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Start Investigation'))

    await waitFor(() => {
      expect(apiClient.patch).toHaveBeenCalledWith(
        '/claims/claim-test-123/status',
        { new_status: 'investigating', notes: undefined },
      )
    })
  })

  it('opens resolve modal when Resolve button clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.get).mockResolvedValue({
      data: createMockClaim({ status: 'approved' }),
    })

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Resolve')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Resolve'))

    await waitFor(() => {
      expect(screen.getByTestId('resolve-modal')).toBeInTheDocument()
    })
  })

  it('opens note modal when Add Note button clicked', async () => {
    const user = userEvent.setup()
    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Add Note')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Add Note'))

    await waitFor(() => {
      expect(screen.getByTestId('note-modal')).toBeInTheDocument()
    })
  })

  it('renders resolution section when claim is resolved', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: createMockClaim({
        status: 'resolved',
        resolution_type: 'full_refund',
        resolution_amount: 500,
        resolution_notes: 'Full refund issued.',
        resolved_at: '2025-03-16T14:00:00Z',
        refund_id: 'refund-abc-123',
      }),
    })

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Resolution')).toBeInTheDocument()
    })

    expect(screen.getByText('Full Refund')).toBeInTheDocument()
    expect(screen.getByText('Full refund issued.')).toBeInTheDocument()
  })

  it('renders cost breakdown section', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: createMockClaim({
        cost_to_business: 150,
        cost_breakdown: { labour_cost: 80, parts_cost: 50, write_off_cost: 20 },
      }),
    })

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Cost to Business')).toBeInTheDocument()
    })

    expect(screen.getByText('Labour')).toBeInTheDocument()
    expect(screen.getByText('Parts')).toBeInTheDocument()
    expect(screen.getByText('Write-off')).toBeInTheDocument()
  })

  it('shows error state when claim not found', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error('Not found'))

    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('Failed to load claim details.')).toBeInTheDocument()
    })
  })

  it('navigates back to claims list on back button click', async () => {
    const user = userEvent.setup()
    render(<ClaimDetail />)

    await waitFor(() => {
      expect(screen.getByText('← Back to Claims')).toBeInTheDocument()
    })

    await user.click(screen.getByText('← Back to Claims'))
    expect(mockNavigate).toHaveBeenCalledWith('/claims')
  })
})
