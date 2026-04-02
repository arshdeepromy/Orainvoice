import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  canProceedToStaff,
  getStaffBadgeInfo,
  canInviteStaff,
  toggleSelection,
  filterStaff,
  getSelectedCount,
  buildStaffAssignmentCalls,
  getBranchSelectorClasses,
  getActiveBranchIndicatorState,
  type StaffAssignmentSelection,
  type StaffMemberFromAPI,
} from '../branch-staff-helpers'

// ---------------------------------------------------------------------------
// Feature: branch-staff-assignment-and-switcher
// Property-based tests for pure helper functions
// ---------------------------------------------------------------------------

describe('Branch Staff Assignment — Property-Based Tests', () => {
  // Feature: branch-staff-assignment-and-switcher, Property 1: Step navigation requires valid branch name
  // **Validates: Requirements 1.2**
  it('Property 1: "Next" is enabled iff name.trim().length > 0', () => {
    fc.assert(
      fc.property(fc.string(), (name) => {
        const result = canProceedToStaff(name)
        const expected = name.trim().length > 0
        expect(result).toBe(expected)
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 3: Badge classification by account status
  // **Validates: Requirements 2.4, 3.4**
  it('Property 3: badge text is "Has account" when user_id !== null, "No account" when null', () => {
    const userIdArb: fc.Arbitrary<string | null> = fc.oneof(
      fc.constant(null),
      fc.uuid(),
    )

    fc.assert(
      fc.property(userIdArb, (userId) => {
        const badge = getStaffBadgeInfo(userId)
        if (userId !== null) {
          expect(badge.text).toBe('Has account')
          expect(badge.variant).toBe('info')
        } else {
          expect(badge.text).toBe('No account')
          expect(badge.variant).toBe('neutral')
        }
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 5: Unlinked staff without email cannot be invited
  // **Validates: Requirements 3.3**
  it('Property 5: unlinked staff (user_id=null) with null or empty email cannot be invited', () => {
    const noEmailArb: fc.Arbitrary<string | null> = fc.oneof(
      fc.constant(null),
      fc.constant(''),
      fc.constant('   '),
    )

    fc.assert(
      fc.property(noEmailArb, (email) => {
        const result = canInviteStaff(null, email)
        expect(result).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  // Additional: linked staff is always invitable regardless of email
  it('Property 5 (corollary): linked staff is always selectable', () => {
    const emailArb: fc.Arbitrary<string | null> = fc.oneof(
      fc.constant(null),
      fc.constant(''),
      fc.emailAddress(),
    )

    fc.assert(
      fc.property(fc.uuid(), emailArb, (userId, email) => {
        const result = canInviteStaff(userId, email)
        expect(result).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  // Additional: unlinked staff WITH a valid email CAN be invited
  it('Property 5 (inverse): unlinked staff with valid email can be invited', () => {
    fc.assert(
      fc.property(fc.emailAddress(), (email) => {
        const result = canInviteStaff(null, email)
        expect(result).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 4: Checkbox toggle manages selection set
  // **Validates: Requirements 2.2, 2.3, 3.2**
  it('Property 4: toggling a staff member changes selection set size by exactly 1', () => {
    // Generate a list of unique staff IDs and a random sequence of toggle indices
    const staffListArb = fc.array(
      fc.record({
        staffId: fc.uuid(),
        userId: fc.oneof(fc.constant(null as string | null), fc.uuid()),
        email: fc.oneof(fc.constant(null as string | null), fc.emailAddress()),
        name: fc.string({ minLength: 1 }),
      }),
      { minLength: 1, maxLength: 20 },
    )
    const toggleSeqArb = fc.array(fc.nat(), { minLength: 1, maxLength: 50 })

    fc.assert(
      fc.property(staffListArb, toggleSeqArb, (staffList, toggleSeq) => {
        // Deduplicate by staffId
        const uniqueStaff = staffList.filter(
          (s, i, arr) => arr.findIndex((x) => x.staffId === s.staffId) === i,
        )
        if (uniqueStaff.length === 0) return

        let selections = new Map<string, StaffAssignmentSelection>()

        for (const idx of toggleSeq) {
          const member = uniqueStaff[idx % uniqueStaff.length]
          const sizeBefore = selections.size
          selections = toggleSelection(selections, member.staffId, {
            userId: member.userId,
            email: member.email,
            name: member.name,
          })
          const sizeAfter = selections.size
          expect(Math.abs(sizeAfter - sizeBefore)).toBe(1)
        }
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 9: Staff search filters by name, email, or position
  // **Validates: Requirements 8.1, 8.2, 8.3**
  it('Property 9: filterStaff returns exactly staff whose name, email, or position contains query (case-insensitive)', () => {
    const staffMemberArb: fc.Arbitrary<StaffMemberFromAPI> = fc.record({
      id: fc.uuid(),
      org_id: fc.uuid(),
      user_id: fc.oneof(fc.constant(null as string | null), fc.uuid()),
      name: fc.string({ minLength: 1, maxLength: 30 }),
      first_name: fc.string({ minLength: 1, maxLength: 15 }),
      last_name: fc.oneof(fc.constant(null as string | null), fc.string({ maxLength: 15 })),
      email: fc.oneof(fc.constant(null as string | null), fc.emailAddress()),
      phone: fc.oneof(fc.constant(null as string | null), fc.string({ maxLength: 15 })),
      position: fc.oneof(fc.constant(null as string | null), fc.string({ maxLength: 20 })),
      role_type: fc.constantFrom('employee', 'contractor'),
      is_active: fc.constant(true),
      location_assignments: fc.constant([]),
    })

    const staffListArb = fc.array(staffMemberArb, { minLength: 0, maxLength: 20 })
    const queryArb = fc.string({ minLength: 0, maxLength: 10 })

    fc.assert(
      fc.property(staffListArb, queryArb, (staffList, query) => {
        const result = filterStaff(staffList, query)
        const q = query.toLowerCase().trim()

        if (q.length === 0) {
          // Empty query returns full list
          expect(result).toEqual(staffList)
        } else {
          // Each result must match on name, email, or position
          for (const s of result) {
            const nameMatch = (s.name ?? '').toLowerCase().includes(q)
            const emailMatch = (s.email ?? '').toLowerCase().includes(q)
            const positionMatch = (s.position ?? '').toLowerCase().includes(q)
            expect(nameMatch || emailMatch || positionMatch).toBe(true)
          }
          // Each non-result must NOT match
          for (const s of staffList) {
            if (!result.includes(s)) {
              const nameMatch = (s.name ?? '').toLowerCase().includes(q)
              const emailMatch = (s.email ?? '').toLowerCase().includes(q)
              const positionMatch = (s.position ?? '').toLowerCase().includes(q)
              expect(nameMatch || emailMatch || positionMatch).toBe(false)
            }
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 10: Selected count matches actual selections
  // **Validates: Requirements 8.4**
  it('Property 10: getSelectedCount equals selection set size after random toggle sequences', () => {
    const staffListArb = fc.array(
      fc.record({
        staffId: fc.uuid(),
        userId: fc.oneof(fc.constant(null as string | null), fc.uuid()),
        email: fc.oneof(fc.constant(null as string | null), fc.emailAddress()),
        name: fc.string({ minLength: 1 }),
      }),
      { minLength: 1, maxLength: 20 },
    )
    const toggleSeqArb = fc.array(fc.nat(), { minLength: 0, maxLength: 50 })

    fc.assert(
      fc.property(staffListArb, toggleSeqArb, (staffList, toggleSeq) => {
        const uniqueStaff = staffList.filter(
          (s, i, arr) => arr.findIndex((x) => x.staffId === s.staffId) === i,
        )
        if (uniqueStaff.length === 0) return

        let selections = new Map<string, StaffAssignmentSelection>()

        for (const idx of toggleSeq) {
          const member = uniqueStaff[idx % uniqueStaff.length]
          selections = toggleSelection(selections, member.staffId, {
            userId: member.userId,
            email: member.email,
            name: member.name,
          })
        }

        // The count helper must match the actual Map size
        expect(getSelectedCount(selections)).toBe(selections.size)
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 6: API call orchestration matches staff type
  // **Validates: Requirements 4.2, 4.3**
  it('Property 6: buildStaffAssignmentCalls produces correct counts of linked and unlinked calls', () => {
    // Generate a mixed list of staff selections with varying linked/unlinked status
    const selectionArb = fc.record({
      staffId: fc.uuid(),
      userId: fc.oneof(fc.constant(null as string | null), fc.uuid()),
      email: fc.oneof(
        fc.constant(null as string | null),
        fc.constant(''),
        fc.emailAddress(),
      ),
      name: fc.string({ minLength: 1, maxLength: 20 }),
    })

    const selectionsListArb = fc.array(selectionArb, { minLength: 0, maxLength: 30 })
    const branchIdArb = fc.uuid()

    fc.assert(
      fc.property(selectionsListArb, branchIdArb, (selectionsList, branchId) => {
        // Deduplicate by staffId
        const unique = selectionsList.filter(
          (s, i, arr) => arr.findIndex((x) => x.staffId === s.staffId) === i,
        )

        // Build the selections Map as the component would
        const selectionsMap = new Map<string, StaffAssignmentSelection>()
        for (const sel of unique) {
          const canInvite =
            sel.userId !== null ||
            (sel.email !== null && sel.email.trim().length > 0)
          selectionsMap.set(sel.staffId, {
            staffId: sel.staffId,
            userId: sel.userId,
            email: sel.email,
            name: sel.name,
            selected: true,
            canInvite,
          })
        }

        const result = buildStaffAssignmentCalls(selectionsMap, branchId)

        // Count expected linked: userId !== null
        const expectedLinked = unique.filter((s) => s.userId !== null)
        // Count expected unlinked: userId === null AND has valid email
        const expectedUnlinked = unique.filter(
          (s) =>
            s.userId === null &&
            s.email !== null &&
            s.email.trim().length > 0,
        )

        // Linked staff should produce exactly one assign-user call each
        expect(result.linked.length).toBe(expectedLinked.length)

        // Unlinked invitable staff should produce one create-account + assign-user pair each
        expect(result.unlinked.length).toBe(expectedUnlinked.length)

        // Verify all linked entries have a non-null userId
        for (const entry of result.linked) {
          expect(entry.userId).not.toBe('')
          expect(typeof entry.userId).toBe('string')
        }

        // Verify all unlinked entries have a non-empty email
        for (const entry of result.unlinked) {
          expect(entry.email.trim().length).toBeGreaterThan(0)
        }

        // Total API calls: linked get 1 call each, unlinked get 2 calls each
        const totalAssignCalls = result.linked.length + result.unlinked.length
        const totalCreateAccountCalls = result.unlinked.length
        expect(totalAssignCalls).toBe(expectedLinked.length + expectedUnlinked.length)
        expect(totalCreateAccountCalls).toBe(expectedUnlinked.length)
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 7: Branch selector styling reflects selection state
  // **Validates: Requirements 5.1, 5.2, 5.3**
  it('Property 7: active CSS classes applied when selectedBranchId !== null, neutral classes when null', () => {
    const branchIdArb: fc.Arbitrary<string | null> = fc.oneof(
      fc.constant(null),
      fc.uuid(),
      fc.string({ minLength: 1, maxLength: 30 }),
    )

    fc.assert(
      fc.property(branchIdArb, (selectedBranchId) => {
        const classes = getBranchSelectorClasses(selectedBranchId)

        if (selectedBranchId !== null) {
          // Active state: blue-themed classes
          expect(classes).toContain('bg-blue-50')
          expect(classes).toContain('border-blue-400')
          expect(classes).toContain('text-blue-700')
          expect(classes).toContain('font-medium')
          // Must NOT contain neutral classes
          expect(classes).not.toContain('bg-gray-50')
          expect(classes).not.toContain('border-gray-300')
          expect(classes).not.toContain('text-gray-700')
        } else {
          // Neutral state: gray-themed classes
          expect(classes).toContain('bg-gray-50')
          expect(classes).toContain('border-gray-300')
          expect(classes).toContain('text-gray-700')
          // Must NOT contain active classes
          expect(classes).not.toContain('bg-blue-50')
          expect(classes).not.toContain('border-blue-400')
          expect(classes).not.toContain('text-blue-700')
          expect(classes).not.toContain('font-medium')
        }
      }),
      { numRuns: 100 },
    )
  })

  // Feature: branch-staff-assignment-and-switcher, Property 8: Active branch indicator matches current selection
  // **Validates: Requirements 6.1, 6.4**
  it('Property 8: indicator text equals selected branch name, hidden when "All Branches"', () => {
    const branchArb = fc.record({
      id: fc.uuid(),
      name: fc.string({ minLength: 1, maxLength: 50 }),
    })
    const branchListArb = fc.array(branchArb, { minLength: 1, maxLength: 20 })

    fc.assert(
      fc.property(branchListArb, fc.nat(), fc.boolean(), (branches, switchIdx, selectAll) => {
        // Deduplicate by id
        const uniqueBranches = branches.filter(
          (b, i, arr) => arr.findIndex((x) => x.id === b.id) === i,
        )
        if (uniqueBranches.length === 0) return

        // Simulate a sequence: either select "All Branches" (null) or a specific branch
        const selectedBranchId = selectAll
          ? null
          : uniqueBranches[switchIdx % uniqueBranches.length].id

        const state = getActiveBranchIndicatorState(selectedBranchId, uniqueBranches)

        if (selectedBranchId === null) {
          // "All Branches" — indicator should be hidden
          expect(state.visible).toBe(false)
          expect(state.branchName).toBe('')
        } else {
          // Specific branch — indicator should show the branch name
          expect(state.visible).toBe(true)
          const expectedBranch = uniqueBranches.find((b) => b.id === selectedBranchId)
          expect(state.branchName).toBe(expectedBranch?.name ?? '')
        }
      }),
      { numRuns: 100 },
    )
  })

  // Property 8 (edge case): selectedBranchId not found in branches array
  it('Property 8 (edge): indicator visible but branchName empty when id not in branches', () => {
    fc.assert(
      fc.property(fc.uuid(), (orphanId) => {
        const branches = [{ id: 'other-id', name: 'Other Branch' }]
        const state = getActiveBranchIndicatorState(orphanId, branches)
        // Still visible (a branch IS selected), but name falls back to ''
        expect(state.visible).toBe(true)
        expect(state.branchName).toBe('')
      }),
      { numRuns: 100 },
    )
  })
})
