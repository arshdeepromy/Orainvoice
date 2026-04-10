import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Extended Asset Tracking — Task 45.11
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import AssetList, { getAssetLabel } from '../pages/assets/AssetList'
import AssetDetail from '../pages/assets/AssetDetail'

const mockAssets = [
  {
    id: 'asset-1', org_id: 'org-1', customer_id: null,
    asset_type: 'vehicle', identifier: 'ABC123',
    make: 'Toyota', model: 'Corolla', year: 2020,
    serial_number: null, is_active: true,
    created_at: '2025-01-15T10:00:00Z',
    updated_at: '2025-01-15T10:00:00Z',
  },
  {
    id: 'asset-2', org_id: 'org-1', customer_id: 'cust-1',
    asset_type: 'vehicle', identifier: 'XYZ789',
    make: 'Honda', model: 'Civic', year: 2022,
    serial_number: 'SN-001', is_active: true,
    created_at: '2025-01-15T11:00:00Z',
    updated_at: '2025-01-15T11:00:00Z',
  },
]

const mockAssetDetail = {
  id: 'asset-1', org_id: 'org-1', customer_id: null,
  asset_type: 'vehicle', identifier: 'ABC123',
  make: 'Toyota', model: 'Corolla', year: 2020,
  description: 'Family car', serial_number: null,
  location: null, custom_fields: { colour: 'Blue' },
  carjam_data: null, is_active: true,
  created_at: '2025-01-15T10:00:00Z',
  updated_at: '2025-01-15T10:00:00Z',
}

const mockHistory = {
  asset_id: 'asset-1',
  entries: [
    {
      reference_type: 'job', reference_id: 'job-1',
      reference_number: 'JOB-001', description: 'Oil change',
      date: '2025-01-15T10:00:00Z', status: 'completed',
    },
    {
      reference_type: 'invoice', reference_id: 'inv-1',
      reference_number: 'INV-001', description: null,
      date: '2025-01-14T10:00:00Z', status: 'paid',
    },
  ],
}

// -----------------------------------------------------------------------
// getAssetLabel
// -----------------------------------------------------------------------

describe('getAssetLabel', () => {
  it('returns Vehicle for automotive', () => {
    expect(getAssetLabel('automotive-transport')).toBe('Vehicle')
  })

  it('returns Device for IT', () => {
    expect(getAssetLabel('it-technology')).toBe('Device')
  })

  it('returns Property for building', () => {
    expect(getAssetLabel('building-construction')).toBe('Property')
  })

  it('returns Asset for unknown trade', () => {
    expect(getAssetLabel('unknown')).toBe('Asset')
  })

  it('returns Asset when no trade family', () => {
    expect(getAssetLabel()).toBe('Asset')
  })
})

// -----------------------------------------------------------------------
// AssetList
// -----------------------------------------------------------------------

describe('AssetList', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function setupMocks() {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValue({ data: mockAssets })
  }

  it('renders loading state', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockReturnValue(new Promise(() => {}))
    render(<AssetList />)
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i)
  })

  it('renders asset list', async () => {
    setupMocks()
    render(<AssetList />)
    await waitFor(() => {
      expect(screen.getByText('ABC123')).toBeInTheDocument()
      expect(screen.getByText('XYZ789')).toBeInTheDocument()
    })
  })

  it('uses trade-specific label for automotive', async () => {
    setupMocks()
    render(<AssetList tradeFamily="automotive-transport" />)
    await waitFor(() => {
      expect(screen.getByText('Vehicles')).toBeInTheDocument()
    })
  })

  it('uses trade-specific label for IT', async () => {
    setupMocks()
    render(<AssetList tradeFamily="it-technology" />)
    await waitFor(() => {
      expect(screen.getByText('Devices')).toBeInTheDocument()
    })
  })

  it('shows empty state', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockResolvedValue({ data: [] })
    render(<AssetList />)
    await waitFor(() => {
      expect(screen.getByText(/no assets found/i)).toBeInTheDocument()
    })
  })

  it('shows add button', async () => {
    setupMocks()
    render(<AssetList />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add asset/i })).toBeInTheDocument()
    })
  })

  it('toggles create form', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<AssetList />)
    await waitFor(() => {
      expect(screen.getByText('ABC123')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /add asset/i }))
    expect(screen.getByLabelText(/identifier/i)).toBeInTheDocument()
  })

  it('handles API error', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockRejectedValue(new Error('Network error'))
    render(<AssetList />)
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
  })
})

// -----------------------------------------------------------------------
// AssetDetail
// -----------------------------------------------------------------------

describe('AssetDetail', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function setupMocks() {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockImplementation((url: string) => {
        if (url.includes('/history')) return Promise.resolve({ data: mockHistory })
        return Promise.resolve({ data: mockAssetDetail })
      })
  }

  it('renders loading state', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockReturnValue(new Promise(() => {}))
    render(<AssetDetail assetId="asset-1" />)
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i)
  })

  it('renders asset details', async () => {
    setupMocks()
    render(<AssetDetail assetId="asset-1" />)
    await waitFor(() => {
      expect(screen.getByText('ABC123')).toBeInTheDocument()
      expect(screen.getByText('Toyota')).toBeInTheDocument()
      expect(screen.getByText('Corolla')).toBeInTheDocument()
    })
  })

  it('renders custom fields', async () => {
    setupMocks()
    render(<AssetDetail assetId="asset-1" />)
    await waitFor(() => {
      expect(screen.getByText('colour')).toBeInTheDocument()
      expect(screen.getByText('Blue')).toBeInTheDocument()
    })
  })

  it('renders service history', async () => {
    setupMocks()
    render(<AssetDetail assetId="asset-1" />)
    await waitFor(() => {
      expect(screen.getByText('JOB-001')).toBeInTheDocument()
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })
  })

  it('shows Carjam button for automotive trade', async () => {
    setupMocks()
    render(<AssetDetail assetId="asset-1" tradeFamily="automotive-transport" />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /lookup carjam/i })).toBeInTheDocument()
    })
  })

  it('hides Carjam button for non-automotive trade', async () => {
    setupMocks()
    render(<AssetDetail assetId="asset-1" tradeFamily="it-technology" />)
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /lookup carjam/i })).not.toBeInTheDocument()
    })
  })

  it('uses trade-specific label', async () => {
    setupMocks()
    render(<AssetDetail assetId="asset-1" tradeFamily="automotive-transport" />)
    await waitFor(() => {
      expect(screen.getByText(/Vehicle:/)).toBeInTheDocument()
    })
  })

  it('handles not found', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockRejectedValue(new Error('Not found'))
    render(<AssetDetail assetId="asset-999" />)
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
  })
})
