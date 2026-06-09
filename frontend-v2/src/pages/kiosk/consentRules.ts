/**
 * Pure per-vehicle row-resolution rules for the kiosk reminder-consent step.
 *
 * Requirements 1.5a–1.5e: each vehicle row shows exactly ONE inspection-type
 * checkbox — WOF, COF, or none — derived from the vehicle's `inspection_type`
 * and its expiry dates. Kept I/O-free so it can be unit-tested in isolation.
 */

import type { ReminderConsentVehicle } from './types'

export type InspectionRow = 'wof' | 'cof' | 'none'

/**
 * Resolve which inspection-type checkbox a vehicle row should render.
 *
 * - explicit `inspection_type` wins (5a/5b)
 * - both expiries populated with no explicit type → prefer COF, the
 *   heavier-compliance inspection (5c)
 * - only one expiry populated → that one (5c)
 * - neither populated and no type → no inspection row (5d)
 */
export function resolveInspectionTypeRow(
  v: Pick<ReminderConsentVehicle, 'inspection_type' | 'wof_expiry' | 'cof_expiry'>,
): InspectionRow {
  if (v.inspection_type === 'cof') return 'cof'
  if (v.inspection_type === 'wof') return 'wof'
  // No explicit inspection_type — fall back to the expiry dates present.
  if (v.wof_expiry && v.cof_expiry) return 'cof'
  if (v.cof_expiry && !v.wof_expiry) return 'cof'
  if (v.wof_expiry && !v.cof_expiry) return 'wof'
  return 'none'
}

/** Map a resolved inspection row to its reminder category, or null for none. */
export function inspectionCategory(
  row: InspectionRow,
): 'wof_expiry' | 'cof_expiry' | null {
  if (row === 'wof') return 'wof_expiry'
  if (row === 'cof') return 'cof_expiry'
  return null
}
