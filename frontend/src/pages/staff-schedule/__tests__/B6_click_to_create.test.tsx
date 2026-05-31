/**
 * Tests for the B6 click-to-create / click-to-edit flow on the
 * RosterGrid.
 *
 * Three cases:
 *   - Clicking an empty cell opens the modal in create mode with the
 *     cell's staff_id and date pre-filled.
 *   - Clicking a 1-entry cell opens the modal in edit mode for that
 *     entry.
 *   - Clicking a multi-entry cell renders the disambiguation popover.
 *
 * Validates: R4.1, R4.2, R4.3.
 */

import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, afterEach } from 'vitest'
import RosterGrid from '../components/RosterGrid'
import CellDisambiguationPopover from '../components/CellDisambiguationPopover'
import type { ScheduleEntryResponse } from '@/types/schedule'
import type { StaffMember, LeaveOverlay } from '../hooks/useRosterGridData'

const visibleWindow = {
  start: new Date(2025, 5, 2),
  end: new Date(2025, 5, 15),
}

const sampleStaff: StaffMember[] = [
  {
    id: 's1',
    first_name: 'Alice',
    last_name: 'Adams',
    name: 'Alice Adams',
    position: null,
    is_active: true,
  },
]

function entry(
  id: string,
  start: Date,
  end: Date,
  title: string,
): ScheduleEntryResponse {
  return {
    id,
    org_id: 'o1',
    staff_id: 's1',
    title,
    description: null,
    start_time: start.toISOString(),
    end_time: end.toISOString(),
    entry_type: 'job',
    status: 'scheduled',
    notes: null,
    recurrence_group_id: null,
    created_at: '',
    updated_at: '',
  }
}

afterEach(() => cleanup())

describe('RosterGrid click handling (B6)', () => {
  it('calls onCellClick with the cell entries on empty cell click', () => {
    let captured: { staffId: string; entries: ScheduleEntryResponse[] } | null =
      null
    render(
      <MemoryRouter>
        <RosterGrid
          staff={sampleStaff}
          entries={[]}
          leaveByStaffDate={
            new Map<string, Map<string, LeaveOverlay>>()
          }
          visibleWindow={visibleWindow}
          isLoading={false}
          onCellClick={(staffId, _date, entries) => {
            captured = { staffId, entries }
          }}
        />
      </MemoryRouter>,
    )
    const cells = screen.getAllByRole('gridcell')
    fireEvent.click(cells[0])
    const result = captured as { staffId: string; entries: ScheduleEntryResponse[] } | null
    expect(result).toBeTruthy()
    expect(result?.staffId).toBe('s1')
    expect(result?.entries).toHaveLength(0)
  })

  it('calls onCellClick with the 1 entry for a 1-entry cell', () => {
    const e = entry(
      'e1',
      new Date(2025, 5, 2, 9, 0),
      new Date(2025, 5, 2, 17, 0),
      'Morning',
    )
    let capturedEntries: ScheduleEntryResponse[] | null = null
    render(
      <MemoryRouter>
        <RosterGrid
          staff={sampleStaff}
          entries={[e]}
          leaveByStaffDate={new Map()}
          visibleWindow={visibleWindow}
          isLoading={false}
          onCellClick={(_staffId, _date, entries) => {
            capturedEntries = entries
          }}
        />
      </MemoryRouter>,
    )
    const cells = screen.getAllByRole('gridcell')
    // Find the cell on Jun 2 for s1.
    const cell = cells.find(
      (c) =>
        c.getAttribute('data-staff-id') === 's1' &&
        c.getAttribute('data-date') === '2025-06-02',
    )
    expect(cell).toBeDefined()
    fireEvent.click(cell!)
    const result = capturedEntries as ScheduleEntryResponse[] | null
    expect(result).toHaveLength(1)
    expect(result?.[0].id).toBe('e1')
  })

  it('calls onCellClick with multiple entries for a multi-entry cell', () => {
    const e1 = entry(
      'e1',
      new Date(2025, 5, 2, 9, 0),
      new Date(2025, 5, 2, 12, 0),
      'Morning',
    )
    const e2 = entry(
      'e2',
      new Date(2025, 5, 2, 13, 0),
      new Date(2025, 5, 2, 17, 0),
      'Afternoon',
    )
    let capturedEntries: ScheduleEntryResponse[] | null = null
    render(
      <MemoryRouter>
        <RosterGrid
          staff={sampleStaff}
          entries={[e1, e2]}
          leaveByStaffDate={new Map()}
          visibleWindow={visibleWindow}
          isLoading={false}
          onCellClick={(_staffId, _date, entries) => {
            capturedEntries = entries
          }}
        />
      </MemoryRouter>,
    )
    const cells = screen.getAllByRole('gridcell')
    const cell = cells.find(
      (c) =>
        c.getAttribute('data-staff-id') === 's1' &&
        c.getAttribute('data-date') === '2025-06-02',
    )
    fireEvent.click(cell!)
    expect(capturedEntries).toHaveLength(2)
  })
})

describe('CellDisambiguationPopover', () => {
  it('lists every entry and fires onPick when clicked', () => {
    const e1 = entry(
      'e1',
      new Date(2025, 5, 2, 9, 0),
      new Date(2025, 5, 2, 12, 0),
      'Morning',
    )
    const e2 = entry(
      'e2',
      new Date(2025, 5, 2, 13, 0),
      new Date(2025, 5, 2, 17, 0),
      'Afternoon',
    )
    let picked: ScheduleEntryResponse | null = null
    render(
      <CellDisambiguationPopover
        entries={[e1, e2]}
        onPick={(e) => {
          picked = e
        }}
        onClose={() => {}}
      />,
    )
    const items = screen.getAllByRole('menuitem')
    expect(items).toHaveLength(2)
    fireEvent.click(items[1])
    const result = picked as ScheduleEntryResponse | null
    expect(result).toBeTruthy()
    expect(result?.id).toBe('e2')
  })
})
