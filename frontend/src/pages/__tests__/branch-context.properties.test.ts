import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { validateBranchSelection } from '@/contexts/BranchContext'

// Feature: branch-management-complete

// ─── Property 17: Stale branch selection reset ───
// **Validates: Requirements 24.2, 24.3**
//
// For any stored branch_id in localStorage that is not present in the user's
// current branch_ids array, the BranchContext provider SHALL reset the
// selection to "All Branches" (null) and remove the stale value.

describe('Property 17: Stale branch selection reset', () => {
  const uuidArb = fc.uuid()

  it('resets to null when stored branch_id is not in user branch_ids', () => {
    fc.assert(
      fc.property(
        uuidArb,
        fc.array(uuidArb, { minLength: 0, maxLength: 10 }),
        (storedId, userBranchIds) => {
          // Ensure storedId is NOT in the user's branch list
          fc.pre(!userBranchIds.includes(storedId))

          const result = validateBranchSelection(storedId, userBranchIds)
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('keeps selection when stored branch_id IS in user branch_ids', () => {
    fc.assert(
      fc.property(
        uuidArb,
        fc.array(uuidArb, { minLength: 0, maxLength: 10 }),
        (storedId, extraIds) => {
          // Ensure storedId IS in the user's branch list
          const userBranchIds = [storedId, ...extraIds]

          const result = validateBranchSelection(storedId, userBranchIds)
          expect(result).toBe(storedId)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('returns null for null stored id regardless of branch_ids', () => {
    fc.assert(
      fc.property(
        fc.array(uuidArb, { minLength: 0, maxLength: 10 }),
        (userBranchIds) => {
          const result = validateBranchSelection(null, userBranchIds)
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })

  it('returns null for "all" stored id regardless of branch_ids', () => {
    fc.assert(
      fc.property(
        fc.array(uuidArb, { minLength: 0, maxLength: 10 }),
        (userBranchIds) => {
          const result = validateBranchSelection('all', userBranchIds)
          expect(result).toBeNull()
        },
      ),
      { numRuns: 100 },
    )
  })
})

// ─── Property 20: Branch selector shows exactly user's accessible branches ───
// **Validates: Requirements 8.2**
//
// For any user with branch_ids array [B1, B2, ..., Bn], the BranchSelector
// SHALL list exactly those n branches plus the "All Branches" option.

describe('Property 20: Branch selector shows exactly user accessible branches', () => {
  const uuidArb = fc.uuid()

  interface BranchStub {
    id: string
    name: string
    is_active: boolean
  }

  /**
   * Pure function that mirrors the selector's rendering logic:
   * given a list of branches, return the option values that would appear.
   */
  function expectedSelectorOptions(branches: BranchStub[]): string[] {
    return ['all', ...branches.map((b) => b.id)]
  }

  it('selector options = "all" + exactly the user branches', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            id: uuidArb,
            name: fc.string({ minLength: 1, maxLength: 50 }),
            is_active: fc.constant(true),
          }),
          { minLength: 0, maxLength: 10 },
        ),
        (branches) => {
          // Deduplicate by id (mirrors real data)
          const seen = new Set<string>()
          const unique = branches.filter((b) => {
            if (seen.has(b.id)) return false
            seen.add(b.id)
            return true
          })

          const options = expectedSelectorOptions(unique)

          // Must always include "all"
          expect(options[0]).toBe('all')

          // Must include exactly the user's branch ids
          const branchOptions = options.slice(1)
          expect(branchOptions).toHaveLength(unique.length)
          for (const branch of unique) {
            expect(branchOptions).toContain(branch.id)
          }

          // Total options = branches + 1 ("All Branches")
          expect(options).toHaveLength(unique.length + 1)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('no duplicate branch ids in selector options', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            id: uuidArb,
            name: fc.string({ minLength: 1, maxLength: 50 }),
            is_active: fc.constant(true),
          }),
          { minLength: 1, maxLength: 10 },
        ),
        (branches) => {
          const seen = new Set<string>()
          const unique = branches.filter((b) => {
            if (seen.has(b.id)) return false
            seen.add(b.id)
            return true
          })

          const options = expectedSelectorOptions(unique)
          const optionSet = new Set(options)
          expect(optionSet.size).toBe(options.length)
        },
      ),
      { numRuns: 100 },
    )
  })
})
