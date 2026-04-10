import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 1.3, 5.6
 * - 1.3: SMS fields (per_sms_cost_nzd, sms_included_quota) accepted on plan create/update
 * - 5.6: Admin UI displays SMS package tiers in a table with add/remove rows
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
import { SubscriptionPlans, type Plan, type ModuleInfo } from '../pages/admin/SubscriptionPlans'

/* ── Helpers ── */

function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: 'plan-1',
    name: 'Starter',
    monthly_price_nzd: 49,
    user_seats: 5,
    storage_quota_gb: 10,
    carjam_lookups_included: 0,
    per_carjam_lookup_cost_nzd: 0,
    enabled_modules: ['core'],
    is_public: true,
    is_archived: false,
    storage_tier_pricing: [],
    trial_duration: 0,
    trial_duration_unit: 'days',
    sms_included: false,
    per_sms_cost_nzd: 0,
    sms_included_quota: 0,
    sms_package_pricing: [],
    interval_config: [],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

const MODULES: ModuleInfo[] = [
  { slug: 'core', display_name: 'Core', description: 'Core module', category: 'core', is_core: true, dependencies: null },
]

function setupMocks(plans: Plan[] = [makePlan()]) {
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/plans') return Promise.resolve({ data: { plans } })
    if (url.includes('/admin/settings')) return Promise.resolve({ data: { storage_pricing: { increment_gb: 1, price_per_gb_nzd: 0.5 } } })
    if (url.includes('/modules/registry')) return Promise.resolve({ data: { modules: MODULES } })
    return Promise.resolve({ data: {} })
  })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
}

