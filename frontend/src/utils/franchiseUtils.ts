/**
 * Pure utility functions for franchise RBAC scoping.
 *
 * Validates: Requirements 2.6, 2.7
 */

/**
 * Filter data items by user's assigned locations based on role.
 *
 * - Location_Manager: returns only items matching assigned locations
 * - Org_Admin / other roles: returns all items (org-level view)
 *
 * @param data - Array of items with a location identifier
 * @param userLocations - Location IDs assigned to the current user
 * @param role - The user's role
 * @param locationKey - The property name holding the location ID (default: 'location_id')
 */
export function filterByUserLocations<T>(
  data: T[],
  userLocations: string[],
  role: string,
  locationKey: string = 'location_id',
): T[] {
  if (role !== 'location_manager') return data
  if (!userLocations.length) return []
  const locationSet = new Set(userLocations)
  return data.filter((item) => {
    const val = (item as any)[locationKey]
    return typeof val === 'string' && locationSet.has(val)
  })
}
