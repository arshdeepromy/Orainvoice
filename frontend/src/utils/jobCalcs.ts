/**
 * Pure utility functions for job calculations.
 * Extracted for property-based testing (Properties 15, 16).
 */

/**
 * Valid job status transitions map.
 *
 * Property 15: Job status transitions are validated
 * Validates: Requirements 8.3
 */
const VALID_TRANSITIONS: Record<string, string[]> = {
  draft: ['quoted', 'cancelled'],
  quoted: ['accepted', 'cancelled'],
  accepted: ['in_progress', 'cancelled'],
  in_progress: ['completed'],
  completed: ['invoiced'],
  invoiced: [],
  cancelled: [],
}

/**
 * Check whether a status transition is valid.
 *
 * Property 15: Job status transitions are validated
 * Validates: Requirements 8.3
 */
export function isValidStatusTransition(from: string, to: string): boolean {
  const allowed = VALID_TRANSITIONS[from]
  if (!allowed) return false
  return allowed.includes(to)
}

export interface JobProfitability {
  margin: number
  marginPercentage: number
}

/**
 * Calculate job profitability from revenue and costs.
 * margin = revenue - costs
 * marginPercentage = (margin / revenue) * 100, or 0 if revenue is 0
 *
 * Property 16: Job profitability calculation is correct
 * Validates: Requirements 8.5
 */
export function calculateJobProfitability(
  revenue: number,
  costs: number,
): JobProfitability {
  const margin = revenue - costs
  const marginPercentage = revenue === 0 ? 0 : (margin / revenue) * 100
  return { margin, marginPercentage }
}
