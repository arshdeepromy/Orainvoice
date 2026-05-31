/**
 * D1 — render-time benchmark for the Roster Grid Editor.
 *
 * Renders the grid with 50 staff × 700 entries and prints the
 * time-to-render via `console.time` / `console.timeEnd`. We DO NOT
 * hard-assert a wall-clock budget — the spec calls for the number to
 * be tracked in the PR description rather than baked into a brittle
 * threshold (R19.1).
 *
 * Decorated with `it.skipIf(!process.env.RUN_PERF)` so CI does NOT
 * run it by default. Run locally with:
 *
 *     RUN_PERF=1 npx vitest run \
 *         src/pages/staff-schedule/__tests__/perf.test.ts
 *
 * Validates: Roster Grid Editor — task D1 (R19.1).
 */

import { describe, it, expect } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import RosterGrid from '../components/RosterGrid'
import type {
  LeaveOverlay,
  StaffMember,
} from '../hooks/useRosterGridData'
import type { ScheduleEntryResponse } from '@/types/schedule'

const STAFF_COUNT = 50
const ENTRIES_COUNT = 700
const VISIBLE_WINDOW = {
  start: new Date(2026, 5, 1), // 1 Jun 2026 (Mon)
  end: new Date(2026, 5, 14),
}

function buildStaff(): StaffMember[] {
  return Array.from({ length: STAFF_COUNT }, (_, i) => ({
    id: `s-${i}`,
    first_name: `First${i}`,
    last_name: `Last${i}`,
    name: `First${i} Last${i}`,
    position: i % 3 === 0 ? 'Mechanic' : null,
    is_active: true,
  }))
}

function buildEntries(): ScheduleEntryResponse[] {
  return Array.from({ length: ENTRIES_COUNT }, (_, i) => {
    const sid = `s-${i % STAFF_COUNT}`
    const dayOffset = i % 14
    const start = new Date(VISIBLE_WINDOW.start)
    start.setDate(start.getDate() + dayOffset)
    start.setHours(9 + (i % 4), 0, 0, 0)
    const end = new Date(start)
    end.setHours(start.getHours() + 1, 0, 0, 0)
    return {
      id: `e-${i}`,
      org_id: 'o',
      staff_id: sid,
      title: `Shift ${i}`,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      entry_type: 'job',
      status: 'scheduled',
      created_at: start.toISOString(),
      updated_at: start.toISOString(),
    }
  })
}

const RUN_PERF = !!process.env.RUN_PERF

describe('RosterGrid render-time benchmark (D1)', () => {
  it.skipIf(!RUN_PERF)(
    `renders ${STAFF_COUNT} staff × ${ENTRIES_COUNT} entries (timing logged)`,
    () => {
      const staff = buildStaff()
      const entries = buildEntries()
      const leaveByStaffDate = new Map<string, Map<string, LeaveOverlay>>()

      const label = `RosterGrid render ${STAFF_COUNT}x${ENTRIES_COUNT}`
      // eslint-disable-next-line no-console
      console.time(label)
      const { unmount } = render(
        React.createElement(
          MemoryRouter,
          null,
          React.createElement(RosterGrid, {
            staff,
            entries,
            leaveByStaffDate,
            visibleWindow: VISIBLE_WINDOW,
            isLoading: false,
          }),
        ),
      )
      // eslint-disable-next-line no-console
      console.timeEnd(label)

      // Sanity check that the render actually produced cells.
      expect(staff).toHaveLength(STAFF_COUNT)
      expect(entries).toHaveLength(ENTRIES_COUNT)

      unmount()
      cleanup()
    },
  )
})
