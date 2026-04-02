import { useEffect } from 'react'
import { useBranch } from '@/contexts/BranchContext'
import { getBranchSelectorClasses } from '@/pages/settings/branch-staff-helpers'

/**
 * Branch selector dropdown for the top navigation bar.
 *
 * Lists the user's accessible branches plus an "All Branches" option.
 * Pre-selects the single branch when the user has only one.
 * Persists selection via BranchContext (which writes to localStorage).
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
 */
export function BranchSelector() {
  const { selectedBranchId, branches, selectBranch, isLoading } = useBranch()

  // Auto-select single branch if user has exactly one
  useEffect(() => {
    if (branches.length === 1 && selectedBranchId === null) {
      selectBranch(branches[0].id)
    }
  }, [branches, selectedBranchId, selectBranch])

  // Don't render if no branches loaded yet or user has no branches
  if (isLoading || (branches ?? []).length === 0) return null

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value
    selectBranch(val === 'all' ? null : val)
  }

  return (
    <div className="flex items-center">
      <label htmlFor="branch-selector" className="sr-only">
        Select branch
      </label>
      <select
        id="branch-selector"
        value={selectedBranchId ?? 'all'}
        onChange={handleChange}
        className={`rounded-lg border px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 min-h-[44px] ${getBranchSelectorClasses(selectedBranchId)}`}
        aria-label="Select branch"
      >
        <option value="all">All Branches</option>
        {(branches ?? []).map((branch) => (
          <option key={branch.id} value={branch.id}>
            {branch.name}
          </option>
        ))}
      </select>
    </div>
  )
}
