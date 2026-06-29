import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: esignature-field-placement, Property 20: Dependency graph stays acyclic
// **Validates: Requirements 14.2, 14.4**
//
// A Field_Dependency points from a dependent field to the trigger field that
// drives it (dependent -> trigger). The stored dependency graph must never
// contain a self-loop (a field triggering itself, R14.2) nor a directed cycle
// (R14.4). `addDependency` is the only mutator: it rejects a self-loop and an
// edge that would close a cycle, and never stores a rejected edge.
//
// This property folds an arbitrary sequence of candidate edges over a fixed,
// small Field_Set through `addDependency`, keeping only accepted edges, and
// asserts:
//   - an add is rejected iff its trigger equals its dependent (self-loop) or it
//     would close a cycle (`wouldCreateCycle`), with the matching reason;
//   - a rejected edge is never appended to the stored set;
//   - the accepted set is acyclic and self-loop-free at every step
//     (`isAcyclic` holds, `isSelfLoop` holds for no stored edge).

import {
  addDependency,
  isAcyclic,
  isSelfLoop,
  wouldCreateCycle,
  type DependencyCondition,
  type DependencyEffect,
  type FieldDependency,
} from './dependencyGraph'

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/*                                                                     */
/*  A small fixed Field_Set keeps cycles and self-loops likely so the  */
/*  rejection branches are exercised frequently within 100 runs.       */
/* ------------------------------------------------------------------ */

const FIELD_IDS = ['f0', 'f1', 'f2', 'f3', 'f4'] as const

const fieldIdArb = fc.constantFrom(...FIELD_IDS)

const conditionArb = fc.constantFrom<DependencyCondition>(
  'is_checked',
  'is_not_checked',
  'equals',
  'not_equals',
  'is_filled',
  'is_empty',
)

const effectArb = fc.constantFrom<DependencyEffect>('show', 'require')

const edgeArb: fc.Arbitrary<FieldDependency> = fc.record({
  dependentClientId: fieldIdArb,
  triggerClientId: fieldIdArb,
  condition: conditionArb,
  effect: effectArb,
  value: fc.option(fc.string(), { nil: undefined }),
})

/** A sequence of candidate edges to fold through `addDependency`. */
const edgeSequenceArb = fc.array(edgeArb, { minLength: 0, maxLength: 30 })

/* ------------------------------------------------------------------ */
/*  Property 20                                                        */
/* ------------------------------------------------------------------ */

describe('Property 20: Dependency graph stays acyclic', () => {
  it('rejects self-loops and cycle-closing edges, keeps every accepted set acyclic', () => {
    // Concrete anchors: a self-loop and a cycle-closing edge are both rejected
    // and never stored, regardless of generation luck.
    const selfLoop: FieldDependency = {
      dependentClientId: 'f0',
      triggerClientId: 'f0',
      condition: 'is_checked',
      effect: 'show',
    }
    const selfResult = addDependency([], selfLoop)
    expect(selfResult.ok).toBe(false)
    if (!selfResult.ok) expect(selfResult.reason).toBe('self')

    // f0 -> f1 accepted, then f1 -> f0 would close the cycle f0 -> f1 -> f0.
    const accepted = addDependency([], {
      dependentClientId: 'f0',
      triggerClientId: 'f1',
      condition: 'is_checked',
      effect: 'show',
    })
    expect(accepted.ok).toBe(true)
    if (accepted.ok) {
      const cycleEdge: FieldDependency = {
        dependentClientId: 'f1',
        triggerClientId: 'f0',
        condition: 'is_checked',
        effect: 'show',
      }
      const cycleResult = addDependency(accepted.deps, cycleEdge)
      expect(cycleResult.ok).toBe(false)
      if (!cycleResult.ok) expect(cycleResult.reason).toBe('cycle')
    }

    fc.assert(
      fc.property(edgeSequenceArb, (edges) => {
        let deps: FieldDependency[] = []

        for (const edge of edges) {
          const shouldReject = wouldCreateCycle(deps, edge)
          const expectedReason = isSelfLoop(edge) ? 'self' : 'cycle'
          const before = deps

          const result = addDependency(deps, edge)

          // Accepted iff the edge would NOT create a cycle (self-loop included).
          expect(result.ok).toBe(!shouldReject)

          if (!result.ok) {
            // Rejected: correct reason, and nothing is stored.
            expect(result.reason).toBe(expectedReason)
            expect(deps).toBe(before)
          } else {
            // Accepted: the new edge is appended to a fresh array.
            expect(result.deps.length).toBe(before.length + 1)
            expect(result.deps[result.deps.length - 1]).toEqual(edge)
            deps = result.deps
          }

          // Invariant after every step: acyclic and free of self-loops.
          expect(isAcyclic(deps)).toBe(true)
          expect(deps.some((d) => isSelfLoop(d))).toBe(false)
        }
      }),
      { numRuns: 100 },
    )
  })
})
