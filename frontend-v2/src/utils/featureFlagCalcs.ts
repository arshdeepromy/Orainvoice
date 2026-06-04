/**
 * Pure utility functions for feature flag calculations.
 * These are extracted for property-based testing.
 */

export interface FlagBase {
  can_override: boolean
}

export interface FlagWithCategory {
  category: string
  key: string
  enabled: boolean
  can_override: boolean
}

export interface FlagForValidation {
  category: string
  key: string
  description?: string
}

/**
 * Returns whether a flag can be overridden at org level.
 */
export function canOverrideFlag(flag: FlagBase): boolean {
  return flag.can_override === true
}

/**
 * Groups flags by their category field.
 * Returns a record mapping category names to arrays of flags in that category.
 */
export function groupFlagsByCategory<T extends FlagWithCategory>(
  flags: T[],
): Record<string, T[]> {
  const groups: Record<string, T[]> = {}
  for (const flag of flags) {
    const cat = flag.category || 'Uncategorized'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(flag)
  }
  return groups
}

/**
 * Validates that a flag has required fields: non-empty category and non-empty key.
 */
export function validateFlagCategory(flag: FlagForValidation): boolean {
  if (!flag.category || flag.category.trim().length === 0) return false
  if (!flag.key || flag.key.trim().length === 0) return false
  return true
}
