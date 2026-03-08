/**
 * Pure utility functions for retention calculations.
 * Extracted for independent property-based testing and reuse across components.
 *
 * Validates: Requirements 5.2, 5.5
 */

/**
 * Calculate the outstanding retention balance.
 * outstanding = totalRetained - totalReleased
 */
export function calculateOutstandingRetention(
  totalRetained: number,
  totalReleased: number,
): number {
  return totalRetained - totalReleased
}

/**
 * Validate that a release amount is valid:
 * - Must be positive (> 0)
 * - Must not exceed the outstanding retention balance
 *
 * Returns { valid: true } or { valid: false, error: string }.
 */
export function validateReleaseAmount(
  releaseAmount: number,
  outstanding: number,
): { valid: boolean; error?: string } {
  if (releaseAmount <= 0) {
    return { valid: false, error: 'Release amount must be greater than zero' }
  }
  if (releaseAmount > outstanding) {
    return {
      valid: false,
      error: `Release amount ($${releaseAmount.toLocaleString(undefined, { minimumFractionDigits: 2 })}) exceeds outstanding retention ($${outstanding.toLocaleString(undefined, { minimumFractionDigits: 2 })})`,
    }
  }
  return { valid: true }
}

/**
 * Calculate the retention percentage relative to contract value.
 * Returns 0 when contractValue is 0 to avoid division by zero.
 */
export function calculateRetentionPercentage(
  totalRetained: number,
  contractValue: number,
): number {
  if (contractValue <= 0) return 0
  return (totalRetained / contractValue) * 100
}
