/**
 * Pure utility functions for webhook management.
 *
 * Extracted for property-based testing (Properties 10 & 11).
 */

/**
 * Returns true only if the URL starts with 'https://'.
 *
 * **Validates: Requirement 6.3** — HTTPS required for webhook URLs.
 * **Property 10: Webhook URL must be HTTPS**
 */
export function isValidWebhookUrl(url: string): boolean {
  return url.startsWith('https://')
}

export type WebhookHealthStatus = 'healthy' | 'degraded' | 'failing' | 'disabled'

/**
 * Determines the health status indicator for a webhook based on its
 * consecutive failure count and enabled state.
 *
 * - disabled: webhook is not enabled
 * - healthy: enabled with 0 consecutive failures
 * - degraded: enabled with 1–4 consecutive failures
 * - failing: enabled with 5+ consecutive failures
 *
 * **Validates: Requirements 6.6, 6.7**
 * **Property 11: Webhook health status indicator is deterministic**
 */
export function getWebhookHealthStatus(
  consecutiveFailures: number,
  isEnabled: boolean,
): WebhookHealthStatus {
  if (!isEnabled) return 'disabled'
  if (consecutiveFailures === 0) return 'healthy'
  if (consecutiveFailures >= 5) return 'failing'
  return 'degraded'
}