describe('SMS Plan Form Fields', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // 1.3: SMS fields render when sms_included is toggled on
  it('shows SMS quota and cost fields when sms_included checkbox is toggled on', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<SubscriptionPlans />)

    // Wait for page to load and click Create plan
    await screen.findByText('Subscription Management')
    await user.click(screen.getByRole('button', { name: 'Create plan' }))

    // Modal should open — SMS fields should NOT be visible initially
    const modal = await screen.findByRole('dialog')
    expect(within(modal).queryByLabelText('Included SMS quota')).not.toBeInTheDocument()
    expect(within(modal).queryByLabelText(/Per-SMS cost/)).not.toBeInTheDocument()

    // Toggle SMS on
    await user.click(within(modal).getByLabelText(/Include SMS notifications/))

    // SMS fields should now be visible
    expect(within(modal).getByLabelText('Included SMS quota')).toBeInTheDocument()
    expect(within(modal).getByLabelText(/Per-SMS cost/)).toBeInTheDocument()
  })

  // 1.3: SMS fields hidden when sms_included is toggled off
  it('hides SMS fields when sms_included checkbox is toggled off', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<SubscriptionPlans />)

    await screen.findByText('Subscription Management')
    await user.click(screen.getByRole('button', { name: 'Create plan' }))

    const modal = await screen.findByRole('dialog')

    // Toggle on then off
    await user.click(within(modal).getByLabelText(/Include SMS notifications/))
    expect(within(modal).getByLabelText('Included SMS quota')).toBeInTheDocument()

    await user.click(within(modal).getByLabelText(/Include SMS notifications/))
    expect(within(modal).queryByLabelText('Included SMS quota')).not.toBeInTheDocument()
  })

  // 5.6: SMS package tier table — add tier
  it('adds an SMS package tier row when Add button is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<SubscriptionPlans />)

    await screen.findByText('Subscription Management')
    await user.click(screen.getByRole('button', { name: 'Create plan' }))

    const modal = await screen.findByRole('dialog')
    await user.click(within(modal).getByLabelText(/Include SMS notifications/))

    // Initially no tiers
    expect(within(modal).getByText('No SMS package tiers configured.')).toBeInTheDocument()

    // Add a tier
    await user.click(within(modal).getByRole('button', { name: 'Add SMS package tier' }))

    // Tier row should appear with default values
    expect(within(modal).queryByText('No SMS package tiers configured.')).not.toBeInTheDocument()
    const tierNameInputs = within(modal).getAllByLabelText('Tier name')
    // At least one tier name input for SMS (there may also be storage tier name inputs)
    expect(tierNameInputs.length).toBeGreaterThanOrEqual(1)
  })

  // 5.6: SMS package tier table — remove tier
  it('removes an SMS package tier row when Remove button is clicked', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<SubscriptionPlans />)

    await screen.findByText('Subscription Management')
    await user.click(screen.getByRole('button', { name: 'Create plan' }))

    const modal = await screen.findByRole('dialog')
    await user.click(within(modal).getByLabelText(/Include SMS notifications/))

    // Add two tiers
    await user.click(within(modal).getByRole('button', { name: 'Add SMS package tier' }))
    await user.click(within(modal).getByRole('button', { name: 'Add SMS package tier' }))

    // Should have 2 Remove buttons for SMS tiers
    const removeButtons = within(modal).getAllByRole('button', { name: 'Remove' })
    expect(removeButtons.length).toBe(2)

    // Remove one
    await user.click(removeButtons[0])

    // Should have 1 Remove button left
    const remainingRemoveButtons = within(modal).getAllByRole('button', { name: 'Remove' })
    expect(remainingRemoveButtons.length).toBe(1)
  })

  // 1.3: Form submission includes SMS fields
  it('includes SMS fields in the API call when creating a plan with SMS enabled', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<SubscriptionPlans />)

    await screen.findByText('Subscription Management')
    await user.click(screen.getByRole('button', { name: 'Create plan' }))

    const modal = await screen.findByRole('dialog')

    // Fill required fields
    await user.clear(within(modal).getByLabelText('Plan name'))
    await user.type(within(modal).getByLabelText('Plan name'), 'Pro Plan')

    // Enable SMS
    await user.click(within(modal).getByLabelText(/Include SMS notifications/))

    // Set SMS quota and cost
    const quotaInput = within(modal).getByLabelText('Included SMS quota')
    await user.clear(quotaInput)
    await user.type(quotaInput, '500')

    const costInput = within(modal).getByLabelText(/Per-SMS cost/)
    await user.clear(costInput)
    await user.type(costInput, '0.08')

    // Add an SMS package tier
    await user.click(within(modal).getByRole('button', { name: 'Add SMS package tier' }))

    // Submit the form
    await user.click(within(modal).getByRole('button', { name: 'Create plan' }))

    // Verify the API was called with SMS fields
    expect(apiClient.post).toHaveBeenCalledWith(
      '/admin/plans',
      expect.objectContaining({
        name: 'Pro Plan',
        sms_included: true,
        sms_included_quota: 500,
        per_sms_cost_nzd: 0.08,
        sms_package_pricing: expect.arrayContaining([
          expect.objectContaining({
            tier_name: expect.any(String),
            sms_quantity: expect.any(Number),
            price_nzd: expect.any(Number),
          }),
        ]),
      }),
    )
  })

  // 1.3: Edit plan populates SMS fields from existing plan data
  it('populates SMS fields when editing a plan with SMS enabled', async () => {
    const smsPlan = makePlan({
      sms_included: true,
      per_sms_cost_nzd: 0.12,
      sms_included_quota: 200,
      sms_package_pricing: [
        { tier_name: 'Bulk 500', sms_quantity: 500, price_nzd: 40 },
      ],
    })
    setupMocks([smsPlan])
    const user = userEvent.setup()
    render(<SubscriptionPlans />)

    await screen.findByText('Subscription Management')

    // Click Edit on the plan
    await user.click(screen.getByRole('button', { name: 'Edit' }))

    const modal = await screen.findByRole('dialog')

    // SMS checkbox should be checked
    const smsCheckbox = within(modal).getByLabelText(/Include SMS notifications/) as HTMLInputElement
    expect(smsCheckbox.checked).toBe(true)

    // SMS fields should be visible with correct values (number inputs return numbers)
    expect(within(modal).getByLabelText('Included SMS quota')).toHaveValue(200)
    expect(within(modal).getByLabelText(/Per-SMS cost/)).toHaveValue(0.12)

    // SMS package tier should be present
    expect(within(modal).getByDisplayValue('Bulk 500')).toBeInTheDocument()
    expect(within(modal).getByDisplayValue('500')).toBeInTheDocument()
    expect(within(modal).getByDisplayValue('40')).toBeInTheDocument()
  })
})


/* ------------------------------------------------------------------ */
/*  SmsUsage page tests                                                */
/* ------------------------------------------------------------------ */

import SmsUsage from '../pages/reports/SmsUsage'

/**
 * Validates: Requirements 7.2, 7.3
 * - 7.2: SmsUsage report page displays total SMS sent, included in plan, overage count, overage charge, daily chart
 * - 7.3: Active SMS package purchases with remaining credits displayed on SMS usage report page
 */

const mockSmsUsageData = {
  total_sent: 320,
  included_in_plan: 200,
  package_credits_remaining: 50,
  effective_quota: 250,
  overage_count: 70,
  overage_charge_nzd: 5.6,
  per_sms_cost_nzd: 0.08,
  reset_at: '2024-02-01T00:00:00Z',
  daily_breakdown: [
    { date: '2024-01-15', sms_count: 18 },
    { date: '2024-01-16', sms_count: 25 },
  ],
}

const mockSmsPackages = [
  {
    id: 'pkg-1',
    tier_name: 'Bulk 500',
    sms_quantity: 500,
    price_nzd: 40,
    credits_remaining: 30,
    purchased_at: '2024-01-10T00:00:00Z',
  },
  {
    id: 'pkg-2',
    tier_name: 'Bulk 1000',
    sms_quantity: 1000,
    price_nzd: 70,
    credits_remaining: 20,
    purchased_at: '2024-01-12T00:00:00Z',
  },
]

