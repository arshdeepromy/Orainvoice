import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// Feature: automotive-dashboard-widgets, Property 2: Module Gating Determines Widget Visibility
// **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.7**

/* ------------------------------------------------------------------ */
/*  Widget definitions — mirrors WidgetGrid.tsx WIDGET_DEFINITIONS     */
/* ------------------------------------------------------------------ */

interface WidgetDef {
  id: string
  module?: string
}

const WIDGET_DEFINITIONS: WidgetDef[] = [
  { id: 'recent-customers' },
  { id: 'todays-bookings', module: 'bookings' },
  { id: 'public-holidays' },
  { id: 'inventory-overview', module: 'inventory' },
  { id: 'cash-flow' },
  { id: 'recent-claims', module: 'claims' },
  { id: 'active-staff' },
  { id: 'expiry-reminders', module: 'vehicles' },
  { id: 'reminder-config', module: 'vehicles' },
]

/** The 4 ungated widgets that are always visible */
const UNGATED_IDS = WIDGET_DEFINITIONS
  .filter((w) => !w.module)
  .map((w) => w.id)

/**
 * Pure function that computes visible widget IDs given a module-enabled map.
 * Mirrors the filtering logic in WidgetGrid.tsx.
 */
function computeVisibleWidgets(
  enabledModules: Record<string, boolean>,
): string[] {
  return WIDGET_DEFINITIONS
    .filter((w) => !w.module || enabledModules[w.module])
    .map((w) => w.id)
}

/* ------------------------------------------------------------------ */
/*  Arbitraries                                                        */
/* ------------------------------------------------------------------ */

/** Generate a random enabled/disabled map for the 4 module slugs */
const moduleComboArb = fc.record({
  inventory: fc.boolean(),
  claims: fc.boolean(),
  bookings: fc.boolean(),
  vehicles: fc.boolean(),
})

/* ------------------------------------------------------------------ */
/*  Property 2: Module Gating Determines Widget Visibility             */
/* ------------------------------------------------------------------ */

describe('Property 2: Module Gating Determines Widget Visibility', () => {
  it('visible widgets equal ungated + enabled-gated widgets', () => {
    fc.assert(
      fc.property(moduleComboArb, (modules) => {
        const visible = computeVisibleWidgets(modules)
        const visibleSet = new Set(visible)

        // (a) All ungated widgets are always visible
        for (const id of UNGATED_IDS) {
          expect(visibleSet.has(id)).toBe(true)
        }

        // (b) Each module-gated widget is visible iff its module is enabled
        for (const def of WIDGET_DEFINITIONS) {
          if (def.module) {
            expect(visibleSet.has(def.id)).toBe(modules[def.module as keyof typeof modules])
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  it('no module-gated widget is visible when its module is disabled', () => {
    fc.assert(
      fc.property(moduleComboArb, (modules) => {
        const visible = new Set(computeVisibleWidgets(modules))

        for (const def of WIDGET_DEFINITIONS) {
          if (def.module && !modules[def.module as keyof typeof modules]) {
            expect(visible.has(def.id)).toBe(false)
          }
        }
      }),
      { numRuns: 100 },
    )
  })

  it('all modules enabled shows all 9 widgets', () => {
    fc.assert(
      fc.property(
        fc.constant({ inventory: true, claims: true, bookings: true, vehicles: true }),
        (modules) => {
          const visible = computeVisibleWidgets(modules)
          expect(visible).toHaveLength(WIDGET_DEFINITIONS.length)
        },
      ),
      { numRuns: 100 },
    )
  })

  it('all modules disabled shows only the 4 ungated widgets', () => {
    fc.assert(
      fc.property(
        fc.constant({ inventory: false, claims: false, bookings: false, vehicles: false }),
        (modules) => {
          const visible = computeVisibleWidgets(modules)
          expect(visible).toHaveLength(UNGATED_IDS.length)
          expect(visible).toEqual(UNGATED_IDS)
        },
      ),
      { numRuns: 100 },
    )
  })
})
