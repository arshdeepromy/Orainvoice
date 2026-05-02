/**
 * Utility functions for generating portal share links.
 *
 * Requirements: 25.1, 25.2, 25.3, 25.4
 */

/**
 * Build the portal URL for sharing with a customer.
 * Uses the customer's portal token to generate the correct URL format:
 * `/portal/{customer_portal_token}`
 *
 * Returns null if the customer has no portal token.
 */
export function buildPortalUrl(
  origin: string,
  customerPortalToken: string | null | undefined,
): string | null {
  if (!customerPortalToken) return null
  return `${origin}/portal/${customerPortalToken}`
}

/**
 * Determine whether the "Share Portal Link" button should be visible.
 * The button is hidden when:
 * - The customer has no portal token
 * - Portal access is disabled for the customer
 */
export function canSharePortalLink(
  customerPortalToken: string | null | undefined,
  customerEnablePortal: boolean | undefined,
): boolean {
  return !!customerPortalToken && !!customerEnablePortal
}
