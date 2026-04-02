/**
 * Unit tests for ClaimsList component.
 *
 * Requirements: 6.1-6.5
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}))

import apiClient from '../../../api/client'
import ClaimsList from '../ClaimsList'

function createMockClaimsList(count = 3) {
  return {
    items: Array.from({ length: count }, (_, i) => ({
      id: `claim-${i + 1}-uuid-abcdef1234567890`,
      customer_id: `cust-${i + 1}`,
      customer_name: `Customer ${i + 1}`,
      claim_type: ['warranty', 'defect', 'service_redo'][i % 3],
      status: ['open', 'investigating', 'approved'][i % 3],
      description: `Test claim ${i + 1}`,
      cost_to_business: (i + 1) * 50,
      branch_id: null,
      created_at: '2025-03-15T10:00:00Z',
    })),
    total: count,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  vi.mocked(apiClient.get).mockResolvedValue({ data: createMockClaimsList() })
})

describe('ClaimsList', () => {
  it('renders claims table with data', async () => {
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getByText('Customer 1')).toBeInTheDocument()
    })

    expect(screen.getByText('Customer 2')).toBeInTheDocument()
    expect(screen.getByText('Customer 3')).toBeInTheDocument()
    // Use getAllByText since Badge sr-only text may duplicate
    expect(screen.getAllByText('Warranty').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Open').length).toBeGreaterThanOrEqual(1)
  })

  it('shows loading spinner initially', () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}))
    render(<ClaimsList />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows error message on API failure', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error('Network error'))
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getByText('Failed to load claims.')).toBeInTheDocument()
    })
  })

  it('shows empty state when no claims', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [], total: 0 } })
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getByText(/No claims yet/)).toBeInTheDocument()
    })
  })

  it('navigates to claim detail on row click', async () => {
    const user = userEvent.setup()
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getByText('Customer 1')).toBeInTheDocument()
    })

    const rows = screen.getAllByRole('row')
    // First row is header, second is first data row
    await user.click(rows[1])
    expect(mockNavigate).toHaveBeenCalledWith('/claims/claim-1-uuid-abcdef1234567890')
  })

  it('navigates to new claim form on button click', async () => {
    const user = userEvent.setup()
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getByText('Customer 1')).toBeInTheDocument()
    })

    await user.click(screen.getByText('+ New Claim'))
    expect(mockNavigate).toHaveBeenCalledWith('/claims/new')
  })

  it('renders status badges with correct text', async () => {
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getAllByText('Open').length).toBeGreaterThanOrEqual(1)
    })

    expect(screen.getAllByText('Investigating').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Approved').length).toBeGreaterThanOrEqual(1)
  })

  it('sends filter params to API when status filter changes', async () => {
    const user = userEvent.setup()
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getByText('Customer 1')).toBeInTheDocument()
    })

    const statusSelect = screen.getByLabelText('Status')
    await user.selectOptions(statusSelect, 'open')

    await waitFor(() => {
      const calls = vi.mocked(apiClient.get).mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[1]?.params?.status).toBe('open')
    })
  })

  it('sends search param to API when search input changes', async () => {
    const user = userEvent.setup()
    render(<ClaimsList />)

    await waitFor(() => {
      expect(screen.getByText('Customer 1')).toBeInTheDocument()
    })

    const searchInput = screen.getByLabelText('Search')
    await user.type(searchInput, 'test query')

    await waitFor(() => {
      const calls = vi.mocked(apiClient.get).mock.calls
      const lastCall = calls[calls.length - 1]
      expect(lastCall[1]?.params?.search).toBe('test query')
    })
  })
})
