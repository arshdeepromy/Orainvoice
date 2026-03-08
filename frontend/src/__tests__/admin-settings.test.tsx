import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 50.1-50.3
 * - 50.1: Manage Global Vehicle DB, T&C with version history, announcement banner
 * - 50.2: Updating T&C prompts all users to re-accept on next login
 * - 50.3: Set platform announcement banner for maintenance/feature notices
 *
 * Note: Subscription plans and storage pricing are managed on the dedicated
 * Subscription Management page (SubscriptionPlans.tsx), not here.
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPut = vi.fn()
  const mockPost = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, put: mockPut, post: mockPost, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import { Settings } from '../pages/admin/Settings'

/* ── Backend-shaped types ── */

interface PlatformSettings {
  storage_pricing: { increment_gb: number; price_per_gb_nzd: number }
  terms_and_conditions: { content: string; version: number } | string
  terms_version: number
  terms_history: { version: number; content: string; updated_at: string }[]
  announcement_banner: string
}

interface VehicleDbStats {
  total_records: number
  last_refreshed_at: string
}

function makeSettings(overrides: Partial<PlatformSettings> = {}): PlatformSettings {
  return {
    storage_pricing: { increment_gb: 5, price_per_gb_nzd: 2.5 },
    terms_and_conditions: { content: 'Default platform terms.', version: 3 },
    terms_version: 3,
    terms_history: [
      { version: 3, content: 'Default platform terms.', updated_at: '2024-06-01T00:00:00Z' },
      { version: 2, content: 'Previous terms v2.', updated_at: '2024-03-01T00:00:00Z' },
      { version: 1, content: 'Original terms v1.', updated_at: '2024-01-01T00:00:00Z' },
    ],
    announcement_banner: '',
    ...overrides,
  }
}

function makeVehicleDbStats(overrides: Partial<VehicleDbStats> = {}): VehicleDbStats {
  return {
    total_records: 15420,
    last_refreshed_at: '2024-06-15T10:30:00Z',
    ...overrides,
  }
}

function setupMocks(
  settings: PlatformSettings = makeSettings(),
  vehicleStats: VehicleDbStats = makeVehicleDbStats(),
) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/settings') return Promise.resolve({ data: settings })
    if (url === '/admin/vehicle-db/stats') return Promise.resolve({ data: vehicleStats })
    if (url.startsWith('/admin/vehicle-db/search/')) {
      return Promise.resolve({
        data: [{ id: 'v-1', rego: 'ABC123', make: 'Toyota', model: 'Corolla', year: 2020, last_pulled_at: '2024-06-01T00:00:00Z' }],
      })
    }
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
}

