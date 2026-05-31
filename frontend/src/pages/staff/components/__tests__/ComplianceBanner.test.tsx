/**
 * Unit tests for ComplianceBanner.
 *
 * Refs: Staff Management Phase 1 — R6, G1, G3
 */

import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ComplianceBanner, {
  type ComplianceSummary,
  StaffRowDots,
} from '../ComplianceBanner'

const ZERO_SUMMARY: ComplianceSummary = {
  probation_ending_soon: 0,
  visa_expiring_soon: 0,
  pay_review_due: 0,
  below_minimum_wage: 0,
  missing_agreement: 0,
  missing_employee_id: 0,
  missing_start_date: 0,
}

describe('ComplianceBanner', () => {
  it('returns null when summary is null', () => {
    const { container } = render(
      <ComplianceBanner summary={null} activeFilter={null} onFilterChange={() => {}} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('returns null when summary is undefined', () => {
    const { container } = render(
      <ComplianceBanner summary={undefined} activeFilter={null} onFilterChange={() => {}} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('returns null when all counters are zero', () => {
    const { container } = render(
      <ComplianceBanner
        summary={ZERO_SUMMARY}
        activeFilter={null}
        onFilterChange={() => {}}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders one button per non-zero counter only', () => {
    const summary: ComplianceSummary = {
      ...ZERO_SUMMARY,
      probation_ending_soon: 2,
      visa_expiring_soon: 1,
      pay_review_due: 0,
      below_minimum_wage: 3,
      missing_agreement: 0,
      missing_employee_id: 4,
      missing_start_date: 0,
    }
    render(
      <ComplianceBanner
        summary={summary}
        activeFilter={null}
        onFilterChange={() => {}}
      />
    )

    // Only the non-zero counters have buttons rendered.
    expect(screen.getByTestId('counter-probation_ending')).toBeInTheDocument()
    expect(screen.getByTestId('counter-visa_expiring')).toBeInTheDocument()
    expect(screen.getByTestId('counter-below_minimum_wage')).toBeInTheDocument()
    expect(screen.getByTestId('counter-missing_employee_id')).toBeInTheDocument()

    // Zero counters render nothing.
    expect(screen.queryByTestId('counter-pay_review_due')).not.toBeInTheDocument()
    expect(screen.queryByTestId('counter-missing_agreement')).not.toBeInTheDocument()
    expect(screen.queryByTestId('counter-missing_start_date')).not.toBeInTheDocument()

    // Counter copy includes the count.
    expect(screen.getByText(/probation ending/i).textContent).toMatch(/2/)
    expect(screen.getByText(/missing code/i).textContent).toMatch(/4/)
  })

  it('renders all 7 counters when every counter is non-zero', () => {
    const summary: ComplianceSummary = {
      probation_ending_soon: 1,
      visa_expiring_soon: 1,
      pay_review_due: 1,
      below_minimum_wage: 1,
      missing_agreement: 1,
      missing_employee_id: 1,
      missing_start_date: 1,
    }
    render(
      <ComplianceBanner
        summary={summary}
        activeFilter={null}
        onFilterChange={() => {}}
      />
    )
    const expected = [
      'counter-probation_ending',
      'counter-visa_expiring',
      'counter-pay_review_due',
      'counter-below_minimum_wage',
      'counter-missing_agreement',
      'counter-missing_employee_id',
      'counter-missing_start_date',
    ]
    for (const id of expected) {
      expect(screen.getByTestId(id)).toBeInTheDocument()
    }
  })

  it('clicking a counter calls onFilterChange with the filter string', () => {
    const onFilterChange = vi.fn()
    const summary: ComplianceSummary = {
      ...ZERO_SUMMARY,
      missing_employee_id: 3,
    }
    render(
      <ComplianceBanner
        summary={summary}
        activeFilter={null}
        onFilterChange={onFilterChange}
      />
    )

    fireEvent.click(screen.getByTestId('counter-missing_employee_id'))
    expect(onFilterChange).toHaveBeenCalledTimes(1)
    expect(onFilterChange).toHaveBeenCalledWith('missing_employee_id')
  })

  it('clicking the active counter toggles the filter off (calls with null)', () => {
    const onFilterChange = vi.fn()
    const summary: ComplianceSummary = {
      ...ZERO_SUMMARY,
      visa_expiring_soon: 2,
    }
    render(
      <ComplianceBanner
        summary={summary}
        activeFilter="visa_expiring"
        onFilterChange={onFilterChange}
      />
    )

    const btn = screen.getByTestId('counter-visa_expiring')
    expect(btn).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(btn)
    expect(onFilterChange).toHaveBeenCalledTimes(1)
    expect(onFilterChange).toHaveBeenCalledWith(null)
  })

  it('renders the G3 persistent banner when missing_start_date > 0', () => {
    const summary: ComplianceSummary = {
      ...ZERO_SUMMARY,
      missing_start_date: 5,
    }
    render(
      <ComplianceBanner
        summary={summary}
        activeFilter={null}
        onFilterChange={() => {}}
      />
    )

    const banner = screen.getByTestId('g3-persistent-banner')
    expect(banner).toBeInTheDocument()
    expect(banner.textContent).toMatch(/phase 2 leave accrual/i)
    expect(banner.textContent).toMatch(/employment_start_date/)
  })

  it('does NOT render the G3 banner when missing_start_date === 0', () => {
    const summary: ComplianceSummary = {
      ...ZERO_SUMMARY,
      // Other counters non-zero so the component renders, but missing_start_date=0.
      below_minimum_wage: 2,
      missing_start_date: 0,
    }
    render(
      <ComplianceBanner
        summary={summary}
        activeFilter={null}
        onFilterChange={() => {}}
      />
    )
    expect(screen.queryByTestId('g3-persistent-banner')).not.toBeInTheDocument()
    // The counter row still rendered.
    expect(screen.getByTestId('counter-below_minimum_wage')).toBeInTheDocument()
  })

  it('counter buttons meet the 44px minimum touch target (mobile-app rule)', () => {
    const summary: ComplianceSummary = {
      ...ZERO_SUMMARY,
      pay_review_due: 1,
    }
    render(
      <ComplianceBanner
        summary={summary}
        activeFilter={null}
        onFilterChange={() => {}}
      />
    )

    const btn = screen.getByTestId('counter-pay_review_due')
    expect(btn.className).toMatch(/min-h-\[44px\]/)
  })
})

describe('StaffRowDots', () => {
  it('returns null when no fields are missing', () => {
    const { container } = render(
      <StaffRowDots
        staff={{
          employee_id: 'EMP-001',
          employment_start_date: '2024-01-01',
          hourly_rate: '30.00',
          minimum_wage_threshold: 23.15,
        }}
      />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders a single amber dot when only employee_id is missing (G1)', () => {
    render(
      <StaffRowDots
        staff={{
          employee_id: null,
          employment_start_date: '2024-01-01',
          hourly_rate: '30.00',
        }}
      />
    )
    const cluster = screen.getByTestId('staff-row-dots')
    expect(cluster).toHaveAttribute('title', 'Missing: employee code')
    expect(cluster.querySelectorAll('span').length).toBe(1)
    expect(cluster.querySelector('span')?.className).toMatch(/bg-amber-500/)
  })

  it('stacks two amber dots when employee_id and start_date are both missing (G1+G3)', () => {
    render(
      <StaffRowDots
        staff={{
          employee_id: null,
          employment_start_date: null,
          hourly_rate: '30.00',
        }}
      />
    )
    const cluster = screen.getByTestId('staff-row-dots')
    expect(cluster).toHaveAttribute(
      'title',
      'Missing: employee code, employment start date'
    )
    expect(cluster.querySelectorAll('span').length).toBe(2)
  })

  it('renders a red dot for below-minimum-wage when threshold is provided', () => {
    render(
      <StaffRowDots
        staff={{
          employee_id: 'EMP-001',
          employment_start_date: '2024-01-01',
          hourly_rate: '20.00',
          minimum_wage_threshold: 23.15,
        }}
      />
    )
    const cluster = screen.getByTestId('staff-row-dots')
    expect(cluster).toHaveAttribute('title', 'Missing: below minimum wage')
    expect(cluster.querySelector('span')?.className).toMatch(/bg-red-500/)
  })

  it('does not flag below-min-wage when threshold is omitted', () => {
    const { container } = render(
      <StaffRowDots
        staff={{
          employee_id: 'EMP-001',
          employment_start_date: '2024-01-01',
          hourly_rate: '5.00',
        }}
      />
    )
    expect(container.firstChild).toBeNull()
  })
})
