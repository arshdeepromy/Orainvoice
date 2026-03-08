import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  cascadeDisable,
  autoEnableDependencies,
  isComingSoon,
} from '../utils/moduleCalcs'

// Feature: production-readiness-gaps, Property 24: Module disable cascades to dependents
// Feature: production-readiness-gaps, Property 25: Module enable auto-enables dependencies
// Feature: production-readiness-gaps, Property 26: Coming soon modules are non-selectable
// **Validates: Requirements 12.3, 12.4, 12.5**

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

/** Generate a module slug */
const slugArb = fc
  .string({ minLength: 1, maxLength: 30 })
  .filter((s) => s.trim().length > 0)
  .map((s) => s.replace(/\s+/g, '_'))

/** Generate a unique list of slugs */
const uniqueSlugsArb = (min: number, max: number) =>
  fc
    .uniqueArray(slugArb, { minLength: min, maxLength: max, comparator: 'IsStrictlyEqual' })

/** Generate a module status */
const moduleStatusArb = fc.constantFrom('available', 'coming_soon')

/* ------------------------------------------------------------------ */
/*  Property 24: Module disable cascades to dependents                 */
/* ------------------------------------------------------------------ */

describe('Property 24: Module disable cascades to dependents', () => {
  it('returns empty array when module has no dependents', () => {
    fc.assert(
      fc.property(slugArb, (slug) => {
        const modules = [{ slug, dependents: [] }]
        const result = cascadeDisable(slug, modules)
        expect(result).toHaveLength(0)
      }),
      { numRuns: 100 },
    )
  })

  it('returns direct dependents for a single-level cascade', () => {
    fc.assert(
      fc.property(
        uniqueSlugsArb(3, 8),
        (slugs) => {
          const [target, ...deps] = slugs
          const modules = [
            { slug: target, dependents: deps },
            ...deps.map((d) => ({ slug: d, dependents: [] })),
          ]
          const result = cascadeDisable(target, modules)
          // All direct dependents must be in the result
          for (const dep of deps) {
            expect(result).toContain(dep)
          }
          expect(result).toHaveLength(deps.length)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('includes transitive dependents in cascade', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(3, 3), (slugs) => {
        const [a, b, c] = slugs
        // A -> B -> C (chain)
        const modules = [
          { slug: a, dependents: [b] },
          { slug: b, dependents: [c] },
          { slug: c, dependents: [] },
        ]
        const result = cascadeDisable(a, modules)
        expect(result).toContain(b)
        expect(result).toContain(c)
        expect(result).toHaveLength(2)
      }),
      { numRuns: 100 },
    )
  })

  it('does not include the disabled module itself in the result', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(2, 6), (slugs) => {
        const [target, ...deps] = slugs
        const modules = [
          { slug: target, dependents: deps },
          ...deps.map((d) => ({ slug: d, dependents: [] })),
        ]
        const result = cascadeDisable(target, modules)
        expect(result).not.toContain(target)
      }),
      { numRuns: 100 },
    )
  })

  it('handles diamond dependency graphs without duplicates', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(4, 4), (slugs) => {
        const [a, b, c, d] = slugs
        // A -> B, A -> C, B -> D, C -> D (diamond)
        const modules = [
          { slug: a, dependents: [b, c] },
          { slug: b, dependents: [d] },
          { slug: c, dependents: [d] },
          { slug: d, dependents: [] },
        ]
        const result = cascadeDisable(a, modules)
        // D should appear only once
        const uniqueResult = [...new Set(result)]
        expect(result).toHaveLength(uniqueResult.length)
        expect(result).toContain(b)
        expect(result).toContain(c)
        expect(result).toContain(d)
      }),
      { numRuns: 100 },
    )
  })

  it('returns empty array for unknown module slug', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(2, 5), (slugs) => {
        const modules = slugs.map((s) => ({ slug: s, dependents: [] }))
        const result = cascadeDisable('nonexistent_module', modules)
        expect(result).toHaveLength(0)
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 25: Module enable auto-enables dependencies               */
/* ------------------------------------------------------------------ */

describe('Property 25: Module enable auto-enables dependencies', () => {
  it('returns empty array when module has no dependencies', () => {
    fc.assert(
      fc.property(slugArb, (slug) => {
        const modules = [{ slug, dependencies: [] }]
        const result = autoEnableDependencies(slug, modules)
        expect(result).toHaveLength(0)
      }),
      { numRuns: 100 },
    )
  })

  it('returns direct dependencies for a single-level enable', () => {
    fc.assert(
      fc.property(
        uniqueSlugsArb(3, 8),
        (slugs) => {
          const [target, ...deps] = slugs
          const modules = [
            { slug: target, dependencies: deps },
            ...deps.map((d) => ({ slug: d, dependencies: [] })),
          ]
          const result = autoEnableDependencies(target, modules)
          for (const dep of deps) {
            expect(result).toContain(dep)
          }
          expect(result).toHaveLength(deps.length)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('includes transitive dependencies', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(3, 3), (slugs) => {
        const [a, b, c] = slugs
        // A depends on B, B depends on C
        const modules = [
          { slug: a, dependencies: [b] },
          { slug: b, dependencies: [c] },
          { slug: c, dependencies: [] },
        ]
        const result = autoEnableDependencies(a, modules)
        expect(result).toContain(b)
        expect(result).toContain(c)
        expect(result).toHaveLength(2)
      }),
      { numRuns: 100 },
    )
  })

  it('does not include the enabled module itself in the result', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(2, 6), (slugs) => {
        const [target, ...deps] = slugs
        const modules = [
          { slug: target, dependencies: deps },
          ...deps.map((d) => ({ slug: d, dependencies: [] })),
        ]
        const result = autoEnableDependencies(target, modules)
        expect(result).not.toContain(target)
      }),
      { numRuns: 100 },
    )
  })

  it('handles shared dependencies without duplicates', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(4, 4), (slugs) => {
        const [a, b, c, d] = slugs
        // A depends on [B, C], B depends on [D], C depends on [D]
        const modules = [
          { slug: a, dependencies: [b, c] },
          { slug: b, dependencies: [d] },
          { slug: c, dependencies: [d] },
          { slug: d, dependencies: [] },
        ]
        const result = autoEnableDependencies(a, modules)
        const uniqueResult = [...new Set(result)]
        expect(result).toHaveLength(uniqueResult.length)
        expect(result).toContain(b)
        expect(result).toContain(c)
        expect(result).toContain(d)
      }),
      { numRuns: 100 },
    )
  })

  it('returns empty array for unknown module slug', () => {
    fc.assert(
      fc.property(uniqueSlugsArb(2, 5), (slugs) => {
        const modules = slugs.map((s) => ({ slug: s, dependencies: [] }))
        const result = autoEnableDependencies('nonexistent_module', modules)
        expect(result).toHaveLength(0)
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/*  Property 26: Coming soon modules are non-selectable                */
/* ------------------------------------------------------------------ */

describe('Property 26: Coming soon modules are non-selectable', () => {
  it('returns true for modules with coming_soon status', () => {
    fc.assert(
      fc.property(slugArb, (slug) => {
        const module = { slug, status: 'coming_soon' }
        expect(isComingSoon(module)).toBe(true)
      }),
      { numRuns: 100 },
    )
  })

  it('returns false for modules with available status', () => {
    fc.assert(
      fc.property(slugArb, (slug) => {
        const module = { slug, status: 'available' }
        expect(isComingSoon(module)).toBe(false)
      }),
      { numRuns: 100 },
    )
  })

  it('returns false for any status that is not coming_soon', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 30 }).filter((s) => s !== 'coming_soon'),
        (status) => {
          const module = { status }
          expect(isComingSoon(module)).toBe(false)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('is deterministic — same input always gives same result', () => {
    fc.assert(
      fc.property(moduleStatusArb, (status) => {
        const module = { status }
        const result1 = isComingSoon(module)
        const result2 = isComingSoon(module)
        expect(result1).toBe(result2)
      }),
      { numRuns: 100 },
    )
  })
})
