/**
 * Simple navigation guard using a global variable.
 * No React context needed — avoids circular dependency issues.
 *
 * Usage:
 * - Form registers: setNavigationGuard({ isDirty: () => bool, onSave: async () => void })
 * - Form unregisters on unmount: clearNavigationGuard()
 * - Layout checks before navigating: checkNavigationGuard() returns the guard or null
 *
 * Ported VERBATIM from frontend/src/utils/navigationGuard.ts (Task 19).
 */

export interface NavigationGuardDef {
  isDirty: () => boolean
  onSave: () => Promise<void>
}

let _guard: NavigationGuardDef | null = null

export function setNavigationGuard(guard: NavigationGuardDef) {
  _guard = guard
}

export function clearNavigationGuard() {
  _guard = null
}

/** Returns the guard if form is dirty, null if safe to navigate */
export function checkNavigationGuard(): NavigationGuardDef | null {
  if (_guard && _guard.isDirty()) return _guard
  return null
}
