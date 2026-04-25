import { useState, useCallback, useMemo } from 'react'
import { useBranch } from '@/contexts/BranchContext'

/**
 * BranchBadge — displays the active branch name as a tappable badge in the app header.
 * Tapping opens a dropdown branch selector.
 *
 * - 44px minimum touch target
 * - Shows "All Branches" when no specific branch is selected
 * - Hidden when branch module is disabled (no branches loaded and not locked)
 *
 * Requirements: 44.1, 44.5
 */
export function BranchBadge() {
  const { selectedBranchId, branches, selectBranch, isBranchLocked } =
    useBranch()
  const [isOpen, setIsOpen] = useState(false)

  const activeBranchName = useMemo(() => {
    if (!selectedBranchId) return 'All Branches'
    const branch = branches.find((b) => b.id === selectedBranchId)
    return branch?.name ?? 'Branch'
  }, [selectedBranchId, branches])

  const handleToggle = useCallback(() => {
    if (isBranchLocked) return
    setIsOpen((prev) => !prev)
  }, [isBranchLocked])

  const handleSelect = useCallback(
    (id: string | null) => {
      selectBranch(id)
      setIsOpen(false)
    },
    [selectBranch],
  )

  // Don't render if there are no branches and not locked to one
  if (branches.length === 0 && !isBranchLocked && !selectedBranchId) {
    return null
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleToggle}
        disabled={isBranchLocked}
        aria-label={`Current branch: ${activeBranchName}`}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className={`flex min-h-[44px] min-w-[44px] items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
          isBranchLocked
            ? 'cursor-default bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
            : 'bg-blue-50 text-blue-700 active:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:active:bg-blue-900/50'
        }`}
      >
        {/* Branch icon */}
        <svg
          className="h-3.5 w-3.5 flex-shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM18 9a9 9 0 0 1-9 9" />
        </svg>
        <span className="max-w-[100px] truncate">{activeBranchName}</span>
        {!isBranchLocked && (
          <svg
            className={`h-3 w-3 flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        )}
      </button>

      {/* Branch selector dropdown */}
      {isOpen && !isBranchLocked && (
        <>
          {/* Backdrop to close dropdown */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />
          <ul
            role="listbox"
            aria-label="Select branch"
            className="absolute right-0 top-full z-50 mt-1 max-h-60 w-48 overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800"
          >
            {/* All Branches option */}
            <li
              role="option"
              aria-selected={selectedBranchId === null}
              onClick={() => handleSelect(null)}
              className={`flex min-h-[44px] cursor-pointer items-center px-3 py-2 text-sm transition-colors active:bg-gray-100 dark:active:bg-gray-700 ${
                selectedBranchId === null
                  ? 'bg-blue-50 font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                  : 'text-gray-700 dark:text-gray-300'
              }`}
            >
              All Branches
            </li>
            {branches.map((branch) => (
              <li
                key={branch.id}
                role="option"
                aria-selected={selectedBranchId === branch.id}
                onClick={() => handleSelect(branch.id)}
                className={`flex min-h-[44px] cursor-pointer items-center px-3 py-2 text-sm transition-colors active:bg-gray-100 dark:active:bg-gray-700 ${
                  selectedBranchId === branch.id
                    ? 'bg-blue-50 font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                    : 'text-gray-700 dark:text-gray-300'
                }`}
              >
                {branch.name}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
