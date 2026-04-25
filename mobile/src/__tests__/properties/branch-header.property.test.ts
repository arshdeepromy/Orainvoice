import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { resolveBranchHeader } from '@/api/client'

/**
 * **Validates: Requirements 13.4, 44.2, 44.3**
 *
 * Property 3: Branch header injection matches selected branch
 *
 * For any selected branch ID (including null for "All Branches"), every API
 * request made through the API client SHALL include the X-Branch-Id header
 * with the selected branch ID when a specific branch is selected, and SHALL
 * omit the X-Branch-Id header when "All Branches" (null) is selected.
 */

// ---------------------------------------------------------------------------
// Generators
// ---------------------------------------------------------------------------

/** Arbitrary for a valid UUID-like branch ID. */
const branchIdArb = fc.uuid()

/** Arbitrary for null / "all" representing "All Branches". */
const allBranchesArb = fc.oneof(
  fc.constant(null as string | null),
  fc.constant('all' as string | null),
)

/** Arbitrary for any branch selection (specific or all). */
const branchSelectionArb = fc.oneof(
  branchIdArb.map((id) => id as string | null),
  allBranchesArb,
)

// ---------------------------------------------------------------------------
// Property tests
// ---------------------------------------------------------------------------

describe('Branch header injection', () => {
  it('Property 3: resolveBranchHeader returns the branch ID for specific branches', () => {
    fc.assert(
      fc.property(branchIdArb, (branchId) => {
        const result = resolveBranchHeader(branchId)
        expect(result).toBe(branchId)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 3a: resolveBranchHeader returns null for "All Branches" (null)', () => {
    const result = resolveBranchHeader(null)
    expect(result).toBeNull()
  })

  it('Property 3b: resolveBranchHeader returns null for "All Branches" ("all")', () => {
    const result = resolveBranchHeader('all')
    expect(result).toBeNull()
  })

  it('Property 3c: resolveBranchHeader returns null for empty string', () => {
    const result = resolveBranchHeader('')
    expect(result).toBeNull()
  })

  it('Property 3d: for any branch selection, result is either the ID or null', () => {
    fc.assert(
      fc.property(branchSelectionArb, (selection) => {
        const result = resolveBranchHeader(selection)

        if (selection === null || selection === 'all' || selection === '') {
          expect(result).toBeNull()
        } else {
          expect(result).toBe(selection)
        }
      }),
      { numRuns: 200 },
    )
  })

  it('Property 3e: non-null results are always non-empty strings', () => {
    fc.assert(
      fc.property(branchIdArb, (branchId) => {
        const result = resolveBranchHeader(branchId)
        if (result !== null) {
          expect(typeof result).toBe('string')
          expect(result.length).toBeGreaterThan(0)
        }
      }),
      { numRuns: 200 },
    )
  })
})
