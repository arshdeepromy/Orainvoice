/**
 * Pure utility functions for variation order calculations.
 * Extracted for independent testing and reuse across components.
 *
 * Validates: Requirements 4.4, 4.6
 */

/**
 * Calculate the revised contract value from the original value
 * plus the sum of all approved variation cost impacts.
 *
 * Property 7: approved_variation ⇒ revised_contract = original + Σ(approved cost_impacts)
 */
export function calculateRevisedContractValue(
  originalValue: number,
  approvedVariations: { cost_impact: number }[],
): number {
  const total = approvedVariations.reduce(
    (sum, v) => sum + v.cost_impact,
    0,
  )
  return originalValue + total
}

/**
 * Determine whether a variation order is immutable (cannot be edited or deleted).
 * Approved and rejected variations are immutable.
 *
 * Property 8: approved variations cannot be edited or deleted
 */
export function isVariationImmutable(status: string): boolean {
  return status === 'approved' || status === 'rejected'
}
