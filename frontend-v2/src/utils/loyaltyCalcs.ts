/**
 * Pure utility functions for loyalty program calculations.
 *
 * Extracted for property-based testing (Properties 19, 20, 21).
 */

/**
 * Returns true if all tier thresholds are strictly ascending.
 *
 * Property 19: Loyalty tier thresholds are strictly ascending.
 * Validates: Requirements 10.3
 */
export function areTiersAscending(tiers: { threshold: number }[]): boolean {
  for (let i = 1; i < tiers.length; i++) {
    if (tiers[i].threshold <= tiers[i - 1].threshold) {
      return false
    }
  }
  return true
}

/**
 * Returns the number of points needed to reach the next tier,
 * or null if the customer is already at the highest tier.
 *
 * Property 20: Loyalty points to next tier calculation.
 * Validates: Requirements 10.4
 */
export function calculatePointsToNextTier(
  currentPoints: number,
  tiers: { threshold: number }[],
): number | null {
  if (tiers.length === 0) return null

  // Find the next tier whose threshold is strictly greater than currentPoints
  const sorted = [...tiers].sort((a, b) => a.threshold - b.threshold)
  for (const tier of sorted) {
    if (tier.threshold > currentPoints) {
      return tier.threshold - currentPoints
    }
  }

  // Already at or above the highest tier
  return null
}

/**
 * Validates a manual points adjustment: amount must be non-zero
 * and reason must be non-empty (after trimming whitespace).
 *
 * Property 21: Loyalty points adjustment requires reason.
 * Validates: Requirements 10.6
 */
export function validatePointsAdjustment(
  amount: number,
  reason: string,
): { valid: boolean; error?: string } {
  if (amount === 0) {
    return { valid: false, error: 'Adjustment amount must be non-zero' }
  }
  if (!reason || reason.trim().length === 0) {
    return { valid: false, error: 'A reason is required for points adjustments' }
  }
  return { valid: true }
}
