import { useCallback } from 'react'
import { Sheet, List, ListItem, BlockTitle } from 'konsta/react'
import { useBranch } from '@/contexts/BranchContext'

// ─── Checkmark icon ─────────────────────────────────────────────────────────

function CheckIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2.5}
      stroke="currentColor"
      className="h-5 w-5 text-primary"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4.5 12.75l6 6 9-13.5"
      />
    </svg>
  )
}

// ─── BranchPickerSheet props ────────────────────────────────────────────────

export interface BranchPickerSheetProps {
  isOpen: boolean
  onClose: () => void
  onSelect: (branchId: string) => void
}

/**
 * BranchPickerSheet — Konsta UI Sheet listing available branches with
 * radio-style selection. Includes an "All Branches" option that clears
 * the branch filter.
 *
 * On selection: calls `onSelect(branchId)` which should update localStorage
 * and trigger BranchContext refresh.
 *
 * Requirements: 6.5
 */
export function BranchPickerSheet({
  isOpen,
  onClose,
  onSelect,
}: BranchPickerSheetProps) {
  const { selectedBranchId, branches } = useBranch()

  const handleSelect = useCallback(
    (branchId: string) => {
      onSelect(branchId)
      onClose()
    },
    [onSelect, onClose],
  )

  const handleSelectAll = useCallback(() => {
    // Pass empty string to indicate "All Branches" (clear selection)
    onSelect('')
    onClose()
  }, [onSelect, onClose])

  return (
    <Sheet
      opened={isOpen}
      onBackdropClick={onClose}
      data-testid="branch-picker-sheet"
      className="branch-picker-sheet"
    >
      <div
        className="max-h-[70vh] overflow-y-auto pb-safe"
        data-testid="branch-picker-content"
      >
        {/* Drag handle indicator */}
        <div className="flex justify-center pb-2 pt-3">
          <div className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" />
        </div>

        <BlockTitle>Select Branch</BlockTitle>

        <List strongIos outlineIos>
          {/* "All Branches" option */}
          <ListItem
            title="All Branches"
            after={selectedBranchId === null ? <CheckIcon /> : undefined}
            link
            onClick={handleSelectAll}
            data-testid="branch-option-all"
          />

          {/* Individual branch options */}
          {branches.map((branch) => (
            <ListItem
              key={branch.id}
              title={branch.name}
              subtitle={branch.address ?? undefined}
              after={
                selectedBranchId === branch.id ? <CheckIcon /> : undefined
              }
              link
              onClick={() => handleSelect(branch.id)}
              data-testid={`branch-option-${branch.id}`}
            />
          ))}
        </List>
      </div>
    </Sheet>
  )
}
