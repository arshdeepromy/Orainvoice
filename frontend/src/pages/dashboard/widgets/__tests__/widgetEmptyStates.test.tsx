/**
 * Unit tests for empty states across all widgets.
 *
 * Requirements: 4.4, 5.5, 6.4, 7.6, 8.5, 9.6, 10.4, 11.10
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

import { RecentCustomersWidget } from '../RecentCustomersWidget'
import { TodaysBookingsWidget } from '../TodaysBookingsWidget'
import { PublicHolidaysWidget } from '../PublicHolidaysWidget'
import { InventoryOverviewWidget } from '../InventoryOverviewWidget'
import { CashFlowChartWidget } from '../CashFlowChartWidget'
import { RecentClaimsWidget } from '../RecentClaimsWidget'
import { ActiveStaffWidget } from '../ActiveStaffWidget'
import { ExpiryRemindersWidget } from '../ExpiryRemindersWidget'

const emptySection = { items: [], total: 0 }

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('Widget empty states', () => {
  it('RecentCustomersWidget shows "No recent customers"', () => {
    wrap(
      <RecentCustomersWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No recent customers')).toBeInTheDocument()
  })

  it('TodaysBookingsWidget shows "No bookings for today"', () => {
    wrap(
      <TodaysBookingsWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No bookings for today')).toBeInTheDocument()
  })

  it('PublicHolidaysWidget shows "No upcoming public holidays"', () => {
    wrap(
      <PublicHolidaysWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No upcoming public holidays')).toBeInTheDocument()
  })

  it('InventoryOverviewWidget shows "No inventory items"', () => {
    wrap(
      <InventoryOverviewWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No inventory items')).toBeInTheDocument()
  })

  it('CashFlowChartWidget shows "No financial data available"', () => {
    wrap(
      <CashFlowChartWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No financial data available')).toBeInTheDocument()
  })

  it('RecentClaimsWidget shows "No recent claims"', () => {
    wrap(
      <RecentClaimsWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No recent claims')).toBeInTheDocument()
  })

  it('ActiveStaffWidget shows "No staff currently clocked in"', () => {
    wrap(
      <ActiveStaffWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No staff currently clocked in')).toBeInTheDocument()
  })

  it('ExpiryRemindersWidget shows "No upcoming WOF or service expiries"', () => {
    wrap(
      <ExpiryRemindersWidget data={emptySection} isLoading={false} error={null} />,
    )
    expect(screen.getByText('No upcoming WOF or service expiries')).toBeInTheDocument()
  })
})
