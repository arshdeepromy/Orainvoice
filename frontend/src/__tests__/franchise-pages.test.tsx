import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 8 — Extended RBAC / Multi-Location, Task 43.15
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
import LocationList from '../pages/franchise/LocationList'
import StockTransfers from '../pages/franchise/StockTransfers'
import FranchiseDashboard from '../pages/franchise/FranchiseDashboard'

const mockLocations = [
  {
    id: 'loc-1', org_id: 'org-1', name: 'Main Branch',
    address: '123 Main St', phone: '555-0100', email: 'main@test.com',
    invoice_prefix: 'MB', has_own_inventory: true, is_active: true,
    created_at: '2025-01-15T10:00:00Z', updated_at: '2025-01-15T10:00:00Z',
  },
  {
    id: 'loc-2', org_id: 'org-1', name: 'South Branch',
    address: '456 South Ave', phone: '555-0200', email: null,
    invoice_prefix: null, has_own_inventory: false, is_active: true,
    created_at: '2025-01-15T10:00:00Z', updated_at: '2025-01-15T10:00:00Z',
  },
]

const mockTransfers = [
  {
    id: 'tf-1', org_id: 'org-1', from_location_id: 'loc-1',
    to_location_id: 'loc-2', product_id: 'prod-1', quantity: '10.000',
    status: 'pending', requested_by: 'user-1', approved_by: null,
    created_at: '2025-01-15T10:00:00Z', completed_at: null,
  },
  {
    id: 'tf-2', org_id: 'org-1', from_location_id: 'loc-2',
    to_location_id: 'loc-1', product_id: 'prod-2', quantity: '5.000',
    status: 'approved', requested_by: 'user-2', approved_by: 'user-1',
    created_at: '2025-01-15T11:00:00Z', completed_at: null,
  },
]

const mockHeadOffice = {
  total_revenue: '50000.00',
  total_outstanding: '10000.00',
  location_metrics: [
    { location_id: 'loc-1', location_name: 'Main Branch', revenue: '30000.00', outstanding: '6000.00', invoice_count: 30 },
    { location_id: 'loc-2', location_name: 'South Branch', revenue: '20000.00', outstanding: '4000.00', invoice_count: 20 },
  ],
}

const mockFranchiseMetrics = {
  total_organisations: 5,
  total_revenue: '250000.00',
  total_outstanding: '50000.00',
  total_locations: 12,
}

// -----------------------------------------------------------------------
// LocationList
// -----------------------------------------------------------------------

describe('LocationList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function setupMocks() {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValue({ data: mockLocations })
  }

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<LocationList />)
    expect(screen.getByRole('status', { name: 'Loading locations' })).toBeInTheDocument()
  })

  it('displays locations in a table', async () => {
    setupMocks()
    render(<LocationList />)

    const table = await screen.findByRole('grid', { name: 'Locations list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 locations
    expect(screen.getByTestId('location-row-Main Branch')).toHaveTextContent('Main Branch')
    expect(screen.getByTestId('location-row-South Branch')).toHaveTextContent('South Branch')
  })

  it('shows add location form when button clicked', async () => {
    setupMocks()
    render(<LocationList />)
    await screen.findByRole('grid', { name: 'Locations list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add location' }))
    expect(screen.getByRole('form', { name: 'Create location form' })).toBeInTheDocument()
  })

  it('submits new location', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new' } })
    render(<LocationList />)
    await screen.findByRole('grid', { name: 'Locations list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add location' }))
    await user.type(screen.getByLabelText('Location Name'), 'North Branch')
    await user.type(screen.getByLabelText('Address'), '789 North Rd')
    await user.click(screen.getByRole('button', { name: 'Save location' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/locations', expect.objectContaining({
      name: 'North Branch',
      address: '789 North Rd',
    }))
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<LocationList />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load locations')
  })

  it('shows empty state when no locations', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: [] })
    render(<LocationList />)
    expect(await screen.findByText('No locations configured')).toBeInTheDocument()
  })
})

// -----------------------------------------------------------------------
// StockTransfers
// -----------------------------------------------------------------------

describe('StockTransfers', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function setupMocks() {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValue({ data: mockTransfers })
  }

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<StockTransfers />)
    expect(screen.getByRole('status', { name: 'Loading transfers' })).toBeInTheDocument()
  })

  it('displays transfers in a table', async () => {
    setupMocks()
    render(<StockTransfers />)

    const table = await screen.findByRole('grid', { name: 'Stock transfers list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 transfers
  })

  it('shows approve button for pending transfers', async () => {
    setupMocks()
    render(<StockTransfers />)
    await screen.findByRole('grid', { name: 'Stock transfers list' })

    expect(screen.getByRole('button', { name: 'Approve transfer' })).toBeInTheDocument()
  })

  it('shows execute button for approved transfers', async () => {
    setupMocks()
    render(<StockTransfers />)
    await screen.findByRole('grid', { name: 'Stock transfers list' })

    expect(screen.getByRole('button', { name: 'Execute transfer' })).toBeInTheDocument()
  })

  it('calls approve API when approve clicked', async () => {
    setupMocks()
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
    render(<StockTransfers />)
    await screen.findByRole('grid', { name: 'Stock transfers list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Approve transfer' }))

    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/stock-transfers/tf-1/approve')
  })

  it('shows request transfer form', async () => {
    setupMocks()
    render(<StockTransfers />)
    await screen.findByRole('grid', { name: 'Stock transfers list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Request transfer' }))
    expect(screen.getByRole('form', { name: 'Create transfer form' })).toBeInTheDocument()
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<StockTransfers />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load stock transfers')
  })
})

// -----------------------------------------------------------------------
// FranchiseDashboard
// -----------------------------------------------------------------------

describe('FranchiseDashboard', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<FranchiseDashboard />)
    expect(screen.getByRole('status', { name: 'Loading dashboard' })).toBeInTheDocument()
  })

  it('displays head office view with aggregate metrics', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockHeadOffice })
    render(<FranchiseDashboard />)

    await screen.findByTestId('head-office-view')
    expect(screen.getByTestId('total-revenue')).toBeInTheDocument()
    expect(screen.getByTestId('total-outstanding')).toBeInTheDocument()
  })

  it('displays per-location comparison table', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockHeadOffice })
    render(<FranchiseDashboard />)

    const table = await screen.findByRole('grid', { name: 'Location comparison' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 locations
    expect(screen.getByTestId('loc-metric-Main Branch')).toBeInTheDocument()
  })

  it('switches to franchise view', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockImplementation((url: string) => {
        if (url.includes('/dashboard')) return Promise.resolve({ data: mockFranchiseMetrics })
        return Promise.resolve({ data: mockHeadOffice })
      })
    render(<FranchiseDashboard />)
    await screen.findByTestId('head-office-view')

    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'Franchise view' }))

    await screen.findByTestId('franchise-view')
    expect(screen.getByTestId('franchise-orgs')).toHaveTextContent('5')
    expect(screen.getByTestId('franchise-locations')).toHaveTextContent('12')
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<FranchiseDashboard />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load head-office dashboard')
  })
})
