/**
 * Tests for RosterGrid (B5):
 *   - Empty staff array → empty state renders.
 *   - 3 staff × 14 days → 42 cells.
 *   - Leave-shaded cell renders with `aria-disabled="true"`.
 *   - Property test: cell count == staff.length * 14 for any staff
 *     length 0..25 and entries length 0..100.
 *
 * Validates: R2.1, R2.2, R2.3, R2.8, R2.9, R3.5, R14.
 */

import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, afterEach } from 'vitest'
import fc from 'fast-check'
import RosterGrid from '../components/RosterGrid'
import type {
  LeaveOverlay,
  StaffMember,
} from '../hooks/useRosterGridData'
import type { ScheduleEntryResponse } from '@/types/schedule'

const visibleWindow = {
  start: new Date(2025, 5, 2), // 2 Jun 2025 (Mon)
  end: new Date(2025, 5, 15),
}

function renderGrid(
  staff: StaffMember[],
  entries: ScheduleEntryResponse[] = [],
  leaveByStaffDate: Map<string, Map<string, LeaveOverlay>> = new Map(),
) {
  return render(
    <MemoryRouter>
      <RosterGrid
        staff={staff}
        entries={entries}
        leaveByStaffDate={leaveByStaffDate}
        visibleWindow={visibleWindow}
        isLoading={false}
      />
    </MemoryRouter>,
  )
}

const sampleStaff: StaffMember[] = [
  {
    id: 's1',
    first_name: 'Alice',
    last_name: 'Smith',
    name: 'Alice Smith',
    position: 'Mechanic',
    is_active: true,
  },
  {
    id: 's2',
    first_name: 'Bob',
    last_name: 'Jones',
    name: 'Bob Jones',
    position: null,
    is_active: true,
  },
  {
    id: 's3',
    first_name: 'Carol',
    last_name: 'Adams',
    name: 'Carol Adams',
    position: null,
    is_active: true,
  },
]

afterEach(() => {
  cleanup()
})

describe('RosterGrid', () => {
  it('shows empty state when staff is empty', () => {
    renderGrid([])
    expect(screen.getByTestId('roster-grid-empty')).toBeInTheDocument()
    expect(screen.getByText(/No active staff/i)).toBeInTheDocument()
  })

  it('renders staff_count × 14 grid cells', () => {
    renderGrid(sampleStaff)
    const cells = screen.getAllByRole('gridcell')
    expect(cells).toHaveLength(sampleStaff.length * 14)
  })

  it('renders a leave-shaded cell with aria-disabled', () => {
    const leaveMap = new Map<string, Map<string, LeaveOverlay>>()
    const inner = new Map<string, LeaveOverlay>()
    inner.set('2025-06-03', {
      leave_type_label: 'Annual leave',
      leave_type_code: 'annual',
    })
    leaveMap.set('s1', inner)

    renderGrid(sampleStaff, [], leaveMap)

    const allCells = screen.getAllByRole('gridcell')
    const leaveCell = allCells.find(
      (el) =>
        el.getAttribute('data-leave') === 'true' &&
        el.getAttribute('data-staff-id') === 's1' &&
        el.getAttribute('data-date') === '2025-06-03',
    )
    expect(leaveCell).toBeDefined()
    expect(leaveCell).toHaveAttribute('aria-disabled', 'true')
    expect(leaveCell?.textContent).toContain('Annual leave')
  })

  it('property: rendered cell count == staff.length * 14 for any size 0..25', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 25 }),
        fc.integer({ min: 0, max: 100 }),
        (staffCount, entryCount) => {
          const staff: StaffMember[] = Array.from(
            { length: staffCount },
            (_, i) => ({
              id: `s-${i}`,
              first_name: `First${i}`,
              last_name: `Last${i}`,
              name: `First${i} Last${i}`,
              position: null,
              is_active: true,
            }),
          )
          const entries: ScheduleEntryResponse[] = Array.from(
            { length: entryCount },
            (_, i) => {
              // Map each entry to an existing staff_id (or empty when no
              // staff so it gets ignored by the indexer).
              const sid =
                staffCount > 0 ? `s-${i % staffCount}` : ''
              const dayOffset = i % 14
              const start = new Date(visibleWindow.start)
              start.setDate(start.getDate() + dayOffset)
              start.setHours(9, 0, 0, 0)
              const end = new Date(start)
              end.setHours(17, 0, 0, 0)
              return {
                id: `e-${i}`,
                org_id: 'o',
                staff_id: sid,
                start_time: start.toISOString(),
                end_time: end.toISOString(),
                entry_type: 'job',
                status: 'scheduled',
                created_at: start.toISOString(),
                updated_at: start.toISOString(),
              }
            },
          )

          const { unmount } = renderGrid(staff, entries)
          if (staffCount === 0) {
            expect(
              screen.getByTestId('roster-grid-empty'),
            ).toBeInTheDocument()
          } else {
            const cells = screen.getAllByRole('gridcell')
            expect(cells).toHaveLength(staffCount * 14)
          }
          unmount()
        },
      ),
      { numRuns: 25 },
    )
  })
})
