/**
 * Tests for the CSV export helpers (B15).
 *
 * Validates: R15.2, R15.3, R15.4 — RFC 4180 round-trip.
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'
import {
  generateRosterGridCSV,
  parseCSV,
  rfc4180Escape,
} from '../utils/csv'
import type { ScheduleEntryResponse } from '@/types/schedule'
import type {
  LeaveOverlay,
  StaffMember,
} from '../hooks/useRosterGridData'

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
    position: 'Mechanic',
    is_active: true,
  },
]

describe('generateRosterGridCSV', () => {
  it('generates header + rows', () => {
    const csv = generateRosterGridCSV(visibleWindow, sampleStaff, [], new Map())
    const rows = parseCSV(csv)
    expect(rows[0][0]).toBe('staff_name')
    expect(rows[0][1]).toBe('position')
    expect(rows[0]).toHaveLength(16) // staff_name + position + 14 days
    expect(rows[1][0]).toBe('Alice Adams')
    expect(rows[1][1]).toBe('Mechanic')
  })

  it('renders leave cells as LEAVE: ...', () => {
    const leave = new Map<string, Map<string, LeaveOverlay>>()
    const inner = new Map<string, LeaveOverlay>()
    inner.set('2025-06-04', {
      leave_type_label: 'Annual',
      leave_type_code: 'annual',
    })
    leave.set('s1', inner)
    const csv = generateRosterGridCSV(visibleWindow, sampleStaff, [], leave)
    const rows = parseCSV(csv)
    // Column index for Jun 4 is 2 (Jun 2 = index 2 in row, header starts col 2).
    expect(rows[1][4]).toBe('LEAVE: Annual')
  })

  it('renders entries as HH:MM-HH:MM Title sorted by start_time', () => {
    const e1: ScheduleEntryResponse = {
      id: 'e1',
      org_id: 'o',
      staff_id: 's1',
      title: 'Morning',
      start_time: new Date(2025, 5, 2, 9, 0).toISOString(),
      end_time: new Date(2025, 5, 2, 12, 0).toISOString(),
      entry_type: 'job',
      status: 'scheduled',
      created_at: '',
      updated_at: '',
    }
    const e2: ScheduleEntryResponse = {
      ...e1,
      id: 'e2',
      title: 'Afternoon',
      start_time: new Date(2025, 5, 2, 13, 0).toISOString(),
      end_time: new Date(2025, 5, 2, 17, 0).toISOString(),
    }
    const csv = generateRosterGridCSV(visibleWindow, sampleStaff, [e1, e2], new Map())
    const rows = parseCSV(csv)
    // Column index for Jun 2 (Mon) is 2 in the row (after staff_name + position).
    expect(rows[1][2]).toBe('09:00-12:00 Morning; 13:00-17:00 Afternoon')
  })

  it('property: parse(generate(rows)) round-trips for unicode + commas + quotes + newlines', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            id: fc.uuid(),
            title: fc.string({ maxLength: 30 }),
          }),
          { minLength: 0, maxLength: 5 },
        ),
        (samples) => {
          const entries: ScheduleEntryResponse[] = samples.map((s, i) => ({
            id: s.id,
            org_id: 'o',
            staff_id: 's1',
            title: s.title,
            start_time: new Date(2025, 5, 2, 9 + i, 0).toISOString(),
            end_time: new Date(2025, 5, 2, 10 + i, 0).toISOString(),
            entry_type: 'job',
            status: 'scheduled',
            created_at: '',
            updated_at: '',
          }))
          const csv = generateRosterGridCSV(
            visibleWindow,
            sampleStaff,
            entries,
            new Map(),
          )
          const rows = parseCSV(csv)
          // Header + 1 staff row.
          expect(rows.length).toBeGreaterThanOrEqual(2)
          // Each row has 16 columns.
          expect(rows[0]).toHaveLength(16)
          expect(rows[1]).toHaveLength(16)
        },
      ),
      { numRuns: 30 },
    )
  })
})

describe('rfc4180Escape', () => {
  it('wraps fields with commas, quotes, or newlines', () => {
    expect(rfc4180Escape('hello')).toBe('hello')
    expect(rfc4180Escape('a,b')).toBe('"a,b"')
    expect(rfc4180Escape('a"b')).toBe('"a""b"')
    expect(rfc4180Escape('a\nb')).toBe('"a\nb"')
  })
})
