/**
 * Unit tests for ClaimsReports page component.
 *
 * Requirements: 10.1-10.6
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'

vi.mock('react-router-dom', () => ({
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}))

vi.mock('../../../api/client', () => ({
  default: { get: vi.fn() },
}))

vi.mock('../../../contexts/BranchContext', () => ({
  useBranch: () => ({
    branches: [
      { id: 'branch-1', name: 'Main', is_active: true },
      { id: 'branch-2', name: 'North', is_active: true },
    ],
    selectedBranchId: null,
    selectBranch: vi.fn(),
    isLoading: false,
  }),
}))

import apiClient from '../../../api/client'
import ClaimsReports from '../ClaimsReports'

const mockByPeriod = {
  periods: [
    { period: '2025-01-01T00:00:00', claim_count: 5, total_cost: '250.00', average_resolution_hours: 48.5 },
    { period: '2025-02-01T00:00:00', claim_count: 3, total_cost: '120.00', average_resolution_hours: 24.0 },
  ],
}

const mockCostOverhead = {
  total_refunds: '500.00',
  total_credit_notes: '200.00',
  total_write_offs: '75.00',
  total_labour_cost: '300.00',
}

const mockSupplierQuality = {
  items: [
    { product_id: 'prod-1', product_name: 'Brake Pad Set', sku: 'BP-001', return_count: 8 },
    { product_id: 'prod-2', product_name: 'Oil Filter', sku: 'OF-002', return_count: 3 },
  ],
}

const mockServiceQuality = {
  items: [
    { staff_id: 'staff-1', staff_name: 'Mike Johnson', redo_count: 4 },
    { staff_id: 'staff-2', staff_name: 'Sarah Lee', redo_count: 2 },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url === '/claims/reports/by-period') return { data: mockByPeriod }
    if (url === '/claims/reports/cost-overhead') return { data: mockCostOverhead }
    if (url === '/claims/reports/supplier-quality') return { data: mockSupplierQuality }
    if (url === '/claims/reports/service-quality') return { data: mockServiceQuality }
    return { data: {} }
  })
})

describe('ClaimsReports', () => {
  it('renders page title and filter controls', async () => {
    render(<ClaimsReports />)

    expect(screen.getByText('Claims Reports')).toBeInTheDocument()
    expect(screen.getByLabelText('From')).toBeInTheDocument()
    expect(screen.getByLabelText('To')).toBeInTheDocument()
    expect(screen.getByLabelText('Branch')).toBeInTheDocument()
  })

  it('renders branch selector with options', () => {
    render(<ClaimsReports />)

    const branchSelect = screen.getByLabelText('Branch')
    expect(branchSelect).toBeInTheDocument()
    expect(screen.getByText('All Branches')).toBeInTheDocument()
    expect(screen.getByText('Main')).toBeInTheDocument()
    expect(screen.getByText('North')).toBeInTheDocument()
  })

  it('renders claims by period tab by default', async () => {
    render(<ClaimsReports />)

    await waitFor(() => {
      expect(screen.getByText('Jan 2025')).toBeInTheDocument()
    })

    expect(screen.getByText('Feb 2025')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('48.5')).toBeInTheDocument()
  })

  it('switches to cost overhead tab', async () => {
    const user = userEvent.setup()
    render(<ClaimsReports />)

    await user.click(screen.getByRole('tab', { name: 'Cost Overhead' }))

    await waitFor(() => {
      expect(screen.getByText('Total Refunds')).toBeInTheDocument()
    })

    expect(screen.getByText('Total Credit Notes')).toBeInTheDocument()
    expect(screen.getByText('Total Write-offs')).toBeInTheDocument()
    expect(screen.getByText('Total Labour Cost')).toBeInTheDocument()
  })

  it('switches to supplier quality tab', async () => {
    const user = userEvent.setup()
    render(<ClaimsReports />)

    await user.click(screen.getByRole('tab', { name: 'Supplier Quality' }))

    await waitFor(() => {
      expect(screen.getByText('Brake Pad Set')).toBeInTheDocument()
    })

    expect(screen.getByText('BP-001')).toBeInTheDocument()
    expect(screen.getByText('Oil Filter')).toBeInTheDocument()
  })

  it('switches to service quality tab', async () => {
    const user = userEvent.setup()
    render(<ClaimsReports />)

    await user.click(screen.getByRole('tab', { name: 'Service Quality' }))

    await waitFor(() => {
      expect(screen.getByText('Mike Johnson')).toBeInTheDocument()
    })

    expect(screen.getByText('Sarah Lee')).toBeInTheDocument()
  })

  it('passes date filters to API', async () => {
    const user = userEvent.setup()
    render(<ClaimsReports />)

    const fromInput = screen.getByLabelText('From')
    const toInput = screen.getByLabelText('To')

    await user.type(fromInput, '2025-01-01')
    await user.type(toInput, '2025-03-31')

    await waitFor(() => {
      const calls = vi.mocked(apiClient.get).mock.calls
      const lastByPeriodCall = calls.filter(c => c[0] === '/claims/reports/by-period').pop()
      expect(lastByPeriodCall?.[1]?.params?.date_from).toBe('2025-01-01')
      expect(lastByPeriodCall?.[1]?.params?.date_to).toBe('2025-03-31')
    })
  })

  it('passes branch filter to API', async () => {
    const user = userEvent.setup()
    render(<ClaimsReports />)

    const branchSelect = screen.getByLabelText('Branch')
    await user.selectOptions(branchSelect, 'branch-1')

    await waitFor(() => {
      const calls = vi.mocked(apiClient.get).mock.calls
      const lastByPeriodCall = calls.filter(c => c[0] === '/claims/reports/by-period').pop()
      expect(lastByPeriodCall?.[1]?.params?.branch_id).toBe('branch-1')
    })
  })

  it('shows empty state for claims by period when no data', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url === '/claims/reports/by-period') return { data: { periods: [] } }
      return { data: {} }
    })

    render(<ClaimsReports />)

    await waitFor(() => {
      expect(screen.getByText('No claims data for the selected period.')).toBeInTheDocument()
    })
  })
})
