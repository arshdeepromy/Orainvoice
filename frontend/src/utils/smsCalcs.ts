/**
 * Pure SMS billing calculation functions.
 * These mirror the backend logic in app/modules/admin/service.py.
 */

/**
 * Compute SMS overage: the number of messages sent beyond the included quota.
 * Always returns a non-negative integer.
 */
export function computeSmsOverage(totalSent: number, includedQuota: number): number {
  return Math.max(0, totalSent - includedQuota)
}

/**
 * Compute the effective SMS quota for an organisation.
 * When smsIncluded is false, the effective quota is always 0 regardless of
 * the plan quota or package credits.
 */
export function getEffectiveSmsQuota(
  smsIncluded: boolean,
  planQuota: number,
  packageCreditsRemaining: number,
): number {
  if (!smsIncluded) return 0
  return planQuota + packageCreditsRemaining
}

/**
 * Compute the overage charge in NZD.
 * Overage charge = overage count × per-SMS cost.
 */
export function computeOverageCharge(overageCount: number, perSmsCost: number): number {
  return overageCount * perSmsCost
}
