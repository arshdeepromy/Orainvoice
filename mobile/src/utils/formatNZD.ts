/**
 * Format a numeric value as NZD currency.
 *
 * Returns a string starting with "NZD" followed by a locale-formatted
 * number with exactly 2 decimal places.
 *
 * Handles null and undefined by treating them as 0.
 *
 * Examples:
 *   formatNZD(1234.5)    → "NZD1,234.50"
 *   formatNZD(0)         → "NZD0.00"
 *   formatNZD(null)      → "NZD0.00"
 *   formatNZD(undefined) → "NZD0.00"
 *   formatNZD(-50)       → "NZD-50.00"
 *
 * Requirements: 56.4
 */
export function formatNZD(value: number | null | undefined): string {
  return `NZD${Number(value ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}
