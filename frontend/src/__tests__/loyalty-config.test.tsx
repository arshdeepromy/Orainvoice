import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirement 38 — Loyalty Module, Task 41.11
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
import LoyaltyConfig from '../pages/loyalty/LoyaltyConfig'

const mockConfig = {
  id: 'cfg-1',
  org_id: 'org-1',
  earn_rate: '1.5000',
  redemption_rate: '0.0100',
  is_active: true,
  created_at: '2025-01-15T10:00:00Z',
  updated_at: '2025-01-15T10:00:00Z',
}

const mockTiers = [
  { id: 't1', org_id: 'org-1', name: 'Bronze', threshold_points: 100,
    discount_percent: '5.00', benefits: {}, display_order: 0 },
  { id: 't2', org_id: 'org-1', name: 'Gold', threshold_points: 1000,
    discount_percent: '10.00', benefits: {}, display_order: 1 },
]

const mockBalance = {
  customer_id: 'cust-1',
  total_points: 750,
  current_tier: mockTiers[0],
  next_tier: mockTiers[1],
  points_to_next_tier: 250,
  transactions: [
    { id: 'tx1', transaction_type: 'earn', points: 500, balance_after: 500,
      reference_type: 'invoice', created_at: '2025-01-10T10:00:00Z' },
    { id: 'tx2', transaction_type: 'earn', points: 250, balance_after: 750,
      reference_type: 'invoice', created_at: '2025-01-12T10:00:00Z' },
  ],
}

describe('LoyaltyConfig', () => {
  beforeEach(() => { vi.clearAllMocks() })

  function setupMocks() {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockImplementation((url: string) => {
        if (url.includes('/tiers')) return Promise.resolve({ data: mockTiers })
        if (url.includes('/config')) return Promise.resolve({ data: mockConfig })
        if (url.includes('/customers/')) return Promise.resolve({ data: mockBalance })
        return Promise.resolve({ data: [] })
      })
  }

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<LoyaltyConfig />)
    expect(screen.getByRole('status', { name: 'Loading loyalty settings' })).toBeInTheDocument()
  })

  it('displays loyalty tiers in a table', async () => {
    setupMocks()
    render(<LoyaltyConfig />)

    const table = await screen.findByRole('grid', { name: 'Loyalty tiers list' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 tiers
    expect(screen.getByTestId('tier-row-Bronze')).toHaveTextContent('Bronze')
    expect(screen.getByTestId('tier-row-Gold')).toHaveTextContent('Gold')
  })

  it('displays config form with current values', async () => {
    setupMocks()
    render(<LoyaltyConfig />)

    await screen.findByRole('grid', { name: 'Loyalty tiers list' })
    const earnInput = screen.getByLabelText('Earn Rate (points per $1)') as HTMLInputElement
    expect(earnInput.value).toBe('1.5000')
  })

  it('submits config update', async () => {
    setupMocks()
    ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: mockConfig })
    render(<LoyaltyConfig />)
    await screen.findByRole('grid', { name: 'Loyalty tiers list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Save loyalty config' }))

    expect(apiClient.put).toHaveBeenCalledWith('/api/v2/loyalty/config', expect.objectContaining({
      earn_rate: 1.5,
      is_active: true,
    }))
  })

  it('shows add tier form when button clicked', async () => {
    setupMocks()
    render(<LoyaltyConfig />)
    await screen.findByRole('grid', { name: 'Loyalty tiers list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add tier' }))

    expect(screen.getByRole('form', { name: 'Create tier form' })).toBeInTheDocument()
  })

  it('submits new tier', async () => {
    setupMocks()
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { id: 'new' } })
    render(<LoyaltyConfig />)
    await screen.findByRole('grid', { name: 'Loyalty tiers list' })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add tier' }))
    await user.type(screen.getByLabelText('Tier Name'), 'Silver')
    await user.type(screen.getByLabelText('Threshold Points'), '500')
    await user.click(screen.getByRole('button', { name: 'Save tier' }))

    expect(apiClient.post).toHaveBeenCalledWith('/api/v2/loyalty/tiers', expect.objectContaining({
      name: 'Silver',
      threshold_points: 500,
    }))
  })

  it('looks up customer balance', async () => {
    setupMocks()
    render(<LoyaltyConfig />)
    await screen.findByRole('grid', { name: 'Loyalty tiers list' })

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Customer ID'), 'cust-1')
    await user.click(screen.getByRole('button', { name: 'Look up balance' }))

    const result = await screen.findByTestId('customer-balance-result')
    expect(result).toBeInTheDocument()
    expect(screen.getByTestId('balance-points')).toHaveTextContent('750')
    expect(screen.getByTestId('balance-tier')).toHaveTextContent('Bronze')
    expect(screen.getByTestId('balance-next-tier')).toHaveTextContent('Gold')
    expect(screen.getByTestId('balance-next-tier')).toHaveTextContent('250 pts needed')
  })

  it('displays transaction history in balance result', async () => {
    setupMocks()
    render(<LoyaltyConfig />)
    await screen.findByRole('grid', { name: 'Loyalty tiers list' })

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Customer ID'), 'cust-1')
    await user.click(screen.getByRole('button', { name: 'Look up balance' }))

    const txTable = await screen.findByRole('grid', { name: 'Transaction history' })
    const rows = within(txTable).getAllByRole('row')
    expect(rows).toHaveLength(3) // header + 2 transactions
  })

  it('shows error when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<LoyaltyConfig />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load loyalty settings')
  })

  it('shows empty state when no tiers', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>)
      .mockImplementation((url: string) => {
        if (url.includes('/tiers')) return Promise.resolve({ data: [] })
        if (url.includes('/config')) return Promise.resolve({ data: mockConfig })
        return Promise.resolve({ data: [] })
      })
    render(<LoyaltyConfig />)
    expect(await screen.findByText('No tiers configured')).toBeInTheDocument()
  })
})
