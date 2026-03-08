/**
 * Pure utility functions for tipping calculations.
 *
 * Extracted for property-based testing (Property 30).
 * Validates: Requirements 15.3
 */

export interface StaffShare {
  id: string
  share: number
}

export interface StaffAllocation {
  id: string
  amount: number
}

/**
 * Distributes a total tip proportionally by share among staff members.
 * Handles rounding so that the sum of all allocations equals totalTip exactly.
 *
 * For equal split: pass equal share values (e.g. share=1 for each).
 * For percentage-based: pass share as the percentage (e.g. share=40, share=60).
 * For role-based: pass share as the role weight.
 *
 * Property 30: Tip distribution allocation is correct.
 * Validates: Requirements 15.3
 */
export function distributeTips(
  totalTip: number,
  staff: StaffShare[],
): StaffAllocation[] {
  if (staff.length === 0 || totalTip <= 0) return []

  const totalShares = staff.reduce((sum, s) => sum + s.share, 0)
  if (totalShares <= 0) return []

  // Calculate raw amounts and floor to 2 decimal places
  const raw = staff.map((s) => ({
    id: s.id,
    exact: (totalTip * s.share) / totalShares,
  }))

  const floored = raw.map((r) => ({
    id: r.id,
    amount: Math.floor(r.exact * 100) / 100,
    remainder: r.exact * 100 - Math.floor(r.exact * 100),
  }))

  // Distribute the leftover cents using largest-remainder method
  const flooredTotal = floored.reduce((sum, f) => sum + f.amount, 0)
  let remainingCents = Math.round((totalTip - flooredTotal) * 100)

  // Sort by remainder descending to allocate extra cents fairly
  const sorted = [...floored].sort((a, b) => b.remainder - a.remainder)

  for (const entry of sorted) {
    if (remainingCents <= 0) break
    entry.amount = Math.round((entry.amount + 0.01) * 100) / 100
    remainingCents--
  }

  // Build result in original order
  const amountMap = new Map(sorted.map((e) => [e.id, e.amount]))
  return staff.map((s) => ({
    id: s.id,
    amount: amountMap.get(s.id) ?? 0,
  }))
}
