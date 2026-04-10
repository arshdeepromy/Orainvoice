import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Validates: Requirements 44.1, 44.2, 41.3
 * - 44.1: Billing page displays plan, next billing date, estimated invoice, storage, Carjam, past invoices, payment method update
 * - 44.2: Plain language without accounting jargon
 * - 41.3: Trial countdown in Org_Admin dashboard
 */

// Mock apiClient before importing the component
vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  return {
    default: { get: mockGet, post: mockPost, put: mockPut },
  }
})

import apiClient from '@/api/client'
import { Billing } from '../pages/settings/Billing'

const mockBillingData = {
  plan: {
    name: 'Pro',
    monthly_price_nzd: 99,
    user_seats: 10,
    storage_quota_gb: 5,
    carjam_lookups_included: 200,
    enabled_modules: ['invoices', 'quotes'],
  },
  status: 'active' as const,
  trial_ends_at: null,
  next_billing_date: '2025-02-15T00:00:00Z',
  estimated_next_invoice: {
    plan_fee: 99,
    storage_addons: 10,
    carjam_overage: 5,
    total: 114,
  },
  storage: {
    used_bytes: 2_684_354_560, // 2.5 GB
    quota_gb: 5,
    avg_invoice_bytes: 5120, // ~5 KB per invoice
  },
  carjam: {
    lookups_this_month: 180,
    included: 200,
  },
  storage_addon_price_per_gb: 5,
}

const mockInvoices = [
  { id: 'inv-1', date: '2025-01-15T00:00:00Z', amount: 99, status: 'paid', pdf_url: 'https://example.com/inv1.pdf' },
  { id: 'inv-2', date: '2024-12-15T00:00:00Z', amount: 104, status: 'paid', pdf_url: 'https://example.com/inv2.pdf' },
]

function setupMocks(billingOverrides = {}, invoicesOverride?: typeof mockInvoices) {
  const billing = { ...mockBillingData, ...billingOverrides }
  ;(apiClient.get as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
    if (url === '/billing') return Promise.resolve({ data: billing })
    if (url === '/billing/invoices') return Promise.resolve({ data: invoicesOverride ?? mockInvoices })
    return Promise.reject(new Error('Unknown URL'))
  })
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} })
  ;(apiClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { url: 'https://stripe.com/update' } })
}

describe('Billing settings page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading spinner initially', () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {})) // never resolves
    render(<Billing />)
    expect(screen.getByRole('status', { name: 'Loading billing information' })).toBeInTheDocument()
  })

  it('displays current plan name and price', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText('Pro')).toBeInTheDocument()
    expect(screen.getByText(/\$99\.00 \/ month/)).toBeInTheDocument()
  })

  it('displays plan features in plain language', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText('Up to 10 users')).toBeInTheDocument()
    expect(screen.getByText('5 GB storage')).toBeInTheDocument()
    expect(screen.getByText('200 Carjam lookups / month')).toBeInTheDocument()
  })

  it('shows active status badge', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText('Active')).toBeInTheDocument()
  })

  it('displays next billing date', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText(/15 February 2025/)).toBeInTheDocument()
  })

  it('shows estimated next invoice breakdown', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText('Plan fee')).toBeInTheDocument()
    expect(screen.getByText('Extra storage')).toBeInTheDocument()
    expect(screen.getByText('Carjam overage')).toBeInTheDocument()
    expect(screen.getByText('Estimated total')).toBeInTheDocument()
  })

  it('displays storage usage bar with percentage', async () => {
    setupMocks()
    render(<Billing />)
    const progressbar = await screen.findByRole('progressbar', { name: /Storage usage/ })
    expect(progressbar).toHaveAttribute('aria-valuenow', '50')
    expect(screen.getByText('50% used')).toBeInTheDocument()
  })

  it('shows estimated invoices remaining', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText(/invoices worth of space remaining/)).toBeInTheDocument()
  })

  it('displays Carjam usage', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText('180')).toBeInTheDocument()
    expect(screen.getByText('of 200 included')).toBeInTheDocument()
  })

  it('shows Carjam overage warning when over limit', async () => {
    setupMocks({
      carjam: { lookups_this_month: 220, included: 200 },
    })
    render(<Billing />)
    expect(await screen.findByText(/20 extra lookups/)).toBeInTheDocument()
  })

  it('renders past invoices table with download links', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByText('Past invoices')).toBeInTheDocument()
    const links = screen.getAllByText('Download PDF')
    expect(links).toHaveLength(2)
  })

  it('has update payment method button', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByRole('button', { name: 'Update payment method' })).toBeInTheDocument()
  })

  it('has upgrade and downgrade buttons', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByRole('button', { name: 'Upgrade plan' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Downgrade plan' })).toBeInTheDocument()
  })

  it('has buy more storage button', async () => {
    setupMocks()
    render(<Billing />)
    expect(await screen.findByRole('button', { name: 'Buy more storage' })).toBeInTheDocument()
  })

  it('shows trial countdown when on trial', async () => {
    const futureDate = new Date()
    futureDate.setDate(futureDate.getDate() + 10)
    setupMocks({
      status: 'trial',
      trial_ends_at: futureDate.toISOString(),
    })
    render(<Billing />)
    expect(await screen.findByText(/days left in your free trial/)).toBeInTheDocument()
    expect(screen.getByText('Trial')).toBeInTheDocument()
  })

  it('shows urgent trial warning when 1 day left', async () => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    setupMocks({
      status: 'trial',
      trial_ends_at: tomorrow.toISOString(),
    })
    render(<Billing />)
    expect(await screen.findByText(/trial ends tomorrow/)).toBeInTheDocument()
  })

  it('shows grace period warning', async () => {
    setupMocks({ status: 'grace_period' })
    render(<Billing />)
    expect(await screen.findByText(/payment is overdue/i)).toBeInTheDocument()
  })

  it('shows storage warning at 90%+ usage', async () => {
    setupMocks({
      storage: {
        used_bytes: 4_831_838_208, // ~4.5 GB of 5 GB = 90%
        quota_gb: 5,
        avg_invoice_bytes: 5120,
      },
    })
    render(<Billing />)
    expect(await screen.findByText(/almost out of storage/)).toBeInTheDocument()
  })

  it('shows error banner when API fails', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network error'))
    render(<Billing />)
    expect(await screen.findByText(/couldn't load your billing information/i)).toBeInTheDocument()
  })

  it('opens storage add-on modal on buy click', async () => {
    setupMocks()
    const user = userEvent.setup()
    render(<Billing />)
    const buyBtn = await screen.findByRole('button', { name: 'Buy more storage' })
    await user.click(buyBtn)
    expect(screen.getByText(/Extra storage costs/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm purchase' })).toBeInTheDocument()
  })
})
