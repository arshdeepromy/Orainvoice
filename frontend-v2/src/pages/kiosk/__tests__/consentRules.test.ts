/**
 * E3 — resolveInspectionTypeRow per-vehicle resolution (Req 1.5a–1.5e).
 *
 * Feature: customer-reminder-consent
 */

import { describe, it, expect } from 'vitest'
import { resolveInspectionTypeRow, inspectionCategory } from '../consentRules'

type V = Parameters<typeof resolveInspectionTypeRow>[0]

function v(overrides: Partial<V> = {}): V {
  return { inspection_type: null, wof_expiry: null, cof_expiry: null, ...overrides }
}

describe('resolveInspectionTypeRow', () => {
  it('5a — explicit inspection_type=wof → wof', () => {
    expect(resolveInspectionTypeRow(v({ inspection_type: 'wof' }))).toBe('wof')
  })

  it('5b — explicit inspection_type=cof → cof', () => {
    expect(resolveInspectionTypeRow(v({ inspection_type: 'cof' }))).toBe('cof')
  })

  it('explicit type wins even when the other expiry is set', () => {
    expect(
      resolveInspectionTypeRow(v({ inspection_type: 'wof', cof_expiry: '2026-08-01' })),
    ).toBe('wof')
  })

  it('5c — both expiries, no type → cof (heavier compliance)', () => {
    expect(
      resolveInspectionTypeRow(v({ wof_expiry: '2026-07-01', cof_expiry: '2026-08-01' })),
    ).toBe('cof')
  })

  it('5c — only cof_expiry → cof', () => {
    expect(resolveInspectionTypeRow(v({ cof_expiry: '2026-08-01' }))).toBe('cof')
  })

  it('5c — only wof_expiry → wof', () => {
    expect(resolveInspectionTypeRow(v({ wof_expiry: '2026-07-01' }))).toBe('wof')
  })

  it('5d — neither type nor expiry → none', () => {
    expect(resolveInspectionTypeRow(v())).toBe('none')
  })
})

describe('inspectionCategory', () => {
  it('maps rows to categories', () => {
    expect(inspectionCategory('wof')).toBe('wof_expiry')
    expect(inspectionCategory('cof')).toBe('cof_expiry')
    expect(inspectionCategory('none')).toBeNull()
  })
})
