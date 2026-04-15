import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 47.1-47.3
 * - 47.1: Display all organisations in a sortable and searchable table
 * - 47.2: Provision, suspend, reinstate, delete, and move between plans
 * - 47.3: Reason required for suspend/delete, stored in audit log
 */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete },
  }
})

import apiClient from '@/api/client'
import { Organisations } from '../pages/admin/Organisations'
import type { Organisation, Plan } from '../pages/admin/Organisations'

const mockPlans: Plan[] = [
  { id: 'plan-starter', name: 'Starter' },
  { id: 'plan-pro', name: 'Professional' },
  { id: 'plan-enterprise', name: 'Enterprise' },
]

const mockOrgs: Organisation[] = [
  {
    id: 'org-1',
    name: 'Kiwi Motors',
    plan_name: 'Professional',
    plan_id: 'plan-pro',
    status: 'active',
    billing_status: 'current',
    signup_date: '2025-01-10T00:00:00Z',
    storage_used_gb: 2.5,
    storage_quota_gb: 10,
    last_login: '2025-06-20T14:30:00Z',
    next_billing_date: '2025-07-10T00:00:00Z',
    billing_interval: 'monthly',
  },
  {
    id: 'org-2',
    name: 'Auckland Auto',
    plan_name: 'Starter',
    plan_id: 'plan-starter',
    status: 'trial',
    billing_status: 'trial',
    signup_date: '2025-06-01T00:00:00Z',
    storage_used_gb: 0.3,
    storage_quota_gb: 5,
    last_login: '2025-06-19T09:00:00Z',
    next_billing_date: null,
    billing_interval: 'monthly',
  },
  {
    id: 'org-3',
    name: 'Wellington Workshop',
    plan_name: 'Enterprise',
    plan_id: 'plan-enterprise',
    status: 'suspended',
    billing_status: 'unpaid',
    signup_date: '2024-06-15T00:00:00Z',
    storage_used_gb: 8.1,
    storage_quota_gb: 50,
    last_login: null,
    next_billing_date: '2025-04-15T00:00:00Z',
    billing_interval: 'annual',
  },
]

function setupMocks(overrides: { orgs?: Organisation[]; plans?: Plan[] } = {}) {
  const orgs = overrides.orgs ?? mockOrgs
  const plans = overrides.plans ?? mockPlans

  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/admin/organisations') return Promise.resolve({ data: orgs })
    if (url === '/admin/plans') return Promise.resolve({ data: plans })
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'org-new' } })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.delete as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
}

