/**
 * Tests for the branch + position filter helper (B17).
 *
 * `applyStaffFilters` is the pure function used by the page.
 *
 * Validates: R3.3, R3.4.
 */

import { describe, it, expect } from 'vitest'
import { applyStaffFilters } from '../components/RosterGridFilters'
import type { StaffMember } from '../hooks/useRosterGridData'

const sampleStaff: StaffMember[] = [
  {
    id: 's1',
    first_name: 'Alice',
    last_name: 'Adams',
    name: 'Alice Adams',
    position: 'Mechanic',
    is_active: true,
    location_assignments: [
      { id: 'la1', staff_id: 's1', location_id: 'b1', assigned_at: '' },
    ],
  },
  {
    id: 's2',
    first_name: 'Bob',
    last_name: 'Bloggs',
    name: 'Bob Bloggs',
    position: 'Mechanic',
    is_active: true,
    location_assignments: [
      { id: 'la2', staff_id: 's2', location_id: 'b2', assigned_at: '' },
    ],
  },
  {
    id: 's3',
    first_name: 'Carol',
    last_name: 'Carter',
    name: 'Carol Carter',
    position: 'Service Advisor',
    is_active: true,
    location_assignments: [
      { id: 'la3', staff_id: 's3', location_id: 'b1', assigned_at: '' },
    ],
  },
]

describe('applyStaffFilters', () => {
  it('returns all staff when no filters set', () => {
    expect(applyStaffFilters(sampleStaff, null, null)).toHaveLength(3)
  })

  it('filters by branch', () => {
    const out = applyStaffFilters(sampleStaff, 'b1', null)
    expect(out).toHaveLength(2)
    expect(out.map((s) => s.id)).toEqual(['s1', 's3'])
  })

  it('filters by position', () => {
    const out = applyStaffFilters(sampleStaff, null, 'Mechanic')
    expect(out.map((s) => s.id)).toEqual(['s1', 's2'])
  })

  it('combines branch and position filters', () => {
    const out = applyStaffFilters(sampleStaff, 'b1', 'Mechanic')
    expect(out.map((s) => s.id)).toEqual(['s1'])
  })
})
