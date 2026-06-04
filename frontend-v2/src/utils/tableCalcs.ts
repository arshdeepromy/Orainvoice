/**
 * Pure utility functions for table/floor-plan calculations.
 *
 * Extracted for property-based testing (Property 29).
 */

/**
 * Returns the CSS colour token for a given table status.
 *
 * Property 29: Table status colour coding is deterministic.
 * Validates: Requirements 14.2
 *
 * Available  → green
 * Occupied   → amber
 * Reserved   → blue
 * Needs Cleaning → red
 * default    → gray
 */
export function getTableStatusColor(status: string): string {
  switch (status.toLowerCase().replace(/[\s_]+/g, '_')) {
    case 'available':
      return 'green'
    case 'occupied':
      return 'amber'
    case 'reserved':
      return 'blue'
    case 'needs_cleaning':
      return 'red'
    default:
      return 'gray'
  }
}
