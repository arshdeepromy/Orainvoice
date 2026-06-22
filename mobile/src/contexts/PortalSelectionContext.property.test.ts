// Feature: organisation-employee-portal, Property 22: Mobile portal-selection persistence round-trip
// **Validates: Requirements 11.1, 11.4**

import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as fc from 'fast-check'

/**
 * Property 22: Mobile portal-selection persistence round-trip.
 *
 * Validates: Requirements 11.1, 11.4
 *
 * For any valid PortalSelection, persisting it (save) and then reading it back
 * (load) on a fresh "app start" SHALL return an equal selection — the choice
 * survives an app restart (R11.1). For any absent, malformed, or garbage blob,
 * load SHALL resolve to "no selection" (null) rather than throwing, so the
 * Portal_Type_Selector is shown instead of the app crashing (R11.4).
 *
 * The Capacitor Preferences plugin is mocked with an in-memory store so the
 * production persistence path (native shell) is exercised, and a blob can be
 * injected directly to simulate corruption written by a previous app version.
 */

// In-memory backing store for the mocked Capacitor Preferences plugin.
const { store } = vi.hoisted(() => ({ store: new Map<string, string>() }))

vi.mock('@capacitor/preferences', () => ({
  Preferences: {
    get: async ({ key }: { key: string }) => ({
      value: store.has(key) ? (store.get(key) as string) : null,
    }),
    set: async ({ key, value }: { key: string; value: string }) => {
      store.set(key, value)
    },
    remove: async ({ key }: { key: string }) => {
      store.delete(key)
    },
  },
}))

import {
  loadPortalSelection,
  savePortalSelection,
  clearPortalSelection,
  PORTAL_SELECTION_KEY,
  type PortalSelection,
  type PortalType,
} from './PortalSelectionContext'

beforeEach(() => {
  // Make the context take the native Capacitor Preferences path (the production
  // path on device), backed by our in-memory store.
  ;(window as unknown as { Capacitor?: unknown }).Capacitor = {
    isNativePlatform: () => true,
  }
  store.clear()
})

// ---------------------------------------------------------------------------
// Arbitraries
// ---------------------------------------------------------------------------

const PORTAL_TYPES: readonly PortalType[] = ['org', 'employee', 'fleet']

const portalTypeArb = fc.constantFrom<PortalType>(...PORTAL_TYPES)

/** A valid PortalSelection: known portal_type, non-empty api_base, optional string fields. */
const validSelectionArb: fc.Arbitrary<PortalSelection> = fc.record(
  {
    portal_type: portalTypeArb,
    api_base: fc.string({ minLength: 1 }),
    org_id: fc.option(fc.string(), { nil: undefined }),
    slug: fc.option(fc.string(), { nil: undefined }),
  },
  { requiredKeys: ['portal_type', 'api_base'] },
)

/** Build the expected canonical form (optional fields omitted when undefined). */
function canonical(sel: PortalSelection): PortalSelection {
  const out: PortalSelection = { portal_type: sel.portal_type, api_base: sel.api_base }
  if (sel.org_id !== undefined) out.org_id = sel.org_id
  if (sel.slug !== undefined) out.slug = sel.slug
  return out
}

