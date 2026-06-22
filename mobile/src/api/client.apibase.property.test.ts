import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { resolveApiBase } from './client'
import type { PortalType } from '@/contexts/PortalSelectionContext'

/**
 * Feature: organisation-employee-portal, Property 23: Mobile per-portal API base resolution
 *
 * **Validates: Requirements 11.8**
 *
 * Property 23: Mobile per-portal API base resolution
 *
 * For any persisted portal type, resolving the API base/origin is
 * deterministic and yields the correct surface for that type
 * (`org → …/api/v1`, `employee → …/e/api`, `fleet → …/fleet/api`), so a
 * persisted selection always targets the chosen portal's backend on every
 * restart.
 *
 * The exhaustive fast-check property (≥100 runs) complements the example-based
 * unit tests in `client.portal.test.ts`.
 */

// ---------------------------------------------------------------------------
// Generators
// ---------------------------------------------------------------------------

/** Every valid portal type. */
const portalTypeArb: fc.Arbitrary<PortalType> = fc.constantFrom('org', 'employee', 'fleet')

/**
 * Origins the resolver must handle:
 * - empty / relative web origin (`''`) — nginx proxies relative paths
 * - absolute native-style origins (scheme + host, optional port, no trailing slash)
 */
const originArb: fc.Arbitrary<string> = fc.oneof(
  fc.constant(''),
  fc.tuple(
    fc.constantFrom('https', 'http'),
    fc.domain(),
    fc.option(fc.integer({ min: 1, max: 65535 }), { nil: undefined }),
  ).map(([scheme, host, port]) =>
    port === undefined ? `${scheme}://${host}` : `${scheme}://${host}:${port}`,
  ),
)

/** The expected path suffix for each portal type. */
const SUFFIX: Record<PortalType, string> = {
  org: '/api/v1',
  employee: '/e/api',
  fleet: '/fleet/api',
}

// ---------------------------------------------------------------------------
// Property tests
// ---------------------------------------------------------------------------

describe('Property 23: Mobile per-portal API base resolution', () => {
  it('yields the correct surface suffix for every portal type and origin', () => {
    fc.assert(
      fc.property(portalTypeArb, originArb, (portalType, origin) => {
        expect(resolveApiBase(portalType, origin)).toBe(`${origin}${SUFFIX[portalType]}`)
      }),
      { numRuns: 200 },
    )
  })

  it('is deterministic — same input always yields the same output', () => {
    fc.assert(
      fc.property(portalTypeArb, originArb, (portalType, origin) => {
        const first = resolveApiBase(portalType, origin)
        const second = resolveApiBase(portalType, origin)
        const third = resolveApiBase(portalType, origin)
        expect(second).toBe(first)
        expect(third).toBe(first)
      }),
      { numRuns: 200 },
    )
  })

  it('maps each portal type to a distinct surface for the same origin', () => {
    fc.assert(
      fc.property(originArb, (origin) => {
        const org = resolveApiBase('org', origin)
        const employee = resolveApiBase('employee', origin)
        const fleet = resolveApiBase('fleet', origin)
        expect(new Set([org, employee, fleet]).size).toBe(3)
      }),
      { numRuns: 200 },
    )
  })

  it('always preserves the given origin as a prefix of the resolved base', () => {
    fc.assert(
      fc.property(portalTypeArb, originArb, (portalType, origin) => {
        const base = resolveApiBase(portalType, origin)
        expect(base.startsWith(origin)).toBe(true)
        expect(base.length).toBeGreaterThan(origin.length)
      }),
      { numRuns: 200 },
    )
  })
})
