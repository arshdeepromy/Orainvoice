import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
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
    user: { id: 'u1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1', assigned_locations: [] },
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
    status: 'pending', notes: 'Urgent', requested_by: 'user-1', approved_by: null,
    created_at: '2025-01-15T10:00:00Z', completed_at: null,
  },
  {
    id: 'tf-2', org_id: 'org-1', from_location_id: 'loc-2',
    to_location_id: 'loc-1', product_id: 'prod-2', quantity: '5.000',
    status: 'approved', notes: null, requested_by: 'user-2', approved_by: 'user-1',
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

  it('shows loading spinner initially', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    const { unmount } = render(<LocationList />)
    expect(screen.getByRole('status', { name: 'Loading locations' })).toBeInTheDocument()
    unmount()
  })

  it('displays locations in a table', async () => {
    setupMocks()
    render(<LocationList />)

    const table = await screen.findByRole('grid', { name: 'Locations list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 locations
    expect(await screen.findByTestId('location-row-Main Branch')).toHaveTextContent('Main Branch')
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
    const form = await screen.findByRole('form', { name: 'Create location form' })
    const nameInput = within(form).getByLabelText('Location Name')
    const addressInput = within(form).getByLabelText('Address')
    await user.type(nameInput, 'North Branch')
    await user.type(addressInput, '789 North Rd')
    await user.click(within(form).getByRole('button', { name: 'Save location' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/locations', expect.objectContaining({
      name: 'North Branch',
      address: '789 North Rd',
    }))
  })

  it('shows edit form when edit button clicked', async () => {
    setupMocks()
    render(<LocationList />)
    await screen.findByRole('grid', { name: 'Locations list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Main Branch' }))
    expect(screen.getByRole('form', { name: 'Edit location form' })).toBeInTheDocument()
    expect(screen.getByLabelText('Location Name')).toHaveValue('Main Branch')
  })

  it('submits edit location', async () => {
    setupMocks()
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
    render(<LocationList />)
    await screen.findByRole('grid', { name: 'Locations list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Edit Main Branch' }))
    const form = await screen.findByRole('form', { name: 'Edit location form' })
    const nameInput = within(form).getByLabelText('Location Name')
    await user.clear(nameInput)
    await user.type(nameInput, 'Updated Branch')
    await user.click(within(form).getByRole('button', { name: 'Update location' }))

    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/locations/loc-1', expect.objectContaining({
      name: 'Updated Branch',
    }))
  })

  it('calls deactivate API when deactivate clicked', async () => {
    setupMocks()
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
    render(<LocationList />)
    await screen.findByRole('grid', { name: 'Locations list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Deactivate Main Branch' }))

    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/locations/loc-1', { is_active: false })
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
      .mockImplementation((url: string) => {
        if (url.includes('/api/v2/locations')) return Promise.resolve({ data: mockLocations })
        return Promise.resolve({ data: mockTransfers })
      })
  }

  it('shows loading spinner initially', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    const { unmount } = render(<StockTransfers />)
    expect(screen.getByRole('status', { name: 'Loading transfers' })).toBeInTheDocument()
    unmount()
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

  it('shows request transfer form with location dropdowns', async () => {
    setupMocks()
    render(<StockTransfers />)
    await screen.findByRole('grid', { name: 'Stock transfers list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Request transfer' }))
    expect(screen.getByRole('form', { name: 'Create transfer form' })).toBeInTheDocument()
    // Should have location dropdowns since locations were loaded
    expect(screen.getByLabelText('Source Location')).toBeInTheDocument()
    expect(screen.getByLabelText('Destination Location')).toBeInTheDocument()
  })

  it('displays transfer notes and dates', async () => {
    setupMocks()
    render(<StockTransfers />)
    await screen.findByRole('grid', { name: 'Stock transfers list' })

    expect(screen.getByText('Urgent')).toBeInTheDocument()
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

  it('displays per-location performance chart', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockHeadOffice })
    render(<FranchiseDashboard />)

    await screen.findByTestId('head-office-view')
    expect(screen.getByTestId('performance-chart')).toBeInTheDocument()
    expect(screen.getByTestId('chart-bar-Main Branch')).toBeInTheDocument()
    expect(screen.getByTestId('chart-bar-South Branch')).toBeInTheDocument()
  })

  it('supports per-location filtering', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockHeadOffice })
    render(<FranchiseDashboard />)

    await screen.findByTestId('head-office-view')
    const user = userEvent.setup()
    const filter = screen.getByLabelText('Filter by Location')
    await user.selectOptions(filter, 'loc-1')

    // After filtering, only Main Branch should be visible in chart
    expect(screen.getByTestId('chart-bar-Main Branch')).toBeInTheDocument()
    expect(screen.queryByTestId('chart-bar-South Branch')).not.toBeInTheDocument()
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

// -----------------------------------------------------------------------
// filterByUserLocations utility
// -----------------------------------------------------------------------

import { filterByUserLocations } from '../utils/franchiseUtils'

describe('filterByUserLocations', () => {
  const data = [
    { id: '1', location_id: 'loc-1', name: 'Item A' },
    { id: '2', location_id: 'loc-2', name: 'Item B' },
    { id: '3', location_id: 'loc-3', name: 'Item C' },
  ]

  it('returns all data for org_admin role', () => {
    const result = filterByUserLocations(data, ['loc-1'], 'org_admin')
    expect(result).toHaveLength(3)
  })

  it('filters data for location_manager role', () => {
    const result = filterByUserLocations(data, ['loc-1', 'loc-3'], 'location_manager')
    expect(result).toHaveLength(2)
    expect(result.map((d) => d.location_id)).toEqual(['loc-1', 'loc-3'])
  })

  it('returns empty for location_manager with no assigned locations', () => {
    const result = filterByUserLocations(data, [], 'location_manager')
    expect(result).toHaveLength(0)
  })

  it('supports custom location key', () => {
    const items = [{ id: '1', loc: 'loc-1' }, { id: '2', loc: 'loc-2' }]
    const result = filterByUserLocations(items, ['loc-1'], 'location_manager', 'loc')
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('1')
  })
})