/** Garbage / malformed blobs that must NOT parse to a valid selection. */
const malformedBlobArb: fc.Arbitrary<string> = fc.oneof(
  // Non-JSON strings (guaranteed to fail JSON.parse).
  fc.string().filter((s) => {
    try {
      JSON.parse(s)
      return false
    } catch {
      return true
    }
  }),
  // Valid JSON, but a primitive (not an object).
  fc.oneof(fc.integer(), fc.boolean(), fc.constant(null), fc.double({ noNaN: true })).map((v) =>
    JSON.stringify(v),
  ),
  // Valid JSON, but a string primitive.
  fc.string().map((s) => JSON.stringify(s)),
  // Valid JSON, but an array.
  fc.array(fc.anything()).map((a) => JSON.stringify(a)),
  // Object missing portal_type.
  fc.record({ api_base: fc.string({ minLength: 1 }) }).map((o) => JSON.stringify(o)),
  // Object with an invalid portal_type value.
  fc
    .record({
      portal_type: fc.string().filter((s) => !PORTAL_TYPES.includes(s as PortalType)),
      api_base: fc.string({ minLength: 1 }),
    })
    .map((o) => JSON.stringify(o)),
  // Object with valid portal_type but missing api_base.
  fc.record({ portal_type: portalTypeArb }).map((o) => JSON.stringify(o)),
  // Object with empty api_base.
  fc
    .record({ portal_type: portalTypeArb, api_base: fc.constant('') })
    .map((o) => JSON.stringify(o)),
  // Object with wrong api_base type.
  fc
    .record({ portal_type: portalTypeArb, api_base: fc.integer() })
    .map((o) => JSON.stringify(o)),
  // Object with wrong org_id type (number).
  fc
    .record({ portal_type: portalTypeArb, api_base: fc.string({ minLength: 1 }), org_id: fc.integer() })
    .map((o) => JSON.stringify(o)),
  // Object with wrong slug type (boolean).
  fc
    .record({ portal_type: portalTypeArb, api_base: fc.string({ minLength: 1 }), slug: fc.boolean() })
    .map((o) => JSON.stringify(o)),
)

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Property 22: Mobile portal-selection persistence round-trip', () => {
  it('save → load returns an equal selection (survives restart) [R11.1]', async () => {
    await fc.assert(
      fc.asyncProperty(validSelectionArb, async (sel) => {
        store.clear()
        const ok = await savePortalSelection(sel)
        expect(ok).toBe(true)

        // Simulate a fresh app start: read the persisted value back.
        const loaded = await loadPortalSelection()
        expect(loaded).toEqual(canonical(sel))
      }),
      { numRuns: 200 },
    )
  })

  it('absent selection loads as "no selection" (null) [R11.4]', async () => {
    await fc.assert(
      fc.asyncProperty(fc.constant(null), async () => {
        store.clear()
        const loaded = await loadPortalSelection()
        expect(loaded).toBeNull()
      }),
      { numRuns: 100 },
    )
  })

  it('malformed / garbage blobs load as "no selection" (null), never crashing [R11.4]', async () => {
    await fc.assert(
      fc.asyncProperty(malformedBlobArb, async (blob) => {
        store.clear()
        // A previous app version (or corruption) wrote a bad blob to storage.
        store.set(PORTAL_SELECTION_KEY, blob)

        const loaded = await loadPortalSelection()
        expect(loaded).toBeNull()
      }),
      { numRuns: 200 },
    )
  })

  it('load never throws for ANY stored blob; result is null or a valid selection [R11.4]', async () => {
    await fc.assert(
      fc.asyncProperty(fc.string(), async (raw) => {
        store.clear()
        store.set(PORTAL_SELECTION_KEY, raw)

        const loaded = await loadPortalSelection()
        if (loaded !== null) {
          // If anything is returned it must be a well-formed selection.
          expect(PORTAL_TYPES).toContain(loaded.portal_type)
          expect(typeof loaded.api_base).toBe('string')
          expect(loaded.api_base.length).toBeGreaterThan(0)
          if (loaded.org_id !== undefined) expect(typeof loaded.org_id).toBe('string')
          if (loaded.slug !== undefined) expect(typeof loaded.slug).toBe('string')
        }
      }),
      { numRuns: 200 },
    )
  })

  it('clear then load returns "no selection" (null) for any prior selection [R11.4]', async () => {
    await fc.assert(
      fc.asyncProperty(validSelectionArb, async (sel) => {
        store.clear()
        await savePortalSelection(sel)
        await clearPortalSelection()

        const loaded = await loadPortalSelection()
        expect(loaded).toBeNull()
      }),
      { numRuns: 100 },
    )
  })
})
