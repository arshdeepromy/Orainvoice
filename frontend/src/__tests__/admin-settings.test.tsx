import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 50.1-50.3
 * - 50.1: Manage subscription plans, storage pricing, Global Vehicle DB, T&C with version history, announcement banner
 * - 50.2: Updating T&C prompts all users to re-accept on next login
 * - 50.3: Set platform announcement banner for maintenance/feature notices
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
import type { SubscriptionPlan, PlatformSettings, VehicleDbStats } from '../pages/admin/Settings'

/* ── Test data factories ── */

function makePlan(overrides: Partial<SubscriptionPlan> = {}): SubscriptionPlan {
  return {
    id: 'plan-001',
    name: 'Starter',
    monthly_price_nzd: 49.0,
    user_seats: 3,
    storage_quota_gb: 5,
    carjam_lookups_included: 100,
    enabled_modules: ['invoices', 'payments'],
    is_public: true,
    is_archived: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-06-01T00:00:00Z',
    ...overrides,
  }
}

function makeSettings(overrides: Partial<PlatformSettings> = {}): PlatformSettings {
  return {
    storage_pricing: { increment_gb: 5, price_per_gb_nzd: 2.5 },
    terms_and_conditions: 'Default platform terms.',
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
  plans: SubscriptionPlan[] = [makePlan()],
  settings: PlatformSettings = makeSettings(),
  vehicleStats: VehicleDbStats = makeVehicleDbStats(),
) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/plans') return Promise.resolve({ data: plans })
    if (url === '/admin/settings') return Promise.resolve({ data: settings })
    if (url === '/admin/vehicle-db') return Promise.resolve({ data: vehicleStats })
    if (url.startsWith('/admin/vehicle-db/')) {
      return Promise.resolve({
        data: { id: 'v-1', rego: 'ABC123', make: 'Toyota', model: 'Corolla', year: 2020, last_pulled_at: '2024-06-01T00:00:00Z' },
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

  // 50.1: Page renders with tabbed layout
  it('renders the settings page with all five tabs', async () => {
    setupMocks()
    render(<Settings />)

    expect(screen.getByText('Platform Settings')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Plans' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Storage' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vehicle DB' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'T&C' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Announcements' })).toBeInTheDocument()
  })

  // 50.1: Plans tab — displays subscription plans in a table
  it('displays subscription plans in the Plans tab', async () => {
    const plans = [
      makePlan({ id: 'p1', name: 'Starter', monthly_price_nzd: 49 }),
      makePlan({ id: 'p2', name: 'Professional', monthly_price_nzd: 99, is_archived: true }),
    ]
    setupMocks(plans)
    render(<Settings />)

    expect(await screen.findByText('Starter')).toBeInTheDocument()
    expect(screen.getByText('Professional')).toBeInTheDocument()
    expect(screen.getByText('$49.00')).toBeInTheDocument()
    expect(screen.getByText('$99.00')).toBeInTheDocument()
    expect(screen.getByText('Archived')).toBeInTheDocument()
    expect(screen.getByText('2 plans')).toBeInTheDocument()
  })

  // 50.1: Plans tab — create plan button opens modal
  it('opens create plan modal when Create plan button is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await screen.findByText('Starter')
    await user.click(screen.getByRole('button', { name: 'Create plan' }))

    expect(await screen.findByText('Create Plan')).toBeInTheDocument()
    expect(screen.getByLabelText('Plan name')).toBeInTheDocument()
    expect(screen.getByLabelText('Monthly price (NZD)')).toBeInTheDocument()
    expect(screen.getByLabelText('User seats')).toBeInTheDocument()
    expect(screen.getByLabelText('Storage (GB)')).toBeInTheDocument()
    expect(screen.getByLabelText('Carjam lookups')).toBeInTheDocument()
  })

  // 50.1: Plans tab — edit plan opens modal with pre-filled data
  it('opens edit plan modal with pre-filled data', async () => {
    setupMocks([makePlan({ id: 'p1', name: 'Starter', monthly_price_nzd: 49, user_seats: 3 })])
    const user = userEvent.setup()
    render(<Settings />)

    await screen.findByText('Starter')
    await user.click(screen.getByRole('button', { name: 'Edit' }))

    expect(await screen.findByText('Edit Plan')).toBeInTheDocument()
    expect(screen.getByLabelText('Plan name')).toHaveValue('Starter')
    expect(screen.getByLabelText('Monthly price (NZD)')).toHaveValue(49)
    expect(screen.getByLabelText('User seats')).toHaveValue(3)
  })

  // 50.1: Plans tab — archive plan
  it('calls API to archive a plan when Archive button is clicked', async () => {
    setupMocks([makePlan({ id: 'p1', name: 'Starter', is_archived: false })])
    const user = userEvent.setup()
    render(<Settings />)

    await screen.findByText('Starter')
    await user.click(screen.getByRole('button', { name: 'Archive' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/plans/p1', { is_archived: true })
  })

  // 50.1: Plans tab — restore archived plan
  it('calls API to restore an archived plan', async () => {
    setupMocks([makePlan({ id: 'p2', name: 'Old Plan', is_archived: true })])
    const user = userEvent.setup()
    render(<Settings />)

    await screen.findByText('Old Plan')
    await user.click(screen.getByRole('button', { name: 'Restore' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/plans/p2', { is_archived: false })
  })

  // 50.1: Storage tab — displays storage pricing config
  it('displays storage pricing configuration in the Storage tab', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Storage' }))

    expect(await screen.findByText('Storage Tier Pricing')).toBeInTheDocument()
    expect(screen.getByLabelText('Storage increment (GB)')).toHaveValue(5)
    expect(screen.getByLabelText('Price per GB (NZD)')).toHaveValue(2.5)
  })

  // 50.1: Storage tab — save pricing calls API
  it('saves storage pricing when Save pricing is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Storage' }))
    await screen.findByText('Storage Tier Pricing')

    const incrementInput = screen.getByLabelText('Storage increment (GB)')
    await user.clear(incrementInput)
    await user.type(incrementInput, '10')

    await user.click(screen.getByRole('button', { name: 'Save pricing' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/settings', {
      storage_pricing: { increment_gb: 10, price_per_gb_nzd: 2.5 },
    })
  })

  // 50.1: Vehicle DB tab — displays stats
  it('displays vehicle database stats in the Vehicle DB tab', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Vehicle DB' }))

    expect(await screen.findByText('Global Vehicle Database')).toBeInTheDocument()
    expect(screen.getByText('Total records')).toBeInTheDocument()
    expect(screen.getByText('15,420')).toBeInTheDocument()
  })

  // 50.1: Vehicle DB tab — search by rego
  it('searches for a vehicle by registration number', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Vehicle DB' }))
    await screen.findByText('Global Vehicle Database')

    const searchInput = screen.getByLabelText('Search by registration')
    await user.type(searchInput, 'ABC123')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    expect(apiClient.get).toHaveBeenCalledWith('/admin/vehicle-db/ABC123')
    expect(await screen.findByText('Toyota')).toBeInTheDocument()
    expect(screen.getByText('Corolla')).toBeInTheDocument()
  })

  // 50.1: Vehicle DB tab — force refresh
  it('calls refresh API for a vehicle record', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Vehicle DB' }))
    await screen.findByText('Global Vehicle Database')

    await user.type(screen.getByLabelText('Search by registration'), 'ABC123')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await screen.findByText('Toyota')
    await user.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(apiClient.post).toHaveBeenCalledWith('/admin/vehicle-db/ABC123/refresh')
  })

  // 50.1: Vehicle DB tab — delete stale record
  it('calls delete API for a stale vehicle record', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(screen.getByRole('tab', { name: 'Vehicle DB' }))
    await screen.findByText('Global Vehicle Database')

    await user.type(screen.getByLabelText('Search by registration'), 'ABC123')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await screen.findByText('Toyota')
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(apiClient.delete).toHaveBeenCalledWith('/admin/vehicle-db/ABC123')
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

  // 50.2: T&C tab — publishing new version calls API and shows re-accept message
  it('publishes new terms version and shows re-accept notification', async () => {
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
      [makePlan()],
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

  // Loading state
  it('shows loading spinner while plans are loading', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<Settings />)

    expect(screen.getByRole('status', { name: /loading plans/i })).toBeInTheDocument()
  })

  // Error state
  it('shows error banner when plans fail to load', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<Settings />)

    expect(await screen.findByText(/could not load subscription plans/i)).toBeInTheDocument()
  })
})
