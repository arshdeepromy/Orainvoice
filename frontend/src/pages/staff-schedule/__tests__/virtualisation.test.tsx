/**
 * D2 — verify CSS-only row virtualisation hint.
 *
 * Renders the grid with 250 staff and asserts every row wrapper
 * carries the `content-visibility: auto` hint. The browser uses
 * this hint to skip layout/paint of off-screen rows automatically;
 * we don't assert the actual paint behaviour (jsdom has no layout
 * engine), only that the hint is applied per the implementation in
 * `RosterGrid.tsx` task B5 / D2.
 *
 * Validates: Roster Grid Editor — task D2 (R19.2).
 */

import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, afterEach } from 'vitest'
import RosterGrid from '../components/RosterGrid'
import type {
  LeaveOverlay,
  StaffMember,
} from '../hooks/useRosterGridData'

const STAFF_COUNT = 250
const VISIBLE_WINDOW = {
  start: new Date(2026, 5, 1), // 1 Jun 2026 (Mon)
  end: new Date(2026, 5, 14),
}

function buildStaff(count: number): StaffMember[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `s-${i}`,
    first_name: `First${i}`,
    last_name: `Last${i}`,
    name: `First${i} Last${i}`,
    position: null,
    is_active: true,
  }))
}

afterEach(() => {
  cleanup()
})

describe('RosterGrid row virtualisation hint (D2)', () => {
  it(`applies content-visibility: auto to every row wrapper when staff > 100`, () => {
    const staff = buildStaff(STAFF_COUNT)
    const leaveByStaffDate = new Map<string, Map<string, LeaveOverlay>>()

    render(
      <MemoryRouter>
        <RosterGrid
          staff={staff}
          entries={[]}
          leaveByStaffDate={leaveByStaffDate}
          visibleWindow={VISIBLE_WINDOW}
          isLoading={false}
        />
      </MemoryRouter>,
    )

    const rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(STAFF_COUNT)

    for (const row of rows) {
      // The CSS property name is `content-visibility`; React maps the
      // camelCase `contentVisibility` style key onto it. jsdom exposes
      // both via `style.contentVisibility` and `style['content-visibility']`.
      const cv =
        row.style.contentVisibility ||
        row.style.getPropertyValue('content-visibility')
      expect(cv).toBe('auto')
    }
  })

  it('does NOT apply the hint when staff <= 100', () => {
    const staff = buildStaff(50)
    const leaveByStaffDate = new Map<string, Map<string, LeaveOverlay>>()

    render(
      <MemoryRouter>
        <RosterGrid
          staff={staff}
          entries={[]}
          leaveByStaffDate={leaveByStaffDate}
          visibleWindow={VISIBLE_WINDOW}
          isLoading={false}
        />
      </MemoryRouter>,
    )

    const rows = screen.getAllByRole('row')
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      const cv =
        row.style.contentVisibility ||
        row.style.getPropertyValue('content-visibility')
      expect(cv).toBe('')
    }
  })
})
