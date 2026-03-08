/**
 * Pure utility functions for module management calculations.
 * Extracted for property-based testing.
 */

export interface ModuleWithDependents {
  slug: string
  dependents: string[]
}

export interface ModuleWithDependencies {
  slug: string
  dependencies: string[]
}

export interface ModuleWithStatus {
  status: string
}

/**
 * Returns the list of module slugs that would be disabled when disabling
 * the given module (cascade). Includes transitive dependents.
 *
 * For example, if module A has dependents [B, C] and B has dependents [D],
 * then cascadeDisable('A', modules) returns ['B', 'C', 'D'].
 */
export function cascadeDisable(
  moduleSlug: string,
  modules: ModuleWithDependents[],
): string[] {
  const moduleMap = new Map<string, string[]>()
  for (const m of modules) {
    moduleMap.set(m.slug, m.dependents)
  }

  const result: string[] = []
  const visited = new Set<string>()
  const queue = [moduleSlug]

  while (queue.length > 0) {
    const current = queue.shift()!
    const dependents = moduleMap.get(current) ?? []
    for (const dep of dependents) {
      if (!visited.has(dep)) {
        visited.add(dep)
        result.push(dep)
        queue.push(dep)
      }
    }
  }

  return result
}

/**
 * Returns the list of module slugs that must be auto-enabled when enabling
 * the given module. Includes transitive dependencies.
 *
 * For example, if module D depends on [B, C] and B depends on [A],
 * then autoEnableDependencies('D', modules) returns ['B', 'C', 'A'].
 */
export function autoEnableDependencies(
  moduleSlug: string,
  modules: ModuleWithDependencies[],
): string[] {
  const moduleMap = new Map<string, string[]>()
  for (const m of modules) {
    moduleMap.set(m.slug, m.dependencies)
  }

  const result: string[] = []
  const visited = new Set<string>()
  const queue = [moduleSlug]

  while (queue.length > 0) {
    const current = queue.shift()!
    const dependencies = moduleMap.get(current) ?? []
    for (const dep of dependencies) {
      if (!visited.has(dep)) {
        visited.add(dep)
        result.push(dep)
        queue.push(dep)
      }
    }
  }

  return result
}

/**
 * Returns true if the module has a 'coming_soon' status.
 */
export function isComingSoon(module: ModuleWithStatus): boolean {
  return module.status === 'coming_soon'
}
