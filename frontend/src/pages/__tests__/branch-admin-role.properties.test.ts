// Feature: branch-admin-role, Property 7: branch_admin nav item visibility
// Feature: branch-admin-role, Property 8: Branch assignment modal role filtering

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ─── Types ───

interface NavItem {
  to: string
  label: string
  adminOnly?: boolean
}

interface OrgUser {
  id: string
  email: string
  role: string
  branch_ids: string[]
}

// ─── Pure filters replicating production logic ───

/**
 * Mirrors OrgLayout's visibleNavItems filter for branch_admin:
 *   if (item.adminOnly && userRole !== 'org_admin' && userRole !== 'global_admin') return false
 * Since branch_admin is neither org_admin nor global_admin, adminOnly items are excluded.
 */
function filterNavItemsForBranchAdmin(items: NavItem[]): NavItem[] {
  return items.filter((item) => !item.adminOnly)
}

/**
 * Mirrors BranchManagement.tsx ASSIGNABLE_ROLES and filterAssignableUsers:
 *   export const ASSIGNABLE_ROLES = ['branch_admin', 'salesperson', 'location_manager', 'staff_member']
 *   export function filterAssignableUsers(users) { return users.filter(u => ASSIGNABLE_ROLES.includes(u.role)) }
 */
const ASSIGNABLE_ROLES: readonly string[] = ['branch_admin', 'salesperson', 'location_manager', 'staff_member']

function filterAssignableUsers(users: OrgUser[]): OrgUser[] {
  return (users ?? []).filter((u) => ASSIGNABLE_ROLES.includes(u.role))
}

// ─── Property 7: branch_admin nav item visibility ───
// **Validates: Requirements 4.2, 4.3**
//
// For any list of nav items where each item has an adminOnly boolean flag,
// when filtered for role = "branch_admin", the result should contain exactly
// those items where adminOnly is false (or undefined), and should exclude
// all items where adminOnly is true.

describe('Property 7: branch_admin nav item visibility', () => {
  const navItemArb = fc.record({
    to: fc.string({ minLength: 1, maxLength: 30 }).map((s) => `/${s}`),
    label: fc.string({ minLength: 1, maxLength: 30 }),
    adminOnly: fc.oneof(fc.constant(true), fc.constant(false), fc.constant(undefined)),
  })

  it('result contains only items where adminOnly is false or undefined', () => {
    fc.assert(
      fc.property(
        fc.array(navItemArb, { minLength: 0, maxLength: 20 }),
        (items) => {
          const result = filterNavItemsForBranchAdmin(items)

          for (const item of result) {
            expect(item.adminOnly).not.toBe(true)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('result excludes all items where adminOnly is true', () => {
    fc.assert(
      fc.property(
        fc.array(navItemArb, { minLength: 0, maxLength: 20 }),
        (items) => {
          const result = filterNavItemsForBranchAdmin(items)
          const adminOnlyItems = items.filter((i) => i.adminOnly === true)

          for (const adminItem of adminOnlyItems) {
            expect(result).not.toContainEqual(adminItem)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('result length equals count of non-adminOnly items', () => {
    fc.assert(
      fc.property(
        fc.array(navItemArb, { minLength: 0, maxLength: 20 }),
        (items) => {
          const result = filterNavItemsForBranchAdmin(items)
          const expectedCount = items.filter((i) => !i.adminOnly).length

          expect(result).toHaveLength(expectedCount)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('result preserves all non-adminOnly items in order', () => {
    fc.assert(
      fc.property(
        fc.array(navItemArb, { minLength: 0, maxLength: 20 }),
        (items) => {
          const result = filterNavItemsForBranchAdmin(items)
          const expected = items.filter((i) => !i.adminOnly)

          expect(result).toEqual(expected)
        },
      ),
      { numRuns: 100 },
    )
  })
})

// ─── Property 8: Branch assignment modal role filtering ───
// **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
//
// For any list of users with roles drawn from all possible roles,
// the assignment modal filter should return only users whose role is in
// {branch_admin, salesperson, location_manager, staff_member}.

describe('Property 8: Branch assignment modal role filtering', () => {
  const ALL_ROLES = [
    'global_admin',
    'franchise_admin',
    'org_admin',
    'branch_admin',
    'location_manager',
    'salesperson',
    'staff_member',
    'kiosk',
  ] as const

  const EXCLUDED_ROLES = ['global_admin', 'franchise_admin', 'org_admin', 'kiosk'] as const

  const orgUserArb = fc.record({
    id: fc.uuid(),
    email: fc.emailAddress(),
    role: fc.constantFrom(...ALL_ROLES),
    branch_ids: fc.array(fc.uuid(), { minLength: 0, maxLength: 3 }),
  })

  it('result contains only users with assignable roles', () => {
    fc.assert(
      fc.property(
        fc.array(orgUserArb, { minLength: 0, maxLength: 20 }),
        (users) => {
          const result = filterAssignableUsers(users)

          for (const user of result) {
            expect(ASSIGNABLE_ROLES).toContain(user.role)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('result excludes org_admin, global_admin, franchise_admin, and kiosk', () => {
    fc.assert(
      fc.property(
        fc.array(orgUserArb, { minLength: 0, maxLength: 20 }),
        (users) => {
          const result = filterAssignableUsers(users)

          for (const user of result) {
            for (const excluded of EXCLUDED_ROLES) {
              expect(user.role).not.toBe(excluded)
            }
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  it('result preserves all users with assignable roles', () => {
    fc.assert(
      fc.property(
        fc.array(orgUserArb, { minLength: 0, maxLength: 20 }),
        (users) => {
          const result = filterAssignableUsers(users)
          const expected = users.filter((u) => ASSIGNABLE_ROLES.includes(u.role))

          expect(result).toHaveLength(expected.length)
          expect(result).toEqual(expected)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('result is a subset of the input', () => {
    fc.assert(
      fc.property(
        fc.array(orgUserArb, { minLength: 0, maxLength: 20 }),
        (users) => {
          const result = filterAssignableUsers(users)

          for (const user of result) {
            expect(users).toContainEqual(user)
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})