describe('Admin Organisations page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<Organisations />)
    expect(screen.getByRole('status', { name: 'Loading organisations' })).toBeInTheDocument()
  })

  it('shows error banner when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<Organisations />)
    expect(await screen.findByText(/couldn't load the organisations list/i)).toBeInTheDocument()
  })

  // 47.1: Sortable and searchable table with org details
  it('displays organisations table with name, plan, status, and dates', async () => {
    setupMocks()
    render(<Organisations />)
    expect(await screen.findByText('Kiwi Motors')).toBeInTheDocument()
    expect(screen.getByText('Auckland Auto')).toBeInTheDocument()
    expect(screen.getByText('Wellington Workshop')).toBeInTheDocument()
    expect(screen.getByText('Professional')).toBeInTheDocument()
    expect(screen.getByText('Starter')).toBeInTheDocument()
    expect(screen.getByText('Enterprise')).toBeInTheDocument()
    // Status badges (use getAllBy since status names also appear in the filter dropdown)
    const table = screen.getByRole('grid')
    expect(within(table).getByText('Active')).toBeInTheDocument()
    expect(within(table).getAllByText('Trial').length).toBeGreaterThanOrEqual(1)
    expect(within(table).getByText('Suspended')).toBeInTheDocument()
  })

  // 47.1: Search filters organisations by name
  it('filters organisations by search text', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')

    await user.type(screen.getByPlaceholderText('Search by name or plan...'), 'Kiwi')

    expect(screen.getByText('Kiwi Motors')).toBeInTheDocument()
    expect(screen.queryByText('Auckland Auto')).not.toBeInTheDocument()
    expect(screen.queryByText('Wellington Workshop')).not.toBeInTheDocument()
  })

  // 47.1: Status filter
  it('filters organisations by status', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'suspended')

    expect(screen.queryByText('Kiwi Motors')).not.toBeInTheDocument()
    expect(screen.queryByText('Auckland Auto')).not.toBeInTheDocument()
    expect(screen.getByText('Wellington Workshop')).toBeInTheDocument()
  })

  // 47.2: Provision new organisation
  it('opens provision modal and submits new organisation', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')

    await user.click(screen.getByRole('button', { name: 'Provision new organisation' }))

    expect(screen.getByText('Provision new organisation', { selector: 'h2' })).toBeInTheDocument()

    await user.type(screen.getByLabelText('Organisation name'), 'New Workshop')
    await user.selectOptions(screen.getByLabelText('Subscription plan'), 'plan-pro')
    await user.type(screen.getByLabelText('Org Admin email'), 'admin@newworkshop.co.nz')

    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Provision organisation' }))

    expect(apiClient.post).toHaveBeenCalledWith('/admin/organisations', {
      name: 'New Workshop',
      plan_id: 'plan-pro',
      admin_email: 'admin@newworkshop.co.nz',
    })
  })

  // 47.2: Provision validation — required fields
  it('shows validation errors when provision form is submitted empty', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')

    await user.click(screen.getByRole('button', { name: 'Provision new organisation' }))
    const modal = screen.getByRole('dialog')
    // Clear the pre-selected plan to trigger validation
    await user.selectOptions(screen.getByLabelText('Subscription plan'), 'plan-starter')
    await user.click(within(modal).getByRole('button', { name: 'Provision organisation' }))

    expect(screen.getByText('Organisation name is required')).toBeInTheDocument()
    expect(screen.getByText('Admin email is required')).toBeInTheDocument()
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  // 47.2 + 47.3: Suspend requires reason
  it('opens suspend modal and requires reason', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')

    // Click suspend on the first active org
    const suspendButtons = screen.getAllByRole('button', { name: 'Suspend' })
    await user.click(suspendButtons[0])

    expect(screen.getByText('Suspend organisation', { selector: 'h2' })).toBeInTheDocument()
    const modal = screen.getByRole('dialog')
    expect(within(modal).getByText(/Kiwi Motors/)).toBeInTheDocument()

    // Try to submit without reason
    await user.click(within(modal).getByRole('button', { name: 'Suspend' }))
    expect(screen.getByText('A reason is required to suspend an organisation')).toBeInTheDocument()

    // Enter reason and submit
    await user.type(screen.getByLabelText('Reason for suspension'), 'Non-payment of fees')
    await user.click(within(modal).getByRole('button', { name: 'Suspend' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/organisations/org-1', {
      status: 'suspended',
      reason: 'Non-payment of fees',
    })
  })

  // 47.2: Reinstate suspended organisation
  it('reinstates a suspended organisation', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Wellington Workshop')

    await user.click(screen.getByRole('button', { name: 'Reinstate' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/organisations/org-3', {
      status: 'active',
    })
  })

  // 47.2 + 47.3: Delete with multi-step confirmation and reason
  it('opens delete modal with multi-step confirmation requiring reason and name', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    await user.click(deleteButtons[0])

    // Step 1: Reason
    expect(screen.getByText('Delete organisation', { selector: 'h2' })).toBeInTheDocument()
    expect(screen.getByText(/This action is permanent/)).toBeInTheDocument()

    // Try without reason
    const modal = screen.getByRole('dialog')
    await user.click(within(modal).getByRole('button', { name: 'Continue' }))
    expect(screen.getByText('A reason is required to delete an organisation')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Reason for deletion'), 'Requested by owner')
    await user.click(within(modal).getByRole('button', { name: 'Continue' }))

    // Step 2: Confirm by typing org name
    expect(screen.getByText(/type the organisation name/)).toBeInTheDocument()

    // Wrong name
    await user.type(screen.getByLabelText('Confirm organisation name'), 'Wrong Name')
    await user.click(within(modal).getByRole('button', { name: 'Delete permanently' }))
    expect(screen.getByText(/Please type "Kiwi Motors" to confirm/)).toBeInTheDocument()

    // Correct name
    await user.clear(screen.getByLabelText('Confirm organisation name'))
    await user.type(screen.getByLabelText('Confirm organisation name'), 'Kiwi Motors')
    await user.click(within(modal).getByRole('button', { name: 'Delete permanently' }))

    expect(apiClient.delete).toHaveBeenCalledWith('/admin/organisations/org-1', {
      data: { reason: 'Requested by owner' },
    })
  })

  // 47.2: Move between plans
  it('opens move plan modal and changes plan', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')

    const movePlanButtons = screen.getAllByRole('button', { name: 'Move plan' })
    await user.click(movePlanButtons[0])

    expect(screen.getByText('Move to different plan', { selector: 'h2' })).toBeInTheDocument()
    const modal = screen.getByRole('dialog')
    expect(within(modal).getByText(/Kiwi Motors/)).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('New plan'), 'plan-enterprise')
    await user.click(within(modal).getByRole('button', { name: 'Move plan' }))

    expect(apiClient.put).toHaveBeenCalledWith('/admin/organisations/org-1', {
      plan_id: 'plan-enterprise',
    })
  })

  // 47.2: Suspended org shows Reinstate but not Suspend
  it('shows reinstate button for suspended orgs and hides suspend', async () => {
    setupMocks()
    render(<Organisations />)
    await screen.findByText('Wellington Workshop')

    // Wellington Workshop is suspended — should have Reinstate, not Suspend
    expect(screen.getByRole('button', { name: 'Reinstate' })).toBeInTheDocument()
    // Only 2 suspend buttons (for the 2 non-suspended orgs)
    expect(screen.getAllByRole('button', { name: 'Suspend' })).toHaveLength(2)
  })

  // 47.1: Storage usage displayed
  it('displays storage usage for each organisation', async () => {
    setupMocks()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')
    expect(screen.getByText('2.5 / 10 GB')).toBeInTheDocument()
    expect(screen.getByText('0.3 / 5 GB')).toBeInTheDocument()
    expect(screen.getByText('8.1 / 50 GB')).toBeInTheDocument()
  })

  // 47.1: Billing status badges
  it('displays billing status badges', async () => {
    setupMocks()
    render(<Organisations />)
    await screen.findByText('Kiwi Motors')
    expect(screen.getByText('Current')).toBeInTheDocument()
    expect(screen.getByText('Unpaid')).toBeInTheDocument()
  })

  // Empty state
  it('shows empty table when no organisations exist', async () => {
    setupMocks({ orgs: [] })
    render(<Organisations />)
    expect(await screen.findByText('No data available')).toBeInTheDocument()
  })
})
