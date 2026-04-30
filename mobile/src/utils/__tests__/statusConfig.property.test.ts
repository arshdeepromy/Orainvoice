// Feature: mobile-konsta-redesign, Property 6: Status colour mapping completeness
// **Validates: Requirements 10.3, 56.2**

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { STATUS_CONFIG } from '@/utils/statusConfig'

/**
 * Property 6: Status colour mapping completeness.
 *
 * For any valid invoice status key in the set {draft, issued, partially_paid,
 * paid, overdue, voided, refunded, partially_refunded}, STATUS_CONFIG[status]
 * SHALL return an object with a non-empty `label` string, a non-empty `color`
 * string containing a Tailwind text colour class, and a non-empty `bg` string
 * containing a Tailwind background colour class.
 */
describe('Property 6: Status colour mapping completeness', () => {
  const validStatuses = [
    'draft',
    'issued',
    'partially_paid',
    'paid',
    'overdue',
    'voided',
    'refunded',
    'partially_refunded',
  ] as const

  const statusArb = fc.constantFrom(...validStatuses)

  it('every valid status has a non-empty label', () => {
    fc.assert(
      fc.property(statusArb, (status) => {
        const config = STATUS_CONFIG[status]
        expect(config).toBeDefined()
        expect(config.label).toBeTruthy()
        expect(config.label.length).toBeGreaterThan(0)
      }),
      { numRuns: 200 },
    )
  })

  it('every valid status has a Tailwind text colour class', () => {
    fc.assert(
      fc.property(statusArb, (status) => {
        const config = STATUS_CONFIG[status]
        expect(config.color).toBeTruthy()
        expect(config.color).toMatch(/^text-/)
      }),
      { numRuns: 200 },
    )
  })

  it('every valid status has a Tailwind background colour class', () => {
    fc.assert(
      fc.property(statusArb, (status) => {
        const config = STATUS_CONFIG[status]
        expect(config.bg).toBeTruthy()
        expect(config.bg).toMatch(/^bg-/)
      }),
      { numRuns: 200 },
    )
  })

  it('all 8 statuses are present in STATUS_CONFIG', () => {
    for (const status of validStatuses) {
      expect(STATUS_CONFIG[status]).toBeDefined()
    }
  })

  it('label, color, and bg are all strings', () => {
    fc.assert(
      fc.property(statusArb, (status) => {
        const config = STATUS_CONFIG[status]
        expect(typeof config.label).toBe('string')
        expect(typeof config.color).toBe('string')
        expect(typeof config.bg).toBe('string')
      }),
      { numRuns: 200 },
    )
  })
})
