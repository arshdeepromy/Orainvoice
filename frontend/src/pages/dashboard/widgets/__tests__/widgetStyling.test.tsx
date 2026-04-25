/**
 * Unit tests for claim status badge colours and inventory low-stock warning.
 *
 * Requirements: 9.3, 7.3, 14.4
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import { RecentClaimsWidget } from '../RecentClaimsWidget'
import { InventoryOverviewWidget } from '../InventoryOverviewWidget'

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('RecentClaimsWidget — status badge colours', () => {
  const makeClaim = (status: string) => ({
    claim_id: `claim-${status}`,
    reference: `REF-${status}`,
    customer_name: `Customer ${status}`,
    claim_date: '2025-01-15',
    status: status as 'open' | 'investigating' | 'approved' | 'rejected' | 'resolved',
  })

  it('uses green for resolved status', () => {
    wrap(
      <RecentClaimsWidget
        data={{ items: [makeClaim('resolved')], total: 1 }}
        isLoading={false}
        error={null}
      />,
    )
    const badge = screen.getByText('Resolved')
    expect(badge.className).toContain('bg-green-100')
    expect(badge.className).toContain('text-green-700')
  })

  it('uses amber for investigating status', () => {
    wrap(
      <RecentClaimsWidget
        data={{ items: [makeClaim('investigating')], total: 1 }}
        isLoading={false}
        error={null}
      />,
    )
    const badge = screen.getByText('Investigating')
    expect(badge.className).toContain('bg-amber-100')
    expect(badge.className).toContain('text-amber-700')
  })

  it('uses red for rejected status', () => {
    wrap(
      <RecentClaimsWidget
        data={{ items: [makeClaim('rejected')], total: 1 }}
        isLoading={false}
        error={null}
      />,
    )
    const badge = screen.getByText('Rejected')
    expect(badge.className).toContain('bg-red-100')
    expect(badge.className).toContain('text-red-700')
  })

  it('uses grey for open status', () => {
    wrap(
      <RecentClaimsWidget
        data={{ items: [makeClaim('open')], total: 1 }}
        isLoading={false}
        error={null}
      />,
    )
    const badge = screen.getByText('Open')
    expect(badge.className).toContain('bg-gray-100')
    expect(badge.className).toContain('text-gray-700')
  })
})

describe('InventoryOverviewWidget — low-stock warning colour', () => {
  it('highlights low-stock count in amber warning colour', () => {
    wrap(
      <InventoryOverviewWidget
        data={{
          items: [
            { category: 'tyres', total_count: 50, low_stock_count: 5 },
            { category: 'parts', total_count: 100, low_stock_count: 0 },
          ],
          total: 2,
        }}
        isLoading={false}
        error={null}
      />,
    )

    // The "5 low stock" text should have amber colour
    const lowStockText = screen.getByText('5 low stock')
    expect(lowStockText.className).toContain('text-amber-600')

    // The "All stocked" text should be grey (no warning)
    const allStockedText = screen.getByText('All stocked')
    expect(allStockedText.className).toContain('text-gray-400')
  })
})
