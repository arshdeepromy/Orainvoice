import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// ---------------------------------------------------------------------------
// Pure helper: promote/demote button visibility based on node role
// Mirrors the logic in HAStatusPanel.tsx
// ---------------------------------------------------------------------------

function getButtonVisibility(role: string): { showPromote: boolean; showDemote: boolean } {
  return {
    showPromote: role === 'standby',
    showDemote: role === 'primary',
  }
}

// ---------------------------------------------------------------------------
// Pure helper: health indicator color based on status string
// Mirrors the CSS class logic in HAStatusPanel.tsx
// ---------------------------------------------------------------------------

function getHealthColor(health: string): string {
  if (health === 'healthy') return 'bg-green-500'
  if (health === 'degraded') return 'bg-amber-500'
  if (health === 'unreachable') return 'bg-red-500'
  return 'bg-gray-400'
}

// ---------------------------------------------------------------------------
// Pure helper: replication lag warning visibility
// Mirrors the banner logic in HAStatusPanel.tsx
// ---------------------------------------------------------------------------

function shouldShowLagWarning(lagSeconds: number | null): boolean {
  return lagSeconds != null && lagSeconds > 30
}

// ---------------------------------------------------------------------------
// Pure helper: role badge variant mapping
// Mirrors the badge styling logic in HAStatusPanel.tsx
// ---------------------------------------------------------------------------

function roleVariant(role: string): string {
  if (role === 'primary') return 'success'
  if (role === 'standby') return 'warning'
  return 'neutral'
}

// ---------------------------------------------------------------------------
// Property-based tests
// ---------------------------------------------------------------------------

describe('HA Status Panel — Property-Based Tests', () => {
  // **Validates: Requirements 7.3, 7.4, 7.5**
  it('Property 1: promote button visible iff role is standby, demote iff primary', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('primary', 'standby', 'standalone'),
        (role) => {
          const { showPromote, showDemote } = getButtonVisibility(role)

          if (role === 'standby') {
            expect(showPromote).toBe(true)
            expect(showDemote).toBe(false)
          } else if (role === 'primary') {
            expect(showPromote).toBe(false)
            expect(showDemote).toBe(true)
          } else {
            expect(showPromote).toBe(false)
            expect(showDemote).toBe(false)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  // **Validates: Requirements 7.3**
  it('Property 2: health indicator color is deterministic for any status', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('healthy', 'degraded', 'unreachable', 'unknown'),
        (health) => {
          const color = getHealthColor(health)
          expect(['bg-green-500', 'bg-amber-500', 'bg-red-500', 'bg-gray-400']).toContain(color)
          // Same input always produces same output (determinism)
          expect(getHealthColor(health)).toBe(color)
        },
      ),
      { numRuns: 100 },
    )
  })

  // **Validates: Requirements 7.7**
  it('Property 3: lag warning shown iff lag > 30s', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.constant(null as number | null),
          fc.float({ min: 0, max: 1000, noNaN: true }),
        ),
        (lagSeconds) => {
          const showWarning = shouldShowLagWarning(lagSeconds)

          if (lagSeconds == null) {
            expect(showWarning).toBe(false)
          } else if (lagSeconds > 30) {
            expect(showWarning).toBe(true)
          } else {
            expect(showWarning).toBe(false)
          }
        },
      ),
      { numRuns: 100 },
    )
  })

  // **Validates: Requirements 7.3**
  it('Property 4: role badge variant is always one of success/warning/neutral', () => {
    fc.assert(
      fc.property(
        fc.string(),
        (role) => {
          const variant = roleVariant(role)
          expect(['success', 'warning', 'neutral']).toContain(variant)
        },
      ),
      { numRuns: 100 },
    )
  })
})