describe('Admin Platform Settings page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // 50.1: Page renders with tabbed layout (no Storage tab — moved to Subscription Management)
  it('renders the settings page with Vehicle DB, T&C, and Announcements tabs', async () => {
    setupMocks()
    render(<Settings />)

    expect(screen.getByText('Platform Settings')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vehicle DB' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'T&C' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Announcements' })).toBeInTheDocument()
    // Storage tab has been moved to Subscription Management page
    expect(screen.queryByRole('tab', { name: 'Storage' })).not.toBeInTheDocument()
  })

  // 50.1: Vehicle DB tab — displays stats
  it('displays vehicle database stats in the Vehicle DB tab', async () => {
    setupMocks()
    render(<Settings />)

    // Vehicle DB is now the default tab
    expect(await screen.findByText('Global Vehicle Database')).toBeInTheDocument()
    expect(screen.getByText('Total records')).toBeInTheDocument()
    expect(screen.getByText('15,420')).toBeInTheDocument()
  })

  // 50.1: Vehicle DB tab — search by rego
  it('searches for a vehicle by registration number', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await screen.findByText('Global Vehicle Database')

    const searchInput = screen.getByLabelText('Search by registration')
    await user.type(searchInput, 'ABC123')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(apiClient.get).toHaveBeenCalledWith('/admin/vehicle-db/search/ABC123')
    expect(await screen.findByText('Toyota')).toBeInTheDocument()
    expect(screen.getByText('Corolla')).toBeInTheDocument()
  })

  // 50.1: Vehicle DB tab — force refresh
  it('calls refresh API for a vehicle record', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await screen.findByText('Global Vehicle Database')

    await user.type(screen.getByLabelText('Search by registration'), 'ABC123')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await screen.findByText('Toyota')
    await user.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(apiClient.post).toHaveBeenCalledWith('/admin/vehicle-db/ABC123/refresh')
  })

  // 50.1: Vehicle DB tab — delete stale record
  it('calls delete API for stale vehicle records', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await screen.findByText('Global Vehicle Database')

    await user.click(screen.getByRole('button', { name: 'Purge stale records' }))

    expect(apiClient.delete).toHaveBeenCalledWith('/admin/vehicle-db/stale', { params: { stale_days: 0 } })
  })

  // 50.1 + 50.2: T&C tab — displays current terms with version
  it('displays terms and conditions with current version in the T&C tab', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'T&C' }))

    expect(await screen.findByText('Platform Terms & Conditions')).toBeInTheDocument()
    expect(screen.getByText('Current version: 3')).toBeInTheDocument()
    expect(screen.getByLabelText('Terms content')).toHaveValue('Default platform terms.')
  })

  // 50.1: T&C tab — version history
  it('shows version history when Version history button is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'T&C' }))
    await screen.findByText('Platform Terms & Conditions')

    await user.click(screen.getByRole('button', { name: 'Version history' }))

    const historyRegion = screen.getByRole('region', { name: /terms version history/i })
    expect(within(historyRegion).getByText('Version 3')).toBeInTheDocument()
    expect(within(historyRegion).getByText('Version 2')).toBeInTheDocument()
    expect(within(historyRegion).getByText('Version 1')).toBeInTheDocument()
  })

  // 50.2: T&C tab — publishing new version calls API
  it('publishes new terms version', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'T&C' }))
    await screen.findByText('Platform Terms & Conditions')

    const editor = screen.getByLabelText('Terms content')
    await user.clear(editor)
    await user.type(editor, 'Updated terms content.')

    await user.click(screen.getByRole('button', { name: 'Publish new version' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/settings', {
      terms_and_conditions: 'Updated terms content.',
    })
  })

  // 50.2: T&C tab — re-accept notice is displayed
  it('displays re-accept notice below the terms editor', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'T&C' }))
    await screen.findByText('Platform Terms & Conditions')

    expect(screen.getByText(/prompt all users to re-accept/i)).toBeInTheDocument()
  })

  // 50.3: Announcements tab — displays announcement banner editor
  it('displays announcement banner editor in the Announcements tab', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Announcements' }))

    expect(await screen.findByText('Announcement Banner')).toBeInTheDocument()
    expect(screen.getByLabelText('Banner text')).toBeInTheDocument()
    expect(screen.getByText(/visible to all organisation users/i)).toBeInTheDocument()
  })

  // 50.3: Announcements tab — save banner
  it('saves announcement banner text', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Announcements' }))
    await screen.findByText('Announcement Banner')

    const textarea = screen.getByLabelText('Banner text')
    await user.type(textarea, 'Scheduled maintenance tonight')

    await user.click(screen.getByRole('button', { name: 'Update banner' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/settings', {
      announcement_banner: 'Scheduled maintenance tonight',
    })
  })

  // 50.3: Announcements tab — preview shown when text entered
  it('shows banner preview when announcement text is entered', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Announcements' }))
    await screen.findByText('Announcement Banner')

    await user.type(screen.getByLabelText('Banner text'), 'System update')

    const preview = screen.getByRole('region', { name: /banner preview/i })
    expect(within(preview).getByText('System update')).toBeInTheDocument()
    expect(within(preview).getByText('Platform Announcement')).toBeInTheDocument()
  })

  // 50.3: Announcements tab — clear banner
  it('clears announcement banner when Clear button is clicked', async () => {
    setupMocks(
      makeSettings({ announcement_banner: 'Existing announcement' }),
    )
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Announcements' }))
    await screen.findByText('Announcement Banner')

    expect(screen.getByLabelText('Banner text')).toHaveValue('Existing announcement')

    await user.click(screen.getByRole('button', { name: 'Clear' }))

    expect(screen.getByLabelText('Banner text')).toHaveValue('')
  })
})
