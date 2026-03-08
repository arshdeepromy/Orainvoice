/**
 * Pure utility functions for progress claim calculations.
 * Extracted for independent testing and reuse across components.
 *
 * Validates: Requirements 3.4, 3.5
 */

export interface ProgressClaimInputs {
  originalContractValue: number
  approvedVariations: number
  workCompletedToDate: number
  workCompletedPrevious: number
  materialsOnSite: number
  retentionWithheld: number
}

export interface ProgressClaimCalculated {
  revisedContractValue: number
  workCompletedThisPeriod: number
  amountDue: number
  completionPercentage: number
}

/**
 * Calculate all derived progress claim fields from input values.
 *
 * - revised_contract_value = original + approved_variations
 * - work_completed_this_period = work_to_date - work_previous
 * - amount_due = work_this_period + materials - retention
 * - completion_percentage = (work_to_date / revised_contract_value) * 100
 */
export function calculateProgressClaimFields(
  values: ProgressClaimInputs,
): ProgressClaimCalculated {
  const revisedContractValue =
    values.originalContractValue + values.approvedVariations

  const workCompletedThisPeriod =
    values.workCompletedToDate - values.workCompletedPrevious

  const amountDue =
    workCompletedThisPeriod + values.materialsOnSite - values.retentionWithheld

  const completionPercentage =
    revisedContractValue > 0
      ? (values.workCompletedToDate / revisedContractValue) * 100
      : 0

  return {
    revisedContractValue,
    workCompletedThisPeriod,
    amountDue,
    completionPercentage,
  }
}

/**
 * Validate that cumulative claimed amount does not exceed revised contract value.
 * Returns an error message if validation fails, or null if valid.
 */
export function validateCumulativeNotExceeded(
  cumulativeClaimed: number,
  amountThisClaim: number,
  revisedContractValue: number,
): string | null {
  const total = cumulativeClaimed + amountThisClaim
  if (revisedContractValue > 0 && total > revisedContractValue) {
    const maxClaimable = Math.max(0, revisedContractValue - cumulativeClaimed)
    return `Cumulative claimed ($${total.toLocaleString()}) exceeds revised contract value ($${revisedContractValue.toLocaleString()}). Maximum claimable: $${maxClaimable.toLocaleString()}`
  }
  return null
}
