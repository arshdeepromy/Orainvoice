/**
 * Shared helper functions for vehicle inspection type display.
 * Determines whether to show WOF or COF labels and expiry dates
 * based on the vehicle's inspection_type field.
 */

export function getInspectionLabel(
  vehicle: { inspection_type?: string | null }
): string {
  if (vehicle?.inspection_type === 'cof') return 'COF Expiry'
  return 'WOF Expiry'
}

export function getInspectionExpiry(
  vehicle: {
    wof_expiry?: string | null
    cof_expiry?: string | null
    inspection_type?: string | null
  }
): string | null {
  if (vehicle?.inspection_type === 'cof') return vehicle?.cof_expiry ?? null
  return vehicle?.wof_expiry ?? null
}