const mockSmsUsageWithTiers = {
  sms_package_pricing: [
    { tier_name: 'Bulk 500', sms_quantity: 500, price_nzd: 40 },
    { tier_name: 'Bulk 1000', sms_quantity: 1000, price_nzd: 70 },
  ],
}

function setupSmsUsageMocks(opts: {
  usageData?: typeof mockSmsUsageData
  packages?: typeof mockSmsPackages
  tiers?: typeof mockSmsUsageWithTiers
} = {}) {
  const usageData = opts.usageData ?? mockSmsUsageData
  const packages = opts.packages ?? mockSmsPackages
  const tierData = opts.tiers ?? mockSmsUsageWithTiers

  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/reports/sms-usage') return Promise.resolve({ data: usageData })
    if (url === '/org/sms-packages') return Promise.resolve({ data: packages })
    if (url === '/org/sms-usage') return Promise.resolve({ data: tierData })
    return Promise.resolve({ data: {} })
  })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
}

describe('SmsUsage Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // 7.2: Summary cards render with correct values
  it('renders summary cards with correct values', async () => {
    setupSmsUsageMocks()
    render(<SmsUsage />)

    expect(await screen.findByText('Total SMS Sent')).toBeInTheDocument()
    expect(screen.getByText('320')).toBeInTheDocument()

    expect(screen.getByText('Included in Plan')).toBeInTheDocument()
    expect(screen.getByText('200')).toBeInTheDocument()

    expect(screen.getByText('Overage Count')).toBeInTheDocument()
    expect(screen.getByText('70')).toBeInTheDocument()

    expect(screen.getByText('Overage Charge')).toBeInTheDocument()
    // The fmt() function uses toLocaleString — match the rendered text flexibly
    expect(screen.getByText((_content, el) =>
      el?.tagName === 'P' && el.classList.contains('text-red-600') && /5\.60/.test(el.textContent ?? '')
    )).toBeInTheDocument()
  })

  // 7.2: Daily chart renders when daily_breakdown data is present
  it('renders daily breakdown chart when data is present', async () => {
    setupSmsUsageMocks()
    render(<SmsUsage />)

    await screen.findByText('Total SMS Sent')
    expect(screen.getByText('Daily SMS Sent')).toBeInTheDocument()
    // SimpleBarChart renders with role="img" and aria-label
    expect(screen.getByRole('img', { name: 'Daily SMS sent' })).toBeInTheDocument()
  })

  // 7.3: Active packages section renders with package data
  it('renders active packages with remaining credits', async () => {
    setupSmsUsageMocks()
    render(<SmsUsage />)

    await screen.findByText('Total SMS Sent')
    expect(screen.getByText('Active SMS Packages')).toBeInTheDocument()
    // Tier names appear in both the packages table and purchase tiers section
    const bulk500 = screen.getAllByText('Bulk 500')
    expect(bulk500.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('30 / 500')).toBeInTheDocument()
    const bulk1000 = screen.getAllByText('Bulk 1000')
    expect(bulk1000.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('20 / 1000')).toBeInTheDocument()
  })

  // 7.3: "No active SMS packages" message when no packages exist
  it('shows "No active SMS packages." when no packages exist', async () => {
    setupSmsUsageMocks({ packages: [] })
    render(<SmsUsage />)

    await screen.findByText('Total SMS Sent')
    expect(screen.getByText('No active SMS packages.')).toBeInTheDocument()
  })

  // 7.3: Purchase dialog opens when Purchase button is clicked and submits correctly
  it('opens purchase dialog and submits purchase', async () => {
    setupSmsUsageMocks()
    const user = userEvent.setup()
    render(<SmsUsage />)

    await screen.findByText('Total SMS Sent')

    // Find and click the first Purchase button (for Bulk 500 tier)
    const purchaseButtons = screen.getAllByRole('button', { name: 'Purchase' })
    expect(purchaseButtons.length).toBe(2)
    await user.click(purchaseButtons[0])

    // Confirmation dialog should appear
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByRole('heading', { name: 'Confirm Purchase' })).toBeInTheDocument()
    expect(within(dialog).getByText(/Bulk 500/)).toBeInTheDocument()
    expect(within(dialog).getByText(/500 SMS credits/)).toBeInTheDocument()

    // Click Confirm Purchase button
    await user.click(within(dialog).getByRole('button', { name: 'Confirm Purchase' }))

    // Verify the API was called with the correct tier
    expect(apiClient.post).toHaveBeenCalledWith('/org/sms-packages/purchase', { tier_name: 'Bulk 500' })
  })
})
