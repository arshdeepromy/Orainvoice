/**
 * Conditional / dependent fields — dependency graph pure core (R14) — advisory.
 *
 * A Field_Dependency records that one placed field (the **dependent**) is
 * conditionally shown or required based on the value of **another** field (the
 * **trigger**) in the same Field_Set. Documenso's v2 field model has no
 * cross-field conditional primitive, so this dependency model is stored on
 * OraInvoice and is **advisory** at signing time (R14.6–R14.8); this module is
 * only concerned with the structural validity of the dependency graph.
 *
 * The dependency edges form a directed graph where each edge points from a
 * dependent field to its trigger field (dependent → trigger). For the graph to
 * be well-formed:
 *   - a field may never trigger itself — a self-loop is rejected (R14.2);
 *   - adding an edge that would close a cycle is rejected (R14.4);
 *   - a rejected dependency is never stored.
 *
 * Every function here is pure, total, and free of I/O, making the acyclicity
 * invariant straightforward to property-test (Property 20, Task 17.2). This
 * module is extracted to the shared core for the mobile editor in Task 23.
 */

/** The supported Dependency_Condition set (R14.3). */
export type DependencyCondition =
  | 'is_checked'
  | 'is_not_checked'
  | 'equals'
  | 'not_equals'
  | 'is_filled'
  | 'is_empty'

/** The advisory effect a satisfied condition has on the dependent field (R14.1). */
export type DependencyEffect = 'show' | 'require'

/**
 * A single field dependency: the `dependentClientId` field's `effect` is driven
 * by the `triggerClientId` field meeting `condition`. `value` carries the
 * comparison operand for value-based conditions (`equals` / `not_equals`); it is
 * unused by the boolean/presence conditions.
 */
export interface FieldDependency {
  dependentClientId: string
  triggerClientId: string
  condition: DependencyCondition
  effect: DependencyEffect
  value?: string
}

/** Result of attempting to add a dependency to the graph. */
export type AddDependencyResult =
  | { ok: true; deps: FieldDependency[] }
  | { ok: false; reason: 'self' | 'cycle' }

/**
 * Whether `target` is reachable from `start` by following dependent → trigger
 * edges in `deps`. Iterative depth-first traversal so it is total and safe on
 * large/duplicated edge sets.
 */
function reaches(deps: FieldDependency[], start: string, target: string): boolean {
  const stack: string[] = [start]
  const seen = new Set<string>()
  while (stack.length > 0) {
    const node = stack.pop() as string
    if (node === target) return true
    if (seen.has(node)) continue
    seen.add(node)
    for (const dep of deps) {
      if (dep.dependentClientId === node) {
        stack.push(dep.triggerClientId)
      }
    }
  }
  return false
}

/**
 * Whether adding the dependent → trigger edge would close a cycle in `deps`.
 * A cycle is closed iff the dependent is already reachable from the trigger
 * (i.e. `trigger → … → dependent` exists), since the new edge supplies the
 * `dependent → trigger` link that completes the loop. A self-loop also closes a
 * cycle but is reported separately via {@link isSelfLoop}.
 */
export function wouldCreateCycle(deps: FieldDependency[], edge: FieldDependency): boolean {
  if (isSelfLoop(edge)) return true
  return reaches(deps, edge.triggerClientId, edge.dependentClientId)
}

/** Whether the edge's trigger is the dependent itself (a forbidden self-loop, R14.2). */
export function isSelfLoop(edge: FieldDependency): boolean {
  return edge.dependentClientId === edge.triggerClientId
}

/**
 * Whether the directed graph formed by `deps` (dependent → trigger edges) is
 * acyclic. Returns `false` if any self-loop or directed cycle is present. Pure
 * and total — used to validate a whole submitted dependency set.
 */
export function isAcyclic(deps: FieldDependency[]): boolean {
  for (const dep of deps) {
    if (isSelfLoop(dep)) return false
  }
  // Detect a cycle via DFS with a recursion (grey) set over the edge list.
  const adjacency = new Map<string, string[]>()
  for (const dep of deps) {
    const targets = adjacency.get(dep.dependentClientId)
    if (targets) targets.push(dep.triggerClientId)
    else adjacency.set(dep.dependentClientId, [dep.triggerClientId])
  }

  const visited = new Set<string>() // fully explored (black)
  const inStack = new Set<string>() // on the current DFS path (grey)

  const hasCycleFrom = (root: string): boolean => {
    // Iterative DFS tracking entry/exit to maintain the grey set.
    const stack: Array<{ node: string; childIndex: number }> = [{ node: root, childIndex: 0 }]
    inStack.add(root)
    while (stack.length > 0) {
      const frame = stack[stack.length - 1]
      const children = adjacency.get(frame.node) ?? []
      if (frame.childIndex < children.length) {
        const next = children[frame.childIndex]
        frame.childIndex += 1
        if (inStack.has(next)) return true
        if (!visited.has(next)) {
          inStack.add(next)
          stack.push({ node: next, childIndex: 0 })
        }
      } else {
        inStack.delete(frame.node)
        visited.add(frame.node)
        stack.pop()
      }
    }
    return false
  }

  for (const node of adjacency.keys()) {
    if (!visited.has(node)) {
      // A detected cycle means the graph is NOT acyclic.
      if (hasCycleFrom(node)) return false
    }
  }
  // No self-loop and no directed cycle → the graph is acyclic.
  return true
}

/**
 * Attempt to add `edge` to the dependency set `deps`. Rejects a self-loop
 * (`reason: 'self'`, R14.2) and an edge that would close a cycle over the
 * existing dependent → trigger edges (`reason: 'cycle'`, R14.4); a rejected
 * dependency is never added. On success returns a **new** array with the edge
 * appended (the input is not mutated). Pure, no I/O.
 */
export function addDependency(
  deps: FieldDependency[],
  edge: FieldDependency,
): AddDependencyResult {
  if (isSelfLoop(edge)) {
    return { ok: false, reason: 'self' }
  }
  if (reaches(deps, edge.triggerClientId, edge.dependentClientId)) {
    return { ok: false, reason: 'cycle' }
  }
  return { ok: true, deps: [...deps, edge] }
}
