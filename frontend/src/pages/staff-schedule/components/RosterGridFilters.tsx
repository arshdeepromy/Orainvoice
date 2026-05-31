/**
 * RosterGridFilters — branch + position dropdowns for the grid
 * (Workstream B / task B17).
 *
 * Branch comes from `BranchContext` (already in the app). Position is
 * the distinct non-null `staff.position` set computed from the staff
 * list. Both filters are applied client-side by the parent — this
 * component only owns the rendering + change events.
 */

import { useMemo } from 'react'
import { useBranch } from '@/contexts/BranchContext'
import type { StaffMember } from '../hooks/useRosterGridData'

export interface RosterGridFiltersProps {
  staff: StaffMember[]
  branchFilter: string | null
  setBranchFilter: (id: string | null) => void
  positionFilter: string | null
  setPositionFilter: (position: string | null) => void
}

export default function RosterGridFilters({
  staff,
  branchFilter,
  setBranchFilter,
  positionFilter,
  setPositionFilter,
}: RosterGridFiltersProps) {
  const { branches } = useBranch()

  const positions = useMemo(() => {
    const set = new Set<string>()
    for (const s of staff ?? []) {
      if (s.position) set.add(s.position)
    }
    return [...set].sort((a, b) => a.localeCompare(b))
  }, [staff])

  return (
    <div
      className="flex flex-wrap items-center gap-3"
      data-no-print
      data-testid="roster-grid-filters"
    >
      <label className="flex items-center gap-2 text-sm text-gray-700">
        Branch
        <select
          aria-label="Branch filter"
          value={branchFilter ?? ''}
          onChange={(e) => setBranchFilter(e.target.value || null)}
          className="rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="">All branches</option>
          {(branches ?? []).map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2 text-sm text-gray-700">
        Position
        <select
          aria-label="Position filter"
          value={positionFilter ?? ''}
          onChange={(e) => setPositionFilter(e.target.value || null)}
          className="rounded border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="">All positions</option>
          {positions.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}

/**
 * Filter helper extracted for reuse in tests.
 */
export function applyStaffFilters(
  staff: StaffMember[],
  branchFilter: string | null,
  positionFilter: string | null,
): StaffMember[] {
  return (staff ?? []).filter((s) => {
    if (branchFilter) {
      const ids = (s.location_assignments ?? []).map((la) => la.location_id)
      if (!ids.includes(branchFilter)) return false
    }
    if (positionFilter) {
      if (s.position !== positionFilter) return false
    }
    return true
  })
}
