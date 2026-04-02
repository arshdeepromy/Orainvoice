/**
 * Pure helper functions for branch staff assignment.
 * Extracted for easy property-based testing without React/API dependencies.
 */

export interface StaffMemberFromAPI {
  id: string
  org_id: string
  user_id: string | null
  name: string
  first_name: string
  last_name: string | null
  email: string | null
  phone: string | null
  position: string | null
  role_type: string
  is_active: boolean
  location_assignments: Array<{
    id: string
    staff_id: string
    location_id: string
    assigned_at: string
  }>
}

export interface StaffAssignmentSelection {
  staffId: string
  userId: string | null
  email: string | null
  name: string
  selected: boolean
  canInvite: boolean
}

export type ModalStep = 'details' | 'staff'

export function canProceedToStaff(name: string): boolean {
  return name.trim().length > 0
}

export function getStaffBadgeInfo(userId: string | null): { text: string; variant: 'info' | 'neutral' } {
  return userId !== null
    ? { text: 'Has account', variant: 'info' }
    : { text: 'No account', variant: 'neutral' }
}

export function canInviteStaff(userId: string | null, email: string | null): boolean {
  if (userId !== null) return true
  return email !== null && email.trim().length > 0
}

export function getCheckboxLabel(userId: string | null): string {
  return userId !== null ? 'Grant branch access' : 'Invite to manage this branch'
}

/**
 * Toggle a staff member in/out of the selection set.
 * Returns a new Map with the toggled state.
 */
export function toggleSelection(
  selections: Map<string, StaffAssignmentSelection>,
  staffId: string,
  staffMember: { userId: string | null; email: string | null; name: string },
): Map<string, StaffAssignmentSelection> {
  const next = new Map(selections)
  if (next.has(staffId)) {
    next.delete(staffId)
  } else {
    next.set(staffId, {
      staffId,
      userId: staffMember.userId,
      email: staffMember.email,
      name: staffMember.name,
      selected: true,
      canInvite: canInviteStaff(staffMember.userId, staffMember.email),
    })
  }
  return next
}

/**
 * Filter staff list by case-insensitive substring match on name, email, or position.
 */
export function filterStaff(
  staffList: StaffMemberFromAPI[],
  query: string,
): StaffMemberFromAPI[] {
  const q = query.toLowerCase().trim()
  if (q.length === 0) return staffList
  return staffList.filter((s) => {
    const name = (s.name ?? '').toLowerCase()
    const email = (s.email ?? '').toLowerCase()
    const position = (s.position ?? '').toLowerCase()
    return name.includes(q) || email.includes(q) || position.includes(q)
  })
}

/**
 * Get the count of selected staff members.
 */
export function getSelectedCount(selections: Map<string, StaffAssignmentSelection>): number {
  return selections.size
}

/**
 * Categorised staff assignment calls for branch creation.
 * Separates linked staff (direct assign) from unlinked staff (create-account + assign).
 */
export interface StaffAssignmentCalls {
  linked: Array<{ staffId: string; userId: string; name: string }>
  unlinked: Array<{ staffId: string; email: string; name: string }>
}

/**
 * Compute the state for the ActiveBranchIndicator in the header.
 * Returns `visible: true` with the branch name when a specific branch is selected,
 * or `visible: false` with an empty name when "All Branches" is selected.
 *
 * Requirements: 6.1, 6.3, 6.4
 */
export function getActiveBranchIndicatorState(
  selectedBranchId: string | null,
  branches: Array<{ id: string; name: string }>,
): { visible: boolean; branchName: string } {
  if (selectedBranchId === null) {
    return { visible: false, branchName: '' }
  }
  const branch = branches.find((b) => b.id === selectedBranchId)
  return { visible: true, branchName: branch?.name ?? '' }
}

/**
 * Returns the appropriate CSS class string for the BranchSelector based on selection state.
 * When a specific branch is selected (non-null), returns active/colored classes.
 * When "All Branches" is selected (null), returns neutral/default classes.
 * Base classes shared by both states are not included here — they are applied separately.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4
 */
export function getBranchSelectorClasses(selectedBranchId: string | null): string {
  if (selectedBranchId !== null) {
    return 'bg-blue-50 border-blue-400 text-blue-700 font-medium'
  }
  return 'bg-gray-50 border-gray-300 text-gray-700'
}

/**
 * Build categorised lists of linked and unlinked staff from the selections Map.
 * Linked staff (userId !== null) need only an assign-user call.
 * Unlinked staff (userId === null, canInvite === true) need create-account + assign-user.
 * Exported for property testing.
 */
export function buildStaffAssignmentCalls(
  selections: Map<string, StaffAssignmentSelection>,
  _newBranchId: string,
): StaffAssignmentCalls {
  const linked: StaffAssignmentCalls['linked'] = []
  const unlinked: StaffAssignmentCalls['unlinked'] = []

  for (const sel of selections.values()) {
    if (sel.userId !== null) {
      linked.push({ staffId: sel.staffId, userId: sel.userId, name: sel.name })
    } else if (sel.canInvite && sel.email !== null && sel.email.trim().length > 0) {
      unlinked.push({ staffId: sel.staffId, email: sel.email, name: sel.name })
    }
  }

  return { linked, unlinked }
}
